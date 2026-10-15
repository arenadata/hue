#!/usr/bin/env python
# Licensed to Cloudera, Inc. under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  Cloudera, Inc. licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Vault client for resolving vault:// references in configuration.
"""

from __future__ import annotations

import os
import re
import time
import base64
import logging
import tempfile
import ipaddress
import subprocess
from typing import Any, Optional
from urllib.parse import urlparse

try:
    import hvac
    from hvac.api.auth_methods import Kubernetes
    from hvac.exceptions import Forbidden, InvalidPath
    HAS_HVAC = True
except ImportError:
    HAS_HVAC = False
    hvac = None
    InvalidPath = Exception
    Forbidden = Exception
    Kubernetes = None

try:
    import gssapi
    HAS_GSSAPI = True
except ImportError:
    gssapi = None
    HAS_GSSAPI = False

from requests import Session
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

from desktop.lib.vault_conf import VaultConfig, get_vault_config

global _resolver

LOG = logging.getLogger()

# Pattern for vault references: vault://path/to/secret?key=fieldname
# or vault://path/to/secret (key=value by default)
VAULT_REF_PATTERN = re.compile(r'^vault://(?P<path>[^?]+)(\?key=(?P<key>[^&]+))?$')


def _default_ccache_path() -> str:
    """Dedicated credential cache so vault logins never touch the default one."""
    return os.path.join(tempfile.gettempdir(), 'hue_vault_ccache_%d' % os.getpid())


def _response_errors(response) -> Optional[list]:
    try:
        return response.json().get('errors')
    except Exception:
        return None


def _build_spnego_authorization(url, service_principal=None, keytab_path=None, principal=None,
                                 ccache_path=None) -> Optional[str]:
    """
  Build the Authorization header for a single-leg Kerberos SPNEGO login.
  The target service is HTTP@<host of url> unless service_principal gives a
  full SPN; credentials come from keytab_path (with its own ccache) or from
  the environment's default credential cache.
  """
    if not HAS_GSSAPI:
        LOG.error("gssapi library is not installed; Kerberos authentication for Vault is unavailable")
        return None

    if service_principal:
        target = gssapi.Name(service_principal, gssapi.NameType.kerberos_principal)
    else:
        host = (urlparse(url).hostname or '').lower().rstrip('.')
        try:
            is_ip = ipaddress.ip_address(host) is not None
        except ValueError:
            is_ip = False
        if not host or is_ip:
            LOG.error("Vault URL must use a host name, not an IP, for Kerberos, or kerberos_service_principal must be set: %s", url)
            return None
        target = gssapi.Name('HTTP@%s' % host, gssapi.NameType.hostbased_service)

    store = {}
    if keytab_path:
        store['client_keytab'] = keytab_path
        store['ccache'] = 'FILE:%s' % (ccache_path or _default_ccache_path())
    elif ccache_path:
        store['ccache'] = 'FILE:%s' % ccache_path

    kwargs = {'usage': 'initiate'}
    if principal:
        kwargs['principal'] = gssapi.Name(principal, gssapi.NameType.kerberos_principal)
    if store:
        kwargs['store'] = store
    creds = gssapi.Credentials(**kwargs)

    context = gssapi.SecurityContext(name=target, creds=creds)
    token = context.step()
    if not token:
        LOG.error("Kerberos SPNEGO token was not produced for %s", url)
        return None
    return 'Negotiate %s' % base64.b64encode(token).decode('ascii')


class VaultClient:
    """Minimal Vault client for retrieving secrets."""

    def __init__(self, config: VaultConfig):
        """
        Initialize Vault client with VaultConfig.

        Args:
            config: VaultConfig instance with connection parameters
        """
        self.config = config
        self._client: Optional[Any] = None
        self._initialized = False
        self._token = None
        self._token_expiry = None

        if not HAS_HVAC:
            LOG.warning("hvac library is not installed. Vault integration is disabled.")
            return

        self._init_client()

    def _init_client(self):
        """Initialize the actual Vault client."""
        try:
            # Create base client
            adapter = HTTPAdapter(
                max_retries=Retry(
                    total=3,
                    backoff_factor=0.1,
                    status_forcelist=[412, 500, 502, 503],
                    raise_on_status=False,
                )
            )
            session = Session()
            session.mount("http://", adapter)
            session.mount("https://", adapter)

            self._client = hvac.Client(
                url=self.config.url,
                verify=self.config.verify,
                cert=self.config.cert,
                timeout=self.config.timeout,
                session=session,
                namespace=self.config.namespace,
            )

            # Authenticate based on auth_type
            auth_methods = {
                'token': self._authenticate_token,
                'userpass': self._authenticate_userpass,
                'ldap': self._authenticate_ldap,
                'kubernetes': self._authenticate_kubernetes,
                'kerberos': self._authenticate_kerberos,
            }

            auth_method = auth_methods.get(self.config.auth_type)
            if not auth_method:
                LOG.error("Unsupported authentication type: %s", self.config.auth_type)
                self._client = None
                return

            if auth_method(self._client):
                LOG.info("Vault client authenticated successfully. URL: %s, Auth: %s, Mount: %s, KV Version: %d",
                         self.config.url, self.config.auth_type, self.config.mount_point, int(self.config.kv_engine_version))
                self._initialized = True
            else:
                LOG.error("Vault client authentication failed for auth type: %s", self.config.auth_type)
                self._client = None

        except Exception as e:
            LOG.error("Failed to initialize Vault client: %s", e)
            self._client = None

    @property
    def client(self):
        return self._client

    def _authenticate_token(self, client_: hvac.Client) -> bool:
        """Authenticate using token."""
        token = self.config.token or self._get_token_from_file()
        if not token:
            LOG.error("No token provided for token authentication in VaultClient")
            return False

        client_.token = token
        return client_.is_authenticated()

    def _authenticate_userpass(self, client_: hvac.Client) -> bool:
        """Authenticate using username/password."""
        password = self._get_password()
        if not self.config.username or not password:
            LOG.error("Username or password missing for userpass authentication")
            return False

        mount_point = self.config.auth_mount_point or "userpass"
        try:
            client_.auth.userpass.login(
                username=self.config.username,
                password=password,
                mount_point=mount_point
            )
            return client_.is_authenticated()
        except Exception as e:
            LOG.error("Userpass authentication failed: %s", e)
            return False

    def _authenticate_ldap(self, client_: hvac.Client) -> bool:
        """Authenticate using LDAP."""
        password = self._get_password()
        if not self.config.username or not password:
            LOG.error("Username or password missing for LDAP authentication")
            return False

        mount_point = self.config.auth_mount_point or "ldap"
        try:
            client_.auth.ldap.login(
                username=self.config.username,
                password=password,
                mount_point=mount_point
            )
            return client_.is_authenticated()
        except Exception as e:
            LOG.error("LDAP authentication failed: %s", e)
            return False

    def _authenticate_kubernetes(self, client_: hvac.Client) -> bool:
        """Authenticate using Kubernetes service account."""
        if not self.config.kubernetes_role:
            LOG.error("Kubernetes role is required")
            return False

        jwt = self._get_kubernetes_jwt()
        if not jwt:
            LOG.error("Failed to get Kubernetes JWT token")
            return False

        mount_point = self.config.auth_mount_point
        try:
            if mount_point:
                Kubernetes(client_.adapter).login(
                    role=self.config.kubernetes_role, jwt=jwt, mount_point=self.config.auth_mount_point
                )
            else:
                Kubernetes(client_.adapter).login(role=self.config.kubernetes_role, jwt=jwt)
            return client_.is_authenticated()
        except Exception as e:
            LOG.error("Kubernetes authentication failed: %s", e)
            return False

    def _authenticate_kerberos(self, client_: hvac.Client) -> bool:
        """
    Authenticate through the Kerberos (SPNEGO) auth mount of OpenBao/Vault:
    a single POST carrying an Authorization: Negotiate header, answered with
    a client token.
    """
        if self.config.krb5_conf_path:
            os.environ['KRB5_CONFIG'] = self.config.krb5_conf_path

        header = _build_spnego_authorization(
            url=self.config.url,
            service_principal=self.config.kerberos_service_principal,
            keytab_path=self.config.keytab_path,
            principal=self.config.principal,
            ccache_path=self.config.ccache_path,
        )
        if not header:
            return False

        mount_point = self.config.auth_mount_point or 'kerberos'
        body = {'role': self.config.kerberos_role} if self.config.kerberos_role else {}
        try:
            response = client_.adapter.post(
                '/v1/auth/%s/login' % mount_point, json=body, headers={'Authorization': header}
            )
        except Exception as e:
            LOG.error("Kerberos login request to Vault failed: %s", e)
            return False

        auth = response.get('auth') if isinstance(response, dict) else None
        if not auth or not auth.get('client_token'):
            errors = response.get('errors') if isinstance(response, dict) else _response_errors(response)
            LOG.error("Kerberos login to Vault failed: %s", errors or 'no client token in response')
            return False

        client_.token = auth['client_token']
        self._token_expiry = time.time() + auth['lease_duration'] if auth.get('lease_duration') else None
        return True

    def _get_password(self) -> Optional[str]:
        """Get password from config or script."""
        if self.config.password:
            return self.config.password
        if self.config.password_script:
            return self._get_password_from_script()
        return None

    def _get_password_from_script(self) -> Optional[str]:
        """Execute script to get password."""
        script = self.config.password_script
        if not script:
            return None

        try:
            result = subprocess.run(
                script,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode == 0:
                return result.stdout.strip('\n')
            else:
                LOG.error("Password script failed: %s", result.stderr)
                return None
        except Exception as e:
            LOG.error("Failed to execute password script: %s", e)
            return None

    def _get_token_from_file(self) -> Optional[str]:
        """Read token from file."""
        token_path = self.config.token_path
        if not token_path or not os.path.exists(token_path):
            return None

        try:
            with open(token_path, 'r') as f:
                return f.read().strip()
        except Exception as e:
            LOG.error("Failed to read token from %s: %s", token_path, e)
            return None

    def _get_kubernetes_jwt(self) -> Optional[str]:
        """Get Kubernetes JWT token from file."""
        if self.config.kubernetes_jwt_path and os.path.exists(self.config.kubernetes_jwt_path):
            try:
                with open(self.config.kubernetes_jwt_path, 'r') as f:
                    return f.read().strip()
            except Exception as e:
                LOG.error("Failed to read Kubernetes JWT: %s", e)
        return None

    @property
    def is_initialized(self):
        return self._initialized and self._client is not None

    def _read_secret_data(self, path: str) -> dict:
        """Read the raw secret dict from the KV engine."""
        LOG.debug("Reading secret: path=%s, mount_point=%s, kv_version=%d",
                  path, self.config.mount_point, int(self.config.kv_engine_version))

        if int(self.config.kv_engine_version) == 1:
            response = self.client.secrets.kv.v1.read_secret(
                path=path,
                mount_point=self.config.mount_point
            )
            return response['data']
        response = self.client.secrets.kv.v2.read_secret_version(
            path=path,
            mount_point=self.config.mount_point
        )
        return response['data']['data']

    def get_secret(self, path: str, key: str = None) -> Optional[Any]:
        """
        Retrieve a secret from Vault.

        Args:
            path: Path to secret in Vault (without mount point)
            key: Optional key to extract from secret dict

        Returns:
            Secret value or entire secret dict if key is None
        """
        if not self.is_initialized:
            LOG.debug("Vault client not initialized")
            return None

        # Use default key if not specified
        if key is None:
            key = self.config.kv_default_key_secret

        # Clean path
        path = path.strip('/')

        try:
            secret_data = self._read_secret_data(path)
        except InvalidPath:
            LOG.warning("Secret not found at path: %s (mount_point=%s)",
                        path, self.config.mount_point)
            return None
        except Forbidden:
            if self.config.auth_type != 'kerberos':
                LOG.error("Permission denied reading secret: %s", path)
                return None
            # The Kerberos token may simply have expired; a new SPNEGO login
            # is cheap with a live credential cache, so retry once.
            LOG.warning("Vault rejected the token, re-authenticating with Kerberos: %s", path)
            if not self._client or not self._authenticate_kerberos(self._client):
                LOG.error("Kerberos re-authentication to Vault failed for secret: %s", path)
                return None
            try:
                secret_data = self._read_secret_data(path)
            except Exception as e:
                LOG.error("Error reading secret from Vault after re-authentication: %s", e)
                return None
        except Exception as e:
            LOG.error("Error reading secret from Vault: %s", str(e))
            return None

        if key:
            result = secret_data.get(key)
            if result is None:
                LOG.warning("Key '%s' not found in secret. Available keys: %s",
                            key, list(secret_data.keys()))
            return result
        return secret_data


class VaultSecretResolver:
    """Resolver for vault:// references in configuration."""

    def __init__(self, config: VaultConfig):
        """
        Initialize resolver with Vault configuration.

        Args:
            config: VaultConfig instance.
        """
        self._client = None
        self._cache = {}
        self._config = config

    def _get_client(self) -> Optional[VaultClient]:
        """Get or create Vault client; a failed one is dropped so the next resolve retries."""
        if self._client is None:
            client = VaultClient(self._config)
            if not client.is_initialized:
                return None
            self._client = client
        return self._client

    def resolve(self, value: str, prefix: str = '') -> Optional[Any]:
        """
        Resolve a vault:// reference to actual secret.

        Args:
            value: String containing vault:// reference
            prefix: Config prefix for logging

        Returns:
            Resolved value or original value if not a vault reference
        """
        if not isinstance(value, str):
            LOG.warning("Invalid vault reference: %s", value)
            return value

        match = VAULT_REF_PATTERN.match(value)
        if not match:
            LOG.warning("Invalid vault reference: %s", value)
            return value

        path = match.group('path')
        key = match.group('key')

        # Check cache
        cache_key = f"{path}:{key}"
        if cache_key in self._cache:
            LOG.debug("Using cached secret for %s", cache_key)
            return self._cache[cache_key]

        # Get from Vault
        client = self._get_client()
        if not client:
            LOG.warning("Vault client not available for reference: %s", value)
            return None

        secret = client.get_secret(path, key)

        if secret is not None:
            self._cache[cache_key] = secret
            LOG.info("Resolved vault reference: %s for config %s", value, prefix)
            return secret

        LOG.warning("Failed to resolve vault reference: %s", value)
        return None

    def clear_cache(self):
        """Clear the secret cache."""
        self._cache.clear()
        LOG.debug("Vault cache cleared")


# Global resolver instance - initialized lazily
VAULT_RESOLVER = None


def _get_resolver(vault_conf: dict) -> VaultSecretResolver:
    """Get or create global resolver."""
    global VAULT_RESOLVER
    if VAULT_RESOLVER is None:
        conf = get_vault_config(vault_conf)
        VAULT_RESOLVER = VaultSecretResolver(conf)
    return VAULT_RESOLVER


def resolve_vault_references(value: str, vault_conf: dict, prefix: str = '') -> Optional[Any]:
    """
    Public function to resolve vault references.
    Called from conf.py when processing configuration values.

    Args:
        value: String possibly containing vault reference
        vault_conf: Vault config map
        prefix: Config prefix for logging

    Returns:
        Resolved value or original value if not a vault reference
    """
    resolver = _get_resolver(vault_conf)
    return resolver.resolve(value, prefix)
