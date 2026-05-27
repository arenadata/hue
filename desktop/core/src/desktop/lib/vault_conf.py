import logging
from dataclasses import MISSING, dataclass, field, fields
from typing import Optional, Dict, Any, Union

LOG = logging.getLogger()


@dataclass
class VaultConfig:
    """
    Configuration class for HashiCorpVault/OpenBao connection.
    Supports multiple authentication methods.
    """

    # Connection settings
    url: str = "http://127.0.0.1:8200"
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
    verify: Optional[Union[bool, str]] = True
    cert: Optional[Union[str, tuple]] = None

    # Timeout settings
    timeout: int = 30

    # Auth mount point
    auth_mount_point: Optional[str] = None

    # Additional options
    _unknown_params: Dict[str, Any] = field(default_factory=dict, repr=False, init=False, compare=False)

    def __post_init__(self):
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

        if int(self.kv_engine_version) not in [1, 2]:
            raise ValueError("kv_engine_version must be 1 or 2")

    def __repr__(self) -> str:
        """String representation without sensitive data"""
        return f"VaultConfig(url={self.url}, auth_type={self.auth_type}, mount_point={self.mount_point})"


# Global configuration instance
VAULT_CONFIG: Optional[VaultConfig] = None


_SECTION_TO_CONFIG_FIELD = {
    'url': 'URL',
    'namespace': 'NAMESPACE',
    'auth_type': 'AUTH_TYPE',
    'mount_point': 'MOUNT_POINT',
    'kv_engine_version': 'KV_ENGINE_VERSION',
    'kv_default_key_secret': 'KV_DEFAULT_KEY_SECRET',
    'token': 'TOKEN',
    'token_path': 'TOKEN_PATH',
    'username': 'USERNAME',
    'password': 'PASSWORD',
    'password_script': 'PASSWORD_SCRIPT',
    'kubernetes_role': 'KUBERNETES_ROLE',
    'kubernetes_jwt_path': 'KUBERNETES_JWT_PATH',
    'verify': 'VERIFY_SSL',
    'cert': 'CERT',
    'timeout': 'TIMEOUT',
    'auth_mount_point': 'AUTH_MOUNT_POINT',
}


def _default_config_values() -> Dict[str, Any]:
    defaults = {}

    for config_field in fields(VaultConfig):
        if config_field.name.startswith('_'):
            continue

        if config_field.default is not MISSING:
            defaults[config_field.name] = config_field.default
        elif config_field.default_factory is not MISSING:
            defaults[config_field.name] = config_field.default_factory()
        else:
            defaults[config_field.name] = None

    return defaults


def _coerce_verify(value):
    if isinstance(value, str):
        lowered = value.lower()
        if lowered == 'true':
            return True
        if lowered == 'false':
            return False
    return value


def _coerce_cert(value):
    if isinstance(value, list):
        return tuple(value)
    if isinstance(value, str) and ',' in value:
        return tuple(part.strip() for part in value.split(','))
    return value


def _coerce_int(value):
    if value is None or isinstance(value, int):
        return value
    return int(value)


def _is_bound_vault_section(vault_config: Any) -> bool:
    return hasattr(vault_config, 'URL') and hasattr(getattr(vault_config, 'URL'), 'get')


def _read_bound_vault_section(vault_config: Any) -> Dict[str, Any]:
    return {
        key: getattr(vault_config, section_name).get()
        for key, section_name in _SECTION_TO_CONFIG_FIELD.items()
    }


def _normalize_vault_config(vault_config: Union['VaultConfig', dict, Any]) -> VaultConfig:
    if isinstance(vault_config, VaultConfig):
        return vault_config

    if _is_bound_vault_section(vault_config):
        normalized = _read_bound_vault_section(vault_config)
        unknown_params = {}
    elif isinstance(vault_config, dict):
        normalized = dict(vault_config)
        unknown_params = {
            key: value for key, value in normalized.items() if key not in _SECTION_TO_CONFIG_FIELD
        }
    else:
        raise TypeError("Vault configuration must be a dict, VaultConfig, or bound config section")

    config_data = _default_config_values()
    config_data.update({key: value for key, value in normalized.items() if key in config_data})
    config_data['verify'] = _coerce_verify(config_data['verify'])
    config_data['cert'] = _coerce_cert(config_data['cert'])
    config_data['timeout'] = _coerce_int(config_data['timeout'])
    config_data['kv_engine_version'] = _coerce_int(config_data['kv_engine_version'])

    config = VaultConfig(**config_data)
    object.__setattr__(config, '_unknown_params', unknown_params)
    return config


def init_vault_config(vault_config: Union[VaultConfig, dict, Any]) -> VaultConfig:
    """
    Initialize global Vault configuration.

    Args:
        vault_config: Vault config map

    Returns:
        Initialized VaultConfig instance
    """
    global VAULT_CONFIG

    normalized = _normalize_vault_config(vault_config)
    if VAULT_CONFIG is None or VAULT_CONFIG != normalized:
        VAULT_CONFIG = normalized

    return VAULT_CONFIG


def get_vault_config(vault_config: Union[VaultConfig, dict, Any]) -> VaultConfig:
    """
    Get global Vault configuration instance.

    Returns:
        VaultConfig instance
    """
    normalized = _normalize_vault_config(vault_config)

    if VAULT_CONFIG is None or VAULT_CONFIG != normalized:
        LOG.info("Vault configuration initialized.")
        init_vault_config(normalized)
    return VAULT_CONFIG
