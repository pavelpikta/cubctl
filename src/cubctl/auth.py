"""Device-based authentication via POST device/add."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .client import CubClient
from .config import save_account, update_config
from .exceptions import CubApiError

DEVICE_CODE_URL = "https://cub.rip/add"
DEVICE_CODE_PATTERN = re.compile(r"^\d{6}$")


@dataclass
class DeviceCredentials:
    """Account data returned by device/add on success."""

    token: str
    profile_id: str
    email: str | None = None
    raw: dict[str, Any] | None = None


def normalize_device_code(code: str | int) -> int:
    """Validate and normalize a 6-digit device code (same rules as Lampa)."""
    text = str(code).strip()
    if not DEVICE_CODE_PATTERN.match(text):
        raise ValueError("Device code must be exactly 6 digits")
    return int(text)


def parse_account_response(result: dict[str, Any]) -> DeviceCredentials:
    """Extract credentials from a successful device/add response."""
    token = result.get("token")
    if not token:
        raise CubApiError("device/add succeeded but response has no token", payload=result)

    profile = result.get("profile") or {}
    profile_id = profile.get("id") if isinstance(profile, dict) else profile
    if profile_id is None:
        raise CubApiError("device/add succeeded but response has no profile", payload=result)

    return DeviceCredentials(
        token=str(token),
        profile_id=str(profile_id),
        email=result.get("email"),
        raw=result,
    )


def apply_account(client: CubClient, result: dict[str, Any]) -> DeviceCredentials:
    """Apply device/add response to a client instance."""
    credentials = parse_account_response(result)
    client.set_credentials(credentials.token, credentials.profile_id)
    return credentials


def login_device(
    client: CubClient,
    code: str | int,
    *,
    save: bool = False,
) -> DeviceCredentials:
    """
    Exchange a 6-digit code from https://cub.rip/add for API credentials.

    Same flow as Lampa ``Device.add()`` → ``POST device/add``.
    """
    normalized = normalize_device_code(code)
    result = client.device_add(normalized)
    credentials = apply_account(client, result)
    if save:
        save_account(
            "src",
            token=credentials.token,
            profile=credentials.profile_id,
            email=credentials.email,
        )
        update_config(base_url=client.base_url, default_account="src")
    return credentials
