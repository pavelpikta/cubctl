"""CUB REST API Python client and CLI."""

__version__ = "1.0.0"

from .auth import DEVICE_CODE_URL, DeviceCredentials, login_device, normalize_device_code
from .client import CubClient, DEFAULT_BASE_URL
from .exceptions import CubApiError
from .hash_utils import movie_timecode_hash, timecode_hash, tv_timecode_hash
from .migration import (
    MigrationClients,
    MigrationResult,
    backup_profile,
    clients_for_migration,
    export_profile,
    migrate_profile,
    resolve_migration_tokens,
    restore_profile,
)

__all__ = [
    "CubClient",
    "CubApiError",
    "DEFAULT_BASE_URL",
    "DEVICE_CODE_URL",
    "DeviceCredentials",
    "login_device",
    "normalize_device_code",
    "MigrationClients",
    "MigrationResult",
    "backup_profile",
    "clients_for_migration",
    "export_profile",
    "migrate_profile",
    "resolve_migration_tokens",
    "restore_profile",
    "movie_timecode_hash",
    "timecode_hash",
    "tv_timecode_hash",
]
