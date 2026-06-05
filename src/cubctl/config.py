"""Load and save CUB API credentials."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

CONFIG_DIR = Path(os.environ.get("CUB_CONFIG_DIR", Path.home() / ".cub"))
CONFIG_FILE = CONFIG_DIR / "config.json"
DEFAULT_ENV_FILE = Path(__file__).resolve().parents[2] / "accounts.env"

ACCOUNT_SRC = "account_src"
ACCOUNT_TARGET = "account_target"
ACCOUNT_SLOTS = (ACCOUNT_SRC, ACCOUNT_TARGET)
ACCOUNT_CHOICES = ("src", "target")

ACCOUNT_ALIASES = {
    "src": ACCOUNT_SRC,
    "target": ACCOUNT_TARGET,
    "account_src": ACCOUNT_SRC,
    "account_target": ACCOUNT_TARGET,
}


def load_config() -> dict[str, Any]:
    if not CONFIG_FILE.exists():
        return {}
    with CONFIG_FILE.open(encoding="utf-8") as fh:
        return json.load(fh)


def save_config(config: dict[str, Any]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with CONFIG_FILE.open("w", encoding="utf-8") as fh:
        json.dump(config, fh, indent=2, ensure_ascii=False)


def update_config(**kwargs: Any) -> dict[str, Any]:
    config = load_config()
    config.update({k: v for k, v in kwargs.items() if v is not None})
    save_config(config)
    return config


def normalize_account_key(name: str) -> str:
    key = ACCOUNT_ALIASES.get(name.strip().lower())
    if not key:
        raise ValueError(f"Unknown account {name!r}. Use: src, target")
    return key


def account_slot_label(config_key: str) -> str:
    if config_key == ACCOUNT_SRC:
        return "src"
    if config_key == ACCOUNT_TARGET:
        return "target"
    return config_key.removeprefix("account_")


def get_account(name: str) -> dict[str, Any]:
    """Return {token, profile, email?, profiles?} for account slot src or target."""
    config = load_config()
    key = normalize_account_key(name)
    account = config.get(key)
    if not account or not account.get("token"):
        raise ValueError(
            f"{account_slot_label(key)} not configured. Run: cubctl accounts setup"
        )
    return account


def save_account(name: str, *, token: str, profile: str, email: str | None = None) -> None:
    key = normalize_account_key(name)
    config = load_config()
    existing = config.get(key) or {}
    profiles = dict(existing.get("profiles") or {})
    profile_id = str(profile)
    config[key] = {
        "token": token,
        "profile": profile_id,
        "profiles": profiles,
        **({"email": email} if email else {}),
    }
    save_config(config)


def get_saved_profiles(name: str) -> dict[str, str]:
    account = get_account(name)
    return {str(k): str(v) for k, v in (account.get("profiles") or {}).items()}


def resolve_profile_id(name: str, profile_ref: str | int) -> str:
    ref = str(profile_ref).strip()
    if not ref:
        raise ValueError("profile reference is empty")
    if ref.isdigit():
        return ref

    account = get_account(name)
    profiles = account.get("profiles") or {}
    needle = ref.lower()
    matches = [(label, pid) for label, pid in profiles.items() if str(label).lower() == needle]
    if len(matches) == 1:
        return str(matches[0][1])
    if len(matches) > 1:
        labels = ", ".join(label for label, _ in matches)
        raise ValueError(f"Ambiguous profile name {ref!r}. Matches: {labels}")

    available = ", ".join(str(label) for label in profiles) or "(none — run: cubctl config profile sync)"
    raise ValueError(
        f"Unknown profile {ref!r} for account {account_slot_label(normalize_account_key(name))!r}. "
        f"Saved names: {available}"
    )


def resolve_profile_for_account(name: str, profile_ref: str | int | None) -> str:
    account = get_account(name)
    if profile_ref is None:
        return str(account["profile"])
    return resolve_profile_id(name, profile_ref)


def save_profile_alias(name: str, *, label: str, profile_id: str | int) -> None:
    key = normalize_account_key(name)
    config = load_config()
    account = config.get(key) or {}
    if not account.get("token"):
        raise ValueError(f"{account_slot_label(key)} not configured. Run: cubctl accounts setup")
    profiles = dict(account.get("profiles") or {})
    profiles[label.strip()] = str(profile_id)
    account["profiles"] = profiles
    config[key] = account
    save_config(config)


def set_default_profile(name: str, *, profile_ref: str | int) -> str:
    profile_id = resolve_profile_id(name, profile_ref)
    key = normalize_account_key(name)
    config = load_config()
    account = config.get(key) or {}
    if not account.get("token"):
        raise ValueError(f"{account_slot_label(key)} not configured. Run: cubctl accounts setup")
    account["profile"] = profile_id
    config[key] = account
    save_config(config)
    return profile_id


def remove_profile_alias(name: str, *, label: str) -> bool:
    key = normalize_account_key(name)
    config = load_config()
    account = config.get(key) or {}
    profiles = dict(account.get("profiles") or {})
    removed = profiles.pop(label, None) is not None
    if not removed:
        needle = label.strip().lower()
        for key_name in list(profiles):
            if key_name.lower() == needle:
                profiles.pop(key_name)
                removed = True
                break
    account["profiles"] = profiles
    config[key] = account
    save_config(config)
    return removed


def show_config() -> dict[str, Any]:
    config = load_config()
    return {
        "config_file": str(CONFIG_FILE),
        "default_account": config.get("default_account") or default_account_slot(),
        "base_url": config.get("base_url"),
        "accounts": list_accounts(),
    }


def list_accounts() -> dict[str, dict[str, Any]]:
    config = load_config()
    result: dict[str, dict[str, Any]] = {}
    for key in ACCOUNT_SLOTS:
        if key in config and config[key].get("token"):
            entry = dict(config[key])
            entry.pop("token", None)
            entry["token_set"] = True
            entry["profiles"] = dict(entry.get("profiles") or {})
            result[account_slot_label(key)] = entry
    return result


def default_account_slot() -> str | None:
    explicit = os.environ.get("CUB_ACCOUNT", "").strip().lower()
    if explicit:
        return account_slot_label(normalize_account_key(explicit))
    config = load_config()
    configured = config.get("default_account")
    if configured:
        return str(configured)
    if config.get(ACCOUNT_SRC, {}).get("token"):
        return "src"
    return None


def default_token() -> str | None:
    slot = default_account_slot()
    if not slot:
        return None
    try:
        return str(get_account(slot)["token"])
    except ValueError:
        return None


def account_client(name: str, *, base_url: str | None = None) -> tuple[str, str]:
    account = get_account(name)
    return str(account["token"]), str(account["profile"])


def load_env_file(path: Path | str | None = None) -> Path:
    env_path = Path(path) if path else DEFAULT_ENV_FILE
    if not env_path.exists():
        raise FileNotFoundError(env_path)
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep:
            continue
        os.environ[key.strip()] = value.strip().strip('"').strip("'")
    return env_path


def device_codes_from_env() -> tuple[str, str]:
    src = os.environ.get("CUB_CODE_SRC", "").strip()
    target = os.environ.get("CUB_CODE_TARGET", "").strip()
    if not src or not target:
        raise ValueError(
            "Set CUB_CODE_SRC and CUB_CODE_TARGET in accounts.env "
            f"(copy accounts.env.example → {DEFAULT_ENV_FILE.name})"
        )
    return src, target
