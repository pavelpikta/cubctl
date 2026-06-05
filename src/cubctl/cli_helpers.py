"""Shared helpers for the CUB CLI."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Callable

from .client import DEFAULT_BASE_URL, CubClient
from .config import (
    default_account_slot,
    get_account,
    load_config,
    resolve_profile_for_account,
)
from .exceptions import CubApiError

# Commands that work without a token (matches client require_token=False paths).
PUBLIC_COMMANDS = frozenset(
    {
        ("collections", "top-collectors"),
        ("collections", "view"),
        ("reactions", "add"),
        ("reactions", "get"),
        ("users", "find"),
    }
)

BOOKMARK_TYPE_CHOICES = (
    "book",
    "history",
    "like",
    "wath",
    "viewed",
    "scheduled",
    "look",
    "thrown",
    "continued",
)

ACCOUNT_HELP = (
    "Saved account slot: src (source) or target. "
    "Like AWS --profile, but fixed slots for migration workflows. Env: CUB_ACCOUNT"
)
PROFILE_HELP = (
    "CUB profile ID or saved profile name from config (see: cubctl config profile list). "
    "Overrides the default profile for the account slot. Env: CUB_PROFILE"
)


def print_json(data: Any, *, compact: bool = False) -> None:
    if compact:
        print(json.dumps(data, ensure_ascii=False))
    else:
        print(json.dumps(data, indent=2, ensure_ascii=False))


def command_requires_auth(args: argparse.Namespace) -> bool:
    """Return True if the parsed command needs credentials before calling the API."""
    key = (args.command, getattr(args, "action", None))
    if key in PUBLIC_COMMANDS:
        return False
    if args.command == "collections" and args.action in ("list", "roll"):
        return bool(getattr(args, "cid", None))
    return True


def resolve_credentials(args: argparse.Namespace) -> tuple[str | None, str | None]:
    """
    Resolve token and CUB profile ID.

    Precedence:
      1. --account src|target (+ optional --profile override)
      2. --token (+ optional --profile)
      3. CUB_TOKEN / CUB_PROFILE env vars
      4. default account slot (CUB_ACCOUNT or account_src)
    """
    account = getattr(args, "account", None) or os.environ.get("CUB_ACCOUNT")
    profile_override = getattr(args, "profile", None) or os.environ.get("CUB_PROFILE")

    if account:
        return credentials_from_saved_account(account, profile_override)

    token = getattr(args, "token", None) or os.environ.get("CUB_TOKEN")
    if token:
        return str(token), str(profile_override) if profile_override is not None else None

    default_slot = default_account_slot()
    if default_slot:
        saved = get_account(default_slot)
        profile = resolve_profile_for_account(default_slot, profile_override)
        return str(saved["token"]), profile

    return None, None


def credentials_from_saved_account(
    name: str,
    profile_override: str | int | None = None,
) -> tuple[str, str]:
    account = get_account(name)
    profile = resolve_profile_for_account(name, profile_override)
    return str(account["token"]), profile


def client_from_args(args: argparse.Namespace, *, require_auth: bool = False) -> CubClient:
    token, profile = resolve_credentials(args)
    if require_auth and not token:
        raise ValueError(
            "Authentication required: use --account src|target, --token, "
            "or run: cubctl accounts setup"
        )
    base_url = (
        getattr(args, "base_url", None)
        or os.environ.get("CUB_BASE_URL")
        or load_config().get("base_url")
        or DEFAULT_BASE_URL
    )
    timeout = getattr(args, "timeout", 30.0)
    return CubClient(token=token, profile=profile, base_url=base_url, timeout=timeout)


def client_from_credentials(
    args: argparse.Namespace,
    *,
    token: str | None,
    profile: str | int | None,
) -> CubClient:
    base_url = (
        getattr(args, "base_url", None)
        or os.environ.get("CUB_BASE_URL")
        or load_config().get("base_url")
        or DEFAULT_BASE_URL
    )
    timeout = getattr(args, "timeout", 30.0)
    return CubClient(token=token, profile=profile, base_url=base_url, timeout=timeout)


def pick_profile_by_name(profiles: list[dict[str, Any]], name: str, *, exact: bool = False) -> dict[str, Any]:
    """Find a profile by name (case-insensitive). Raises ValueError if ambiguous or missing."""
    needle = name.strip().lower()
    if not needle:
        raise ValueError("--name is required")

    if exact:
        matches = [p for p in profiles if str(p.get("name", "")).lower() == needle]
    else:
        exact_matches = [p for p in profiles if str(p.get("name", "")).lower() == needle]
        if exact_matches:
            matches = exact_matches
        else:
            matches = [p for p in profiles if needle in str(p.get("name", "")).lower()]

    if not matches:
        available = ", ".join(str(p.get("name", "?")) for p in profiles)
        raise ValueError(f"No profile matching {name!r}. Available: {available}")
    if len(matches) > 1:
        names = ", ".join(f"{p.get('name')} ({p.get('id')})" for p in matches)
        raise ValueError(f"Ambiguous profile name {name!r}. Matches: {names}. Use --exact or a more specific name.")
    return matches[0]


class ProgressReporter:
    """Print migration progress to stderr."""

    def __init__(self, *, enabled: bool = False, quiet: bool = False) -> None:
        self.enabled = enabled and not quiet
        self.quiet = quiet
        self._step = 0

    def message(self, text: str) -> None:
        if self.quiet:
            return
        print(text, file=sys.stderr)

    def tick(self, label: str) -> None:
        if not self.enabled:
            return
        self._step += 1
        print(f"[{self._step}] {label}", file=sys.stderr)


ProgressCallback = Callable[[str], None]


def make_progress_callback(reporter: ProgressReporter) -> ProgressCallback:
    return reporter.tick


def run_with_errors(action: Callable[[], int]) -> int:
    """Run a CLI action with unified error handling."""
    try:
        return action()
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except CubApiError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        if exc.payload:
            print_json(exc.payload)
        return 1
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def save_hint() -> None:
    print("Tip: use cubctl accounts setup for src + target slots", file=sys.stderr)
