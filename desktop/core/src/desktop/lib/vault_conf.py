import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass, field

LOG = logging.getLogger()


@dataclass
class VaultConfig:
    """
    Configuration class for HashiCorpVault/OpenBao connection.
    Supports multiple authentication methods.
    """

    # Connection settings
    url: str
    namespace: Optional[str] = None
    auth_type: str = "token"  # token, userpass, ldap,  kubernetes

    # KV engine settings
    mount_point: str = "secret"
    kv_engine_version: int = 2
    kv_default_key_secret: str = "value"

    # Token authentication
    token: Optional[str] = None
    token_path: Optional[str] = None

    # Username/Password authentication (userpass, ldap)
    username: Optional[str] = None
    password: Optional[str] = None
    password_script: Optional[str] = None

    # Kubernetes authentication
    kubernetes_role: Optional[str] = None
    kubernetes_jwt_path: str = "/var/run/secrets/kubernetes.io/serviceaccount/token"

    # SSL settings
    verify: Optional[str] = None
    cert: Optional[str] = None

    # Timeout settings
    timeout: int = 30

    # Auth mount point
    auth_mount_point: Optional[str] = None

    # Additional options
    _unknown_params: Dict[str, Any] = field(default_factory=dict, repr=False, init=False)

    def __init__(self, **kwargs):
        dataclass_fields = {f.name for f in self.__dataclass_fields__.values()
                            if not f.name.startswith('_')}

        known_params = {}
        unknown_params = {}

        for key, value in kwargs.items():
            if key in dataclass_fields:
                known_params[key] = value
            else:
                unknown_params[key] = value

        for key, value in known_params.items():
            object.__setattr__(self, key, value)

        object.__setattr__(self, '_unknown_params', unknown_params)
        self._validate_config()

    def _validate_config(self):
        """Validate configuration based on auth type."""
        if not self.url:
            raise ValueError("Vault URL is required")

        if self.auth_type == "token":
            if not self.token and not self.token_path:
                raise ValueError("Either token or token_path is required for token authentication")

        elif self.auth_type in ["userpass", "ldap"]:
            if not self.username:
                raise ValueError("Username is required for %s authentication" % self.auth_type)
            if not self.password and not self.password_script:
                raise ValueError("Either password or password_script is required for %s authentication" % self.auth_type)

        elif self.auth_type == "kubernetes":
            if not self.kubernetes_role:
                raise ValueError("kubernetes_role is required for Kubernetes authentication")

        elif int(self.kv_engine_version) not in [1, 2]:
            raise ValueError("kv_engine_version must be 1 or 2")

    def __repr__(self) -> str:
        """String representation without sensitive data"""
        return f"VaultConfig(url={self.url}, auth_type={self.auth_type}, mount_point={self.mount_point})"


# Global configuration instance
VAULT_CONFIG: Optional[VaultConfig] = None


def init_vault_config(vault_config: dict) -> VaultConfig:
    """
    Initialize global Vault configuration.

    Args:
        vault_config: Vault config map

    Returns:
        Initialized VaultConfig instance
    """
    global VAULT_CONFIG
    
    if not VAULT_CONFIG:
        VAULT_CONFIG = VaultConfig(**vault_config)

    return VAULT_CONFIG


def get_vault_config(vault_config: dict) -> VaultConfig:
    """
    Get global Vault configuration instance.

    Returns:
        VaultConfig instance
    """
    if VAULT_CONFIG is None:
        LOG.info("Vault configuration initialized.")
        init_vault_config(vault_config)
    return VAULT_CONFIG
