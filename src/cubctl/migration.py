"""Migrate CUB data between profiles and accounts."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Literal

from .client import CubClient
from .exceptions import CubApiError

BOOKMARK_TYPES_LEGACY = ("book", "history", "like", "wath")
BOOKMARK_TYPES = (
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
MIGRATION_VERSION = 2
MergeMode = Literal["skip", "overwrite"]
ProgressCallback = Callable[[str], None]


@dataclass
class SectionStats:
    exported: int = 0
    imported: int = 0
    skipped: int = 0
    failed: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "exported": self.exported,
            "imported": self.imported,
            "skipped": self.skipped,
            "failed": self.failed,
        }


@dataclass
class MigrationResult:
    source_profile: str
    target_profile: str
    dry_run: bool
    cross_account: bool = False
    bookmarks: dict[str, SectionStats] = field(default_factory=dict)
    timeline: SectionStats = field(default_factory=SectionStats)
    notifications: SectionStats = field(default_factory=SectionStats)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_profile": self.source_profile,
            "target_profile": self.target_profile,
            "dry_run": self.dry_run,
            "cross_account": self.cross_account,
            "bookmarks": {k: v.to_dict() for k, v in self.bookmarks.items()},
            "timeline": self.timeline.to_dict(),
            "notifications": self.notifications.to_dict(),
            "errors": self.errors,
        }


@dataclass
class MigrationClients:
    """Source and target API clients for a migration."""

    source: CubClient
    target: CubClient
    cross_account: bool


def resolve_migration_tokens(
    *,
    from_token: str | None = None,
    to_token: str | None = None,
    default_token: str | None = None,
    cross_account: bool = False,
) -> tuple[str, str, bool]:
    """
    Resolve source/target tokens for migration.

    Same account (one token):
      - ``from_token`` or ``default_token`` used for both sides

    Cross account (two tokens):
      - ``from_token`` reads source profile
      - ``to_token`` writes target profile
      - When ``cross_account=True``, both must be provided explicitly
    """
    source = from_token or default_token
    if not source:
        raise ValueError(
            "Source token required: use --from-token, --token, CUB_FROM_TOKEN, or CUB_TOKEN"
        )

    if cross_account:
        if not to_token:
            raise ValueError(
                "Cross-account migration requires two tokens: --from-token and --to-token "
                "(or CUB_FROM_TOKEN and CUB_TO_TOKEN)"
            )
        target = to_token
        return source, target, True

    target = to_token or source
    return source, target, source != target


def clients_for_migration(
    *,
    from_token: str,
    from_profile: int | str,
    to_token: str,
    to_profile: int | str,
    base_url: str,
    timeout: float = 30.0,
) -> MigrationClients:
    """Build source/target clients. Use two different tokens for cross-account migration."""
    cross_account = from_token != to_token
    return MigrationClients(
        source=CubClient(
            token=from_token,
            profile=from_profile,
            base_url=base_url,
            timeout=timeout,
        ),
        target=CubClient(
            token=to_token,
            profile=to_profile,
            base_url=base_url,
            timeout=timeout,
        ),
        cross_account=cross_account,
    )


def _bookmark_key(entry: dict[str, Any]) -> tuple[str, str]:
    return (str(entry.get("type", "")), str(entry.get("card_id", "")))


def _decode_card_data(entry: dict[str, Any]) -> dict[str, Any] | str:
    raw = entry.get("data")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        return json.loads(raw)
    return {}


def fetch_all_bookmarks(client: CubClient) -> dict[str, list[dict[str, Any]]]:
    """Fetch all bookmarks (full=1) grouped by internal type (viewed, scheduled, …)."""
    response = client.bookmarks_all(full=1)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for entry in response.get("bookmarks") or []:
        bookmark_type = str(entry.get("type") or "unknown")
        grouped.setdefault(bookmark_type, []).append(entry)
    return grouped


def normalize_bookmarks_export(bookmarks: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Normalize bookmark export payloads into a type → entries map."""
    normalized: dict[str, list[dict[str, Any]]] = {}
    for key, entries in (bookmarks or {}).items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            bookmark_type = str(entry.get("type") or key)
            normalized.setdefault(bookmark_type, []).append(entry)
    return normalized


def export_profile(
    client: CubClient,
    profile_id: int | str,
    *,
    include_notifications: bool = False,
    include_account_meta: bool = True,
) -> dict[str, Any]:
    """Export bookmarks and timeline for a profile to a JSON-serializable dict."""
    client.profile = str(profile_id)
    payload: dict[str, Any] = {
        "version": MIGRATION_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "source_profile": str(profile_id),
        "bookmarks": fetch_all_bookmarks(client),
        "timeline": client.timeline_dump(),
    }

    if include_notifications:
        response = client.notifications_all()
        payload["notifications"] = response.get("notifications") or []

    if include_account_meta:
        payload["account"] = _account_metadata(client, profile_id)

    payload["summary"] = summarize_export(payload)
    return payload


def _account_metadata(client: CubClient, profile_id: int | str) -> dict[str, Any]:
    meta: dict[str, Any] = {"profile_id": str(profile_id)}
    try:
        user = client.users_get().get("user") or {}
        meta["email"] = user.get("email")
        meta["user_id"] = user.get("id")
    except CubApiError:
        pass
    try:
        for profile in client.profiles_all().get("profiles") or []:
            if str(profile.get("id")) == str(profile_id):
                meta["profile_name"] = profile.get("name")
                break
    except CubApiError:
        pass
    return meta


def summarize_export(payload: dict[str, Any]) -> dict[str, Any]:
    bookmarks = normalize_bookmarks_export(payload.get("bookmarks") or {})
    timeline = payload.get("timeline") or {}
    return {
        "bookmarks": {key: len(entries) for key, entries in sorted(bookmarks.items())},
        "timeline": len(timeline.get("timelines") or {}),
        "notifications": len(payload.get("notifications") or []),
    }


def default_backup_path(profile_id: int | str, *, profile_name: str | None = None) -> str:
    """Build a default backup filename."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    slug = profile_name or f"profile-{profile_id}"
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in slug).strip("-") or str(profile_id)
    return f"cub-backup-{safe}-{stamp}.json"


def backup_profile(
    client: CubClient,
    profile_id: int | str,
    path: str,
    *,
    include_notifications: bool = True,
) -> dict[str, Any]:
    """Create a JSON backup file for a profile."""
    payload = export_profile(
        client,
        profile_id,
        include_notifications=include_notifications,
    )
    save_export(path, payload)
    return payload


def restore_profile(
    client: CubClient,
    profile_id: int | str,
    path: str,
    *,
    dry_run: bool = False,
    merge: MergeMode = "skip",
    include_bookmarks: bool = True,
    include_timeline: bool = True,
    include_notifications: bool = True,
) -> MigrationResult:
    """Restore a profile from a JSON backup file."""
    payload = load_export(path)
    return import_export_file(
        client,
        profile_id,
        payload,
        dry_run=dry_run,
        merge=merge,
        include_bookmarks=include_bookmarks,
        include_timeline=include_timeline,
        include_notifications=include_notifications,
    )


def save_export(path: str, payload: dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)


def load_export(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        payload = json.load(fh)
    if payload.get("version") not in (1, MIGRATION_VERSION):
        raise ValueError(f"Unsupported export version: {payload.get('version')}")
    return payload


def _existing_bookmark_keys(client: CubClient) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    response = client.bookmarks_all(full=1)
    for entry in response.get("bookmarks") or []:
        keys.add(_bookmark_key(entry))
    return keys


def import_bookmarks(
    client: CubClient,
    profile_id: int | str,
    bookmarks_by_type: dict[str, Iterable[dict[str, Any]]],
    *,
    dry_run: bool = False,
    merge: MergeMode = "skip",
    result: MigrationResult | None = None,
    on_progress: ProgressCallback | None = None,
    delay_seconds: float = 0.0,
) -> dict[str, SectionStats]:
    """Import bookmarks into a profile (all internal types)."""
    client.profile = str(profile_id)
    normalized = normalize_bookmarks_export(dict(bookmarks_by_type))
    stats = {bookmark_type: SectionStats() for bookmark_type in normalized}
    existing = _existing_bookmark_keys(client) if merge == "skip" else set()

    for bookmark_type, entries in normalized.items():
        section = stats[bookmark_type]
        for entry in entries:
            section.exported += 1
            key = _bookmark_key(entry)
            if merge == "skip" and key in existing:
                section.skipped += 1
                continue

            card_data = _decode_card_data(entry)
            api_type = str(entry.get("type") or bookmark_type)
            if dry_run:
                section.imported += 1
                existing.add(key)
                continue

            try:
                client.bookmarks_add(card_data, api_type)
                section.imported += 1
                existing.add(key)
                if on_progress:
                    on_progress(f"bookmark {api_type}/{key[1]}")
                if delay_seconds:
                    time.sleep(delay_seconds)
            except CubApiError as exc:
                section.failed += 1
                if result is not None:
                    result.errors.append(f"bookmark {api_type}/{key[1]}: {exc}")

    return stats


def import_timeline(
    client: CubClient,
    profile_id: int | str,
    timeline_dump: dict[str, Any],
    *,
    dry_run: bool = False,
    merge: MergeMode = "skip",
    result: MigrationResult | None = None,
    on_progress: ProgressCallback | None = None,
    delay_seconds: float = 0.0,
) -> SectionStats:
    """Import playback timecodes into a profile (requires Premium)."""
    client.profile = str(profile_id)
    stats = SectionStats()
    timelines = timeline_dump.get("timelines") or {}
    stats.exported = len(timelines)

    existing: set[str] = set()
    if merge == "skip":
        current = client.timeline_dump()
        existing = set((current.get("timelines") or {}).keys())

    target_profile = int(profile_id)
    for hash_key, entry in timelines.items():
        if merge == "skip" and hash_key in existing:
            stats.skipped += 1
            continue

        timecode_hash = str(entry.get("hash") or hash_key)
        time_sec = int(float(entry.get("time") or 0))
        duration = int(float(entry.get("duration") or 0))
        percent = int(float(entry.get("percent") or 0))

        if dry_run:
            stats.imported += 1
            continue

        try:
            client.timeline_update(
                hash=timecode_hash,
                time=time_sec,
                duration=duration,
                percent=percent,
                profile=target_profile,
            )
            stats.imported += 1
            if on_progress:
                on_progress(f"timeline {timecode_hash}")
            if delay_seconds:
                time.sleep(delay_seconds)
        except CubApiError as exc:
            stats.failed += 1
            if result is not None:
                result.errors.append(f"timeline {timecode_hash}: {exc}")

    return stats


def import_notifications(
    client: CubClient,
    notifications: Iterable[dict[str, Any]],
    *,
    dry_run: bool = False,
    result: MigrationResult | None = None,
    on_progress: ProgressCallback | None = None,
    delay_seconds: float = 0.0,
) -> SectionStats:
    """Import translation notification subscriptions (account-level)."""
    stats = SectionStats()
    existing_ids = {
        str(item.get("id"))
        for item in client.notifications_all().get("notifications") or []
    }

    for entry in notifications:
        stats.exported += 1
        voice = entry.get("voice") or entry.get("voice_name")
        card_raw = entry.get("card") or entry.get("data")
        if not voice or not card_raw:
            stats.skipped += 1
            continue

        card_data = json.loads(card_raw) if isinstance(card_raw, str) else card_raw
        season = int(entry.get("season") or 1)
        episode = int(entry.get("episode") or 1)
        entry_id = str(entry.get("id", ""))

        if entry_id and entry_id in existing_ids:
            stats.skipped += 1
            continue

        if dry_run:
            stats.imported += 1
            continue

        try:
            client.notifications_add(card_data, voice, season=season, episode=episode)
            stats.imported += 1
            if on_progress:
                on_progress(f"notification {voice}")
            if delay_seconds:
                time.sleep(delay_seconds)
        except CubApiError as exc:
            stats.failed += 1
            if result is not None:
                result.errors.append(f"notification {voice}: {exc}")

    return stats


def migrate_profile(
    source: CubClient,
    source_profile: int | str,
    target: CubClient,
    target_profile: int | str,
    *,
    include_bookmarks: bool = True,
    include_timeline: bool = True,
    include_notifications: bool = False,
    dry_run: bool = False,
    merge: MergeMode = "skip",
    delay_seconds: float = 0.0,
    cross_account: bool | None = None,
    on_progress: ProgressCallback | None = None,
) -> MigrationResult:
    """
    Copy profile data from source to target.

    Supports:
    - same account, different profiles (one token, different profile ids)
    - different accounts (two tokens and different profile ids)
    """
    if cross_account is None:
        cross_account = bool(source.token and target.token and source.token != target.token)

    result = MigrationResult(
        source_profile=str(source_profile),
        target_profile=str(target_profile),
        dry_run=dry_run,
        cross_account=cross_account,
    )

    payload = export_profile(
        source,
        source_profile,
        include_notifications=include_notifications,
    )

    if include_bookmarks:
        result.bookmarks = import_bookmarks(
            target,
            target_profile,
            payload["bookmarks"],
            dry_run=dry_run,
            merge=merge,
            result=result,
            on_progress=on_progress,
            delay_seconds=delay_seconds,
        )

    if include_timeline:
        result.timeline = import_timeline(
            target,
            target_profile,
            payload["timeline"],
            dry_run=dry_run,
            merge=merge,
            result=result,
            on_progress=on_progress,
            delay_seconds=delay_seconds,
        )

    if include_notifications and payload.get("notifications") is not None:
        result.notifications = import_notifications(
            target,
            payload["notifications"],
            dry_run=dry_run,
            result=result,
            on_progress=on_progress,
            delay_seconds=delay_seconds,
        )

    return result


def import_export_file(
    client: CubClient,
    target_profile: int | str,
    payload: dict[str, Any],
    *,
    dry_run: bool = False,
    merge: MergeMode = "skip",
    include_bookmarks: bool = True,
    include_timeline: bool = True,
    include_notifications: bool = True,
    on_progress: ProgressCallback | None = None,
    delay_seconds: float = 0.0,
) -> MigrationResult:
    """Import a previously exported JSON snapshot into a profile."""
    result = MigrationResult(
        source_profile=str(payload.get("source_profile", "?")),
        target_profile=str(target_profile),
        dry_run=dry_run,
    )

    if include_bookmarks:
        result.bookmarks = import_bookmarks(
            client,
            target_profile,
            payload.get("bookmarks") or {},
            dry_run=dry_run,
            merge=merge,
            result=result,
            on_progress=on_progress,
            delay_seconds=delay_seconds,
        )

    if include_timeline:
        result.timeline = import_timeline(
            client,
            target_profile,
            payload.get("timeline") or {},
            dry_run=dry_run,
            merge=merge,
            result=result,
            on_progress=on_progress,
            delay_seconds=delay_seconds,
        )

    if include_notifications and payload.get("notifications") is not None:
        result.notifications = import_notifications(
            client,
            payload["notifications"],
            dry_run=dry_run,
            result=result,
            on_progress=on_progress,
            delay_seconds=delay_seconds,
        )

    return result
