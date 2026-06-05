#!/usr/bin/env python3
"""Command-line interface for the CUB REST API."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Callable

from .client import DEFAULT_BASE_URL, CubClient
from .config import (
    ACCOUNT_CHOICES,
    CONFIG_FILE,
    DEFAULT_ENV_FILE,
    default_account_slot,
    default_token as get_default_token,
    device_codes_from_env,
    get_account,
    get_saved_profiles,
    list_accounts,
    load_config,
    load_env_file,
    remove_profile_alias,
    save_account,
    save_profile_alias,
    set_default_profile,
    show_config,
    update_config,
)
from .auth import DEVICE_CODE_URL, login_device
from .exceptions import CubApiError
from .hash_utils import movie_timecode_hash, tv_timecode_hash
from .cli_helpers import (
    ACCOUNT_HELP,
    BOOKMARK_TYPE_CHOICES,
    PROFILE_HELP,
    ProgressReporter,
    client_from_args,
    client_from_credentials,
    command_requires_auth,
    credentials_from_saved_account,
    make_progress_callback,
    pick_profile_by_name,
    print_json,
    run_with_errors,
    save_hint,
)


def _load_json_arg(value: str) -> Any:
    path = value.lstrip("@")
    if value.startswith("@") or (not value.strip().startswith("{") and not value.strip().startswith("[")):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    return json.loads(value)


def _run(
    action: Callable[[CubClient], Any],
    args: argparse.Namespace,
    *,
    require_auth: bool = False,
    quiet: bool = False,
) -> int:
    client = client_from_args(args, require_auth=require_auth)
    result = action(client)
    print_json(result, compact=quiet)
    return 0


def _build_common_parent() -> argparse.ArgumentParser:
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument("--base-url", help=f"API base URL (default: {DEFAULT_BASE_URL})")
    parent.add_argument("--timeout", type=float, default=30.0, help="Request timeout seconds")
    return parent


def _add_auth_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--token", help="API token (overrides --account)")
    parser.add_argument("--profile", help=PROFILE_HELP)
    parser.add_argument(
        "--account",
        choices=list(ACCOUNT_CHOICES),
        help=ACCOUNT_HELP,
    )


def _build_auth_parent() -> argparse.ArgumentParser:
    parent = _build_common_parent()
    _add_auth_arguments(parent)
    return parent


def _run_device_login(args: argparse.Namespace) -> int:
    code = args.code
    if not code:
        print(f"Open {DEVICE_CODE_URL} while logged in to get a 6-digit code.", file=sys.stderr)
        try:
            code = input("Enter device code: ").strip()
        except (EOFError, KeyboardInterrupt):
            print(file=sys.stderr)
            return 1

    client = client_from_args(args)
    credentials = login_device(client, code, save=args.save)
    print_json(
        {
            "token": credentials.token,
            "profile": credentials.profile_id,
            "email": credentials.email,
        }
    )
    if args.save:
        print(f"Saved src account slot to {CONFIG_FILE}", file=sys.stderr)
        save_hint()
    return 0


def _migration_include(args: argparse.Namespace) -> tuple[bool, bool, bool]:
    parts = {part.strip() for part in (args.include or "bookmarks,timeline").split(",") if part.strip()}
    return (
        "bookmarks" in parts,
        "timeline" in parts,
        "notifications" in parts,
    )


def _migration_progress(args: argparse.Namespace):
    reporter = ProgressReporter(enabled=getattr(args, "progress", False), quiet=getattr(args, "quiet", False))
    return reporter, make_progress_callback(reporter)


def _run_accounts(args: argparse.Namespace) -> int:
    if args.action == "setup":
        code_src = args.code_src
        code_target = args.code_target
        if not code_src or not code_target:
            try:
                env_path = load_env_file(args.env_file)
                code_src, code_target = device_codes_from_env()
                print(f"Using codes from {env_path}", file=sys.stderr)
            except (FileNotFoundError, ValueError) as exc:
                print(f"Error: {exc}", file=sys.stderr)
                print(f"Create {DEFAULT_ENV_FILE.name} from accounts.env.example", file=sys.stderr)
                print("Or: cubctl accounts setup CODE_SRC CODE_TARGET", file=sys.stderr)
                return 1
        client = CubClient(base_url=args.base_url or DEFAULT_BASE_URL, timeout=args.timeout)
        src = login_device(client, code_src)
        save_account("src", token=src.token, profile=src.profile_id, email=src.email)
        target = login_device(client, code_target)
        save_account("target", token=target.token, profile=target.profile_id, email=target.email)
        update_config(base_url=client.base_url, default_account="src")
        print_json(
            {
                "saved_to": str(CONFIG_FILE),
                "src": {
                    "email": src.email,
                    "profile": src.profile_id,
                },
                "target": {
                    "email": target.email,
                    "profile": target.profile_id,
                },
            }
        )
        print(f"Saved src + target accounts to {CONFIG_FILE}", file=sys.stderr)
        return 0

    if args.action == "show":
        print_json(list_accounts())
        return 0

    print(f"Unknown accounts action: {args.action}", file=sys.stderr)
    return 1


def _run_config(args: argparse.Namespace) -> int:
    if args.action == "show":
        print_json(show_config())
        return 0

    if args.action == "path":
        print(CONFIG_FILE)
        return 0

    if args.action == "set":
        if args.setting == "default-account":
            update_config(default_account=args.value)
            print_json({"default_account": args.value, "config_file": str(CONFIG_FILE)})
            return 0
        raise ValueError(f"Unknown setting: {args.setting}")

    if args.action == "profile":
        account = args.account or default_account_slot()
        if not account:
            raise ValueError("--account src|target is required (or set: cubctl config set default-account src)")

        if args.profile_action == "list":
            entry = get_account(account)
            print_json(
                {
                    "account": account,
                    "default_profile": entry["profile"],
                    "profiles": get_saved_profiles(account),
                }
            )
            return 0

        if args.profile_action == "set":
            save_profile_alias(account, label=args.name, profile_id=args.id)
            print_json({"account": account, "name": args.name, "id": str(args.id), "config_file": str(CONFIG_FILE)})
            return 0

        if args.profile_action == "default":
            profile_id = set_default_profile(account, profile_ref=args.name)
            print_json(
                {
                    "account": account,
                    "default_profile": profile_id,
                    "name": args.name,
                    "config_file": str(CONFIG_FILE),
                }
            )
            return 0

        if args.profile_action == "remove":
            if not remove_profile_alias(account, label=args.name):
                raise ValueError(f"Profile {args.name!r} not found in config for account {account!r}")
            print_json({"account": account, "removed": args.name, "config_file": str(CONFIG_FILE)})
            return 0

        if args.profile_action == "sync":
            token, profile = credentials_from_saved_account(account, None)
            client = client_from_credentials(args, token=token, profile=profile)
            profiles = client.profiles_all().get("profiles") or []
            saved: dict[str, str] = {}
            for entry in profiles:
                name = str(entry.get("name", "")).strip()
                profile_id = entry.get("id")
                if not name or profile_id is None:
                    continue
                save_profile_alias(account, label=name, profile_id=profile_id)
                saved[name] = str(profile_id)
            print_json({"account": account, "synced": saved, "config_file": str(CONFIG_FILE)})
            return 0

        raise ValueError(f"Unknown profile action: {args.profile_action}")

    raise ValueError(f"Unknown config action: {args.action}")


def _resolve_migration_endpoints(args: argparse.Namespace) -> tuple[str, str, str, str, bool]:
    """Return from_token, from_profile, to_token, to_profile, cross_account."""
    from .migration import resolve_migration_tokens

    from_account = getattr(args, "from_account", None)
    to_account = getattr(args, "to_account", None)

    if from_account and to_account:
        if not args.from_profile:
            raise ValueError(
                "--from-profile is required (saved account default is the main profile, not named profiles)"
            )
        if not args.to_profile:
            raise ValueError("--to-profile is required")
        from_token, from_profile = credentials_from_saved_account(from_account, args.from_profile)
        to_token, to_profile = credentials_from_saved_account(to_account, args.to_profile)
        return from_token, from_profile, to_token, to_profile, from_token != to_token

    config = load_config()
    from_token, to_token, cross_account = resolve_migration_tokens(
        from_token=args.from_token or os.environ.get("CUB_FROM_TOKEN"),
        to_token=args.to_token or os.environ.get("CUB_TO_TOKEN"),
        default_token=args.token or os.environ.get("CUB_TOKEN") or get_default_token(),
        cross_account=getattr(args, "cross_account", False),
    )
    if not args.from_profile or not args.to_profile:
        raise ValueError("--from-profile and --to-profile are required")
    return from_token, str(args.from_profile), to_token, str(args.to_profile), cross_account


def _run_migration(args: argparse.Namespace) -> int:
    from .migration import (
        clients_for_migration,
        export_profile,
        import_export_file,
        load_export,
        migrate_profile,
        resolve_migration_tokens,
        save_export,
    )

    include_bookmarks, include_timeline, include_notifications = _migration_include(args)
    merge = args.merge
    config = load_config()
    base_url = args.base_url or os.environ.get("CUB_BASE_URL") or config.get("base_url") or DEFAULT_BASE_URL
    reporter, on_progress = _migration_progress(args)
    delay = getattr(args, "delay", 0.0) or 0.0
    quiet = getattr(args, "quiet", False)

    if args.action == "export":
        from_account = getattr(args, "from_account", None) or getattr(args, "account", None)
        if from_account:
            if not args.from_profile:
                raise ValueError(
                    "--from-profile is required (saved account default is the main profile, not named profiles)"
                )
            from_token, from_profile = credentials_from_saved_account(from_account, args.from_profile)
        else:
            from_token, _, _ = resolve_migration_tokens(
                from_token=args.from_token or os.environ.get("CUB_FROM_TOKEN"),
                to_token=None,
                default_token=args.token or os.environ.get("CUB_TOKEN") or get_default_token(),
                cross_account=False,
            )
            if not args.from_profile:
                raise ValueError("--from-profile is required")
            from_profile = str(args.from_profile)
        client = client_from_credentials(args, token=from_token, profile=from_profile)
        reporter.message(f"Exporting profile {from_profile}…")
        payload = export_profile(
            client,
            from_profile,
            include_notifications=include_notifications,
        )
        if args.output:
            save_export(args.output, payload)
            reporter.message(f"Exported to {args.output}")
        print_json(payload.get("summary") if quiet else payload, compact=quiet)
        return 0

    if args.action == "import":
        to_account = getattr(args, "to_account", None) or getattr(args, "account", None)
        if to_account:
            if not args.to_profile:
                raise ValueError("--to-profile is required")
            to_token, to_profile = credentials_from_saved_account(to_account, args.to_profile)
        else:
            _, to_token, _ = resolve_migration_tokens(
                from_token=None,
                to_token=args.to_token or os.environ.get("CUB_TO_TOKEN"),
                default_token=args.token or os.environ.get("CUB_TOKEN") or get_default_token(),
                cross_account=False,
            )
            if not args.to_profile:
                raise ValueError("--to-profile is required")
            to_profile = str(args.to_profile)
        if not args.input:
            raise ValueError("--input is required for import")
        client = client_from_credentials(args, token=to_token, profile=to_profile)
        payload = load_export(args.input)
        reporter.message(f"Importing into profile {to_profile}…")
        result = import_export_file(
            client,
            to_profile,
            payload,
            dry_run=args.dry_run,
            merge=merge,
            include_bookmarks=include_bookmarks,
            include_timeline=include_timeline,
            include_notifications=include_notifications,
            on_progress=on_progress,
            delay_seconds=delay,
        )
        print_json(result.to_dict(), compact=quiet)
        return 0

    if args.action == "run":
        from_token, from_profile, to_token, to_profile, cross_account = _resolve_migration_endpoints(args)
        clients = clients_for_migration(
            from_token=from_token,
            from_profile=from_profile,
            to_token=to_token,
            to_profile=to_profile,
            base_url=base_url,
            timeout=args.timeout,
        )
        reporter.message(
            "Cross-account migration" if cross_account else "Same-account migration"
        )
        reporter.message(f"{from_profile} → {to_profile}")
        result = migrate_profile(
            clients.source,
            from_profile,
            clients.target,
            to_profile,
            include_bookmarks=include_bookmarks,
            include_timeline=include_timeline,
            include_notifications=include_notifications,
            dry_run=args.dry_run,
            merge=merge,
            cross_account=clients.cross_account,
            delay_seconds=delay,
            on_progress=on_progress,
        )
        print_json(result.to_dict(), compact=quiet)
        return 0

    raise ValueError(f"Unknown migrate action: {args.action}")


def _run_backup(args: argparse.Namespace) -> int:
    from .migration import (
        default_backup_path,
        export_profile,
        restore_profile,
        save_export,
    )

    client = client_from_args(args, require_auth=True)
    profile = client.profile
    if not profile:
        raise ValueError("profile required (--profile or --account src|target)")

    include_notifications = "notifications" in (args.include or "bookmarks,timeline,notifications")

    if args.action == "create":
        payload = export_profile(
            client,
            profile,
            include_notifications=include_notifications,
        )
        output = args.output or default_backup_path(
            profile,
            profile_name=(payload.get("account") or {}).get("profile_name"),
        )
        save_export(output, payload)
        print(f"Backup saved to {output}", file=sys.stderr)
        print_json({"file": output, "summary": payload.get("summary"), "account": payload.get("account")})
        return 0

    if args.action == "restore":
        if not args.input:
            raise ValueError("--input is required for restore")
        include_bookmarks, include_timeline, include_notifications = _migration_include(args)
        result = restore_profile(
            client,
            profile,
            args.input,
            dry_run=args.dry_run,
            merge=args.merge,
            include_bookmarks=include_bookmarks,
            include_timeline=include_timeline,
            include_notifications=include_notifications,
        )
        print_json(result.to_dict())
        return 0

    raise ValueError(f"Unknown backup action: {args.action}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cubctl",
        description="CUB REST API CLI — https://cub.rip/developer/",
    )
    from . import __version__

    parser.add_argument("--version", action="version", version=f"cubctl {__version__}")
    _add_auth_arguments(parser)
    sub = parser.add_subparsers(dest="command", required=True)

    auth_parent = _build_auth_parent()
    common_parent = _build_common_parent()

    # device (POST device/add)
    device = sub.add_parser("device", help="Device authentication (POST device/add)")
    dev = device.add_subparsers(dest="action", required=True)

    dev_add = dev.add_parser(
        "add",
        parents=[common_parent],
        help="Exchange 6-digit code from cub.rip/add for token",
    )
    dev_add.add_argument(
        "code",
        nargs="?",
        help="6-digit code from https://cub.rip/add (prompted if omitted)",
    )
    dev_add.add_argument("--save", action="store_true", help="Save token/profile to src account slot in config")

    auth = sub.add_parser("auth", parents=[common_parent], help="Alias for: device add")
    auth.add_argument(
        "code",
        nargs="?",
        help="6-digit code from https://cub.rip/add (prompted if omitted)",
    )
    auth.add_argument("--save", action="store_true", help="Save token/profile to src account slot in config")

    # accounts (two device codes → account_src + account_target in config)
    accounts = sub.add_parser("accounts", help="Configure src and target account slots")
    acc = accounts.add_subparsers(dest="action", required=True)

    acc_setup = acc.add_parser(
        "setup",
        parents=[common_parent],
        help="Exchange two codes → src + target slots in ~/.cub/config.json",
    )
    acc_setup.add_argument(
        "code_src",
        nargs="?",
        help="6-digit code for src account (or set CUB_CODE_SRC in accounts.env)",
    )
    acc_setup.add_argument(
        "code_target",
        nargs="?",
        help="6-digit code for target account (or set CUB_CODE_TARGET in accounts.env)",
    )
    acc_setup.add_argument(
        "--env-file",
        help=f"Env file with CUB_CODE_SRC/CUB_CODE_TARGET (default: {DEFAULT_ENV_FILE.name})",
    )

    acc.add_parser("show", help="Show saved src / target accounts (no tokens)")

    # config (~/.cub/config.json — accounts, default slot, saved profile names)
    config_cmd = sub.add_parser("config", help="Manage ~/.cub/config.json")
    cfg = config_cmd.add_subparsers(dest="action", required=True)

    cfg.add_parser("show", help="Show config: accounts, profiles, defaults (tokens redacted)")
    cfg.add_parser("path", help="Print path to config.json")

    cfg_set = cfg.add_parser("set", help="Update a config value")
    cfg_set.add_argument("setting", choices=["default-account"], help="Setting to change")
    cfg_set.add_argument("value", choices=list(ACCOUNT_CHOICES), help="New value")

    cfg_profile = cfg.add_parser("profile", help="Saved CUB profile names (id aliases) in config")
    cfg_profile.add_argument(
        "--account",
        choices=list(ACCOUNT_CHOICES),
        help="Account slot (defaults to default_account from config)",
    )
    prof = cfg_profile.add_subparsers(dest="profile_action", required=True)

    prof.add_parser("list", help="List saved profile names for an account slot")

    prof_set = prof.add_parser("set", help="Save profile name → id in config")
    prof_set.add_argument("--name", required=True, help="Profile label, e.g. Pavel")
    prof_set.add_argument("--id", required=True, help="CUB profile ID")

    prof_default = prof.add_parser("default", help="Set default profile for an account slot")
    prof_default.add_argument("--name", required=True, help="Saved profile name or numeric id")

    prof_remove = prof.add_parser("remove", help="Remove a saved profile name from config")
    prof_remove.add_argument("--name", required=True, help="Profile label to remove")

    prof.add_parser("sync", parents=[auth_parent], help="Fetch profiles from API and save names to config")

    # migrate
    migrate = sub.add_parser("migrate", help="Migrate bookmarks/timeline between profiles or accounts")
    mig = migrate.add_subparsers(dest="action", required=True)

    def _add_migration_args(parser: argparse.ArgumentParser, *, for_run: bool = False) -> None:
        parser.add_argument("--from-profile", help="Source profile ID")
        parser.add_argument("--to-profile", help="Target profile ID")
        parser.add_argument(
            "--from-token",
            help="Source account token (reads data). Env: CUB_FROM_TOKEN",
        )
        parser.add_argument(
            "--to-token",
            help="Target account token (writes data). Env: CUB_TO_TOKEN. "
            "Defaults to --from-token for same-account migration",
        )
        if for_run:
            parser.add_argument(
                "--from",
                dest="from_account",
                choices=list(ACCOUNT_CHOICES),
                metavar="SLOT",
                help="Source account slot: src or target",
            )
            parser.add_argument(
                "--to",
                dest="to_account",
                choices=list(ACCOUNT_CHOICES),
                metavar="SLOT",
                help="Target account slot: src or target",
            )
            parser.add_argument(
                "--cross-account",
                action="store_true",
                help="Require two explicit tokens (--from-token and --to-token)",
            )
        parser.add_argument(
            "--include",
            default="bookmarks,timeline",
            help="Comma-separated: bookmarks,timeline,notifications",
        )
        parser.add_argument(
            "--merge",
            choices=["skip", "overwrite"],
            default="skip",
            help="skip existing items or overwrite them",
        )
        parser.add_argument("--dry-run", action="store_true", help="Simulate without writing")
        parser.add_argument("--progress", action="store_true", help="Print import progress to stderr")
        parser.add_argument("--quiet", action="store_true", help="Compact JSON output (export: summary only)")
        parser.add_argument(
            "--delay",
            type=float,
            default=0.0,
            help="Seconds between API writes during import (rate limiting)",
        )

    mig_run = mig.add_parser("run", parents=[auth_parent], help="Copy data from one profile to another")
    _add_migration_args(mig_run, for_run=True)

    mig_export = mig.add_parser("export", parents=[auth_parent], help="Export profile data to JSON")
    _add_migration_args(mig_export)
    mig_export.add_argument(
        "--from",
        dest="from_account",
        choices=list(ACCOUNT_CHOICES),
        metavar="SLOT",
        help="Source account slot: src or target",
    )
    mig_export.add_argument("-o", "--output", help="Write export to file")

    mig_import = mig.add_parser("import", parents=[auth_parent], help="Import profile data to JSON")
    _add_migration_args(mig_import)
    mig_import.add_argument(
        "--to",
        dest="to_account",
        choices=list(ACCOUNT_CHOICES),
        metavar="SLOT",
        help="Target account slot: src or target",
    )
    mig_import.add_argument("-i", "--input", required=True, help="Export JSON file")

    # backup (JSON snapshot)
    backup = sub.add_parser("backup", help="Create or restore a JSON profile backup")
    bk = backup.add_subparsers(dest="action", required=True)

    def _add_backup_args(parser: argparse.ArgumentParser, *, restore: bool = False) -> None:
        parser.add_argument(
            "--include",
            default="bookmarks,timeline,notifications",
            help="Comma-separated: bookmarks,timeline,notifications",
        )
        if restore:
            parser.add_argument("-i", "--input", required=True, help="Backup JSON file")
            parser.add_argument(
                "--merge",
                choices=["skip", "overwrite"],
                default="skip",
                help="skip existing items or overwrite them",
            )
            parser.add_argument("--dry-run", action="store_true", help="Simulate without writing")
        else:
            parser.add_argument(
                "-o", "--output",
                help="Output file (default: cub-backup-<profile>-<timestamp>.json)",
            )

    bk_create = bk.add_parser("create", parents=[auth_parent], help="Download profile data to JSON file")
    _add_backup_args(bk_create)

    bk_restore = bk.add_parser("restore", parents=[auth_parent], help="Restore profile data from JSON file")
    _add_backup_args(bk_restore, restore=True)

    # bookmarks
    bookmarks = sub.add_parser("bookmarks", help="Bookmark operations")
    bm = bookmarks.add_subparsers(dest="action", required=True)

    bm_all = bm.add_parser("all", parents=[auth_parent], help="List bookmarks")
    bm_all.add_argument(
        "--full",
        type=int,
        choices=[0, 1],
        help="1 = all internal types (viewed, scheduled, look, thrown, …); omit --type to fetch everything",
    )
    bm_all.add_argument("--type", choices=list(BOOKMARK_TYPE_CHOICES))

    bm_counts = bm.add_parser("counts", parents=[auth_parent], help="Show bookmark counts by internal type")
    bm_counts.add_argument("--type", choices=list(BOOKMARK_TYPE_CHOICES), help="Optional filter (still returns all counts)")

    bm_add = bm.add_parser("add", parents=[auth_parent], help="Add bookmark")
    bm_add.add_argument("--data", required=True, help="Card JSON string or @file.json")
    bm_add.add_argument("--type", required=True, choices=list(BOOKMARK_TYPE_CHOICES))

    bm_rm = bm.add_parser("remove", parents=[auth_parent], help="Remove bookmark(s)")
    bm_rm.add_argument("--id", type=int, help="Single bookmark record id")
    bm_rm.add_argument("--list", help="JSON array of ids, e.g. '[1,2,3]'")

    # card
    card = sub.add_parser("card", help="Card metadata operations")
    cd = card.add_subparsers(dest="action", required=True)

    cd_season = cd.add_parser("season", parents=[auth_parent], help="List episodes in a season")
    cd_season.add_argument("--id", type=int, required=True)
    cd_season.add_argument("--original-name", required=True)
    cd_season.add_argument("--season", type=int, required=True)

    cd_sub = cd.add_parser("subscribed", parents=[auth_parent], help="Check translation subscription")
    cd_sub.add_argument("--id", type=int, required=True)

    cd_tr = cd.add_parser("translations", parents=[auth_parent], help="List translations")
    cd_tr.add_argument("--id", type=int, required=True)
    cd_tr.add_argument("--season", type=int, required=True)

    cd_unsub = cd.add_parser("unsubscribe", parents=[auth_parent], help="Unsubscribe from translations")
    cd_unsub.add_argument("--id", type=int, required=True)

    # collections
    collections = sub.add_parser("collections", help="Collection operations")
    col = collections.add_subparsers(dest="action", required=True)

    col_list = col.add_parser("list", parents=[auth_parent], help="List collections")
    col_list.add_argument("--page", type=int)
    col_list.add_argument("--cid", type=int, help="Filter by user id")
    col_list.add_argument(
        "--category",
        choices=["week", "month", "top", "new", "big", "all", "top-collector"],
    )

    col_roll = col.add_parser("roll", parents=[auth_parent], help="Latest 20 public collections")
    col_roll.add_argument("--cid", type=int)

    col.add_parser("top-collectors", parents=[auth_parent], help="Top 10 collectors")

    col_view = col.add_parser("view", parents=[auth_parent], help="View collection cards")
    col_view.add_argument("id", type=int)
    col_view.add_argument("--page", type=int)

    col_add = col.add_parser("add", parents=[auth_parent], help="Add card to collection")
    col_add.add_argument("--id", type=int, required=True, help="Collection id")
    col_add.add_argument("--card-id", type=int, required=True)
    col_add.add_argument("--card-type", required=True, choices=["movie", "tv"])

    col_bg = col.add_parser("background", parents=[auth_parent], help="Set collection backdrop")
    col_bg.add_argument("--id", type=int, required=True)
    col_bg.add_argument("--backdrop-path", required=True)

    col_change = col.add_parser("change", parents=[auth_parent], help="Change collection title/visibility")
    col_change.add_argument("--id", type=int, required=True)
    col_change.add_argument("--title", required=True)
    col_change.add_argument("--public", type=int, required=True, choices=[0, 1])

    col_create = col.add_parser("create", parents=[auth_parent], help="Create collection")
    col_create.add_argument("--name", required=True)

    col_liked = col.add_parser("liked", parents=[auth_parent], help="Like/unlike collection")
    col_liked.add_argument("--id", type=int, required=True)
    col_liked.add_argument("--dir", type=int, required=True, choices=[1, -1])

    col_rc = col.add_parser("remove-card", parents=[auth_parent], help="Remove card from collection")
    col_rc.add_argument("--id", type=int, required=True)
    col_rc.add_argument("--card-id", type=int, required=True)
    col_rc.add_argument("--card-type", required=True, choices=["movie", "tv"])

    col_rm = col.add_parser("remove", parents=[auth_parent], help="Delete collection")
    col_rm.add_argument("--id", type=int, required=True)

    # notice
    notice = sub.add_parser("notice", help="Notice operations")
    nt = notice.add_subparsers(dest="action", required=True)
    nt.add_parser("all", parents=[auth_parent], help="Get notices")
    nt.add_parser("clear", parents=[auth_parent], help="Mark all notices read")

    # notifications
    notifications = sub.add_parser("notifications", help="Translation notification subscriptions")
    ntf = notifications.add_subparsers(dest="action", required=True)
    ntf.add_parser("all", parents=[auth_parent], help="List subscriptions")

    ntf_add = ntf.add_parser("add", parents=[auth_parent], help="Subscribe to translation releases")
    ntf_add.add_argument("--data", required=True, help="Card JSON or @file.json")
    ntf_add.add_argument("--voice", required=True, help="Translation name, e.g. LostFilm")
    ntf_add.add_argument("--season", type=int, default=1)
    ntf_add.add_argument("--episode", type=int, default=1)

    ntf_rm = ntf.add_parser("remove", parents=[auth_parent], help="Remove subscription")
    ntf_rm.add_argument("--id", type=int, required=True)

    ntf_st = ntf.add_parser("status", parents=[auth_parent], help="Enable/disable subscription")
    ntf_st.add_argument("--id", type=int, required=True)
    ntf_st.add_argument("--status", type=int, required=True, choices=[0, 1])

    # profiles
    profiles = sub.add_parser("profiles", help="Profile operations")
    pr = profiles.add_subparsers(dest="action", required=True)
    pr.add_parser("all", parents=[auth_parent], help="List profiles")

    pr_pick = pr.add_parser("pick", parents=[auth_parent], help="Resolve profile id by name")
    pr_pick.add_argument("--name", required=True, help="Profile name (case-insensitive, partial match)")
    pr_pick.add_argument("--exact", action="store_true", help="Require exact name match")

    pr_change = pr.add_parser("change", parents=[auth_parent], help="Rename profile")
    pr_change.add_argument("--id", type=int, required=True)
    pr_change.add_argument("--name", required=True)

    pr_create = pr.add_parser("create", parents=[auth_parent], help="Create profile")
    pr_create.add_argument("--name", required=True)

    pr_rm = pr.add_parser("remove", parents=[auth_parent], help="Delete profile")
    pr_rm.add_argument("--id", type=int, required=True)

    # reactions
    reactions = sub.add_parser("reactions", help="Card reaction operations")
    rx = reactions.add_subparsers(dest="action", required=True)

    rx_add = rx.add_parser("add", parents=[auth_parent], help="Add reaction")
    rx_add.add_argument("card_id", help="e.g. movie_539972 or tv_125988")
    rx_add.add_argument("type", choices=["fire", "nice", "think", "bore", "shit"])

    rx_get = rx.add_parser("get", parents=[auth_parent], help="Get reactions")
    rx_get.add_argument("card_id", help="e.g. movie_539972 or tv_125988")

    # timeline
    timeline = sub.add_parser("timeline", help="Playback timecode operations (Premium)")
    tl = timeline.add_subparsers(dest="action", required=True)

    tl_all = tl.add_parser("all", parents=[auth_parent], help="Get timecodes")
    tl_all.add_argument("--full", type=int, choices=[0, 1])

    tl_cl = tl.add_parser("changelog", parents=[auth_parent], help="Changes since timestamp")
    tl_cl.add_argument("--since", type=int, required=True, help="Timestamp ms")

    tl.add_parser("dump", parents=[auth_parent], help="Full export with version")

    tl_up = tl.add_parser("update", parents=[auth_parent], help="Save timecode")
    tl_up.add_argument("--hash", help="Timecode hash (see hash subcommand)")
    tl_up.add_argument("--time", type=int, required=True, help="Position seconds")
    tl_up.add_argument("--duration", type=int, required=True)
    tl_up.add_argument("--percent", type=int, required=True)
    tl_up.add_argument(
        "--profile-id",
        type=int,
        help="CUB profile ID (default: from --account slot or saved config)",
    )

    tl_hash = tl.add_parser("hash", parents=[common_parent], help="Compute timeline hash (no API call)")
    tl_hash.add_argument("--movie", metavar="ORIGINAL_TITLE", help="Movie original_title")
    tl_hash.add_argument("--tv-season", type=int)
    tl_hash.add_argument("--tv-episode", type=int)
    tl_hash.add_argument("--tv-name", help="TV original_name")

    # users
    users = sub.add_parser("users", help="User operations")
    us = users.add_subparsers(dest="action", required=True)

    us_find = us.add_parser("find", parents=[auth_parent], help="Find user by email")
    us_find.add_argument("--email", required=True)

    us.add_parser("get", parents=[auth_parent], help="Get current user info")

    us_give = us.add_parser("give", parents=[auth_parent], help="Gift Premium days")
    us_give.add_argument("--to", type=int, required=True, help="Recipient user id")
    us_give.add_argument("--days", type=int, required=True, help="Days (min 5)")
    us_give.add_argument("--password", required=True)

    # list endpoints
    sub.add_parser("endpoints", help="List all supported API endpoints")

    return parser


def main(argv: list[str] | None = None) -> int:
    if DEFAULT_ENV_FILE.exists():
        try:
            load_env_file()
        except (FileNotFoundError, ValueError):
            pass

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "endpoints":
        from pathlib import Path

        spec_path = Path(__file__).resolve().parent / "api_spec.json"
        with spec_path.open(encoding="utf-8") as fh:
            spec = json.load(fh)
        for item in spec:
            auth = " [token]" if item.get("token") else ""
            print(f"{item['method']:4} {item['url']:<35} # {item['category']}/{item['name']}{auth}")
        return 0

    if args.command in ("auth", "device"):
        if args.command == "device" and args.action != "add":
            print(f"Unknown device action: {args.action}", file=sys.stderr)
            return 1
        return run_with_errors(lambda: _run_device_login(args))

    if args.command == "accounts":
        return run_with_errors(lambda: _run_accounts(args))

    if args.command == "config":
        return run_with_errors(lambda: _run_config(args))

    if args.command == "migrate":
        return run_with_errors(lambda: _run_migration(args))

    if args.command == "backup":
        return run_with_errors(lambda: _run_backup(args))

    handlers: dict[tuple[str, str | None], Callable[[CubClient, argparse.Namespace], Any]] = {
        ("bookmarks", "all"): lambda c, a: c.bookmarks_all(full=a.full, type=a.type),
        ("bookmarks", "counts"): lambda c, a: {
            "counts": c.bookmarks_all(type=a.type, full=1).get("counts") or [],
            "profile": c.profile,
        },
        ("bookmarks", "add"): lambda c, a: c.bookmarks_add(_load_json_arg(a.data), a.type),
        ("bookmarks", "remove"): lambda c, a: _bookmarks_remove(c, a),
        ("card", "season"): lambda c, a: c.card_season(a.id, a.original_name, a.season),
        ("card", "subscribed"): lambda c, a: c.card_subscribed(a.id),
        ("card", "translations"): lambda c, a: c.card_translations(a.id, a.season),
        ("card", "unsubscribe"): lambda c, a: c.card_unsubscribe(a.id),
        ("collections", "list"): lambda c, a: c.collections_list(page=a.page, cid=a.cid, category=a.category),
        ("collections", "roll"): lambda c, a: c.collections_roll(cid=a.cid),
        ("collections", "top-collectors"): lambda c, a: c.collections_top_collectors(),
        ("collections", "view"): lambda c, a: c.collections_view(a.id, page=a.page),
        ("collections", "add"): lambda c, a: c.collections_add(a.id, a.card_id, a.card_type),
        ("collections", "background"): lambda c, a: c.collections_background(a.id, a.backdrop_path),
        ("collections", "change"): lambda c, a: c.collections_change(a.id, a.title, a.public),
        ("collections", "create"): lambda c, a: c.collections_create(a.name),
        ("collections", "liked"): lambda c, a: c.collections_liked(a.id, a.dir),
        ("collections", "remove-card"): lambda c, a: c.collections_remove_card(a.id, a.card_id, a.card_type),
        ("collections", "remove"): lambda c, a: c.collections_remove(a.id),
        ("notice", "all"): lambda c, a: c.notice_all(),
        ("notice", "clear"): lambda c, a: c.notice_clear(),
        ("notifications", "all"): lambda c, a: c.notifications_all(),
        ("notifications", "add"): lambda c, a: c.notifications_add(
            _load_json_arg(a.data), a.voice, season=a.season, episode=a.episode
        ),
        ("notifications", "remove"): lambda c, a: c.notifications_remove(a.id),
        ("notifications", "status"): lambda c, a: c.notifications_status(a.id, a.status),
        ("profiles", "all"): lambda c, a: c.profiles_all(),
        ("profiles", "pick"): lambda c, a: pick_profile_by_name(
            c.profiles_all().get("profiles") or [],
            a.name,
            exact=a.exact,
        ),
        ("profiles", "change"): lambda c, a: c.profiles_change(a.id, a.name),
        ("profiles", "create"): lambda c, a: c.profiles_create(a.name),
        ("profiles", "remove"): lambda c, a: c.profiles_remove(a.id),
        ("reactions", "add"): lambda c, a: c.reactions_add(a.card_id, a.type),
        ("reactions", "get"): lambda c, a: c.reactions_get(a.card_id),
        ("timeline", "all"): lambda c, a: c.timeline_all(full=a.full),
        ("timeline", "changelog"): lambda c, a: c.timeline_changelog(a.since),
        ("timeline", "dump"): lambda c, a: c.timeline_dump(),
        ("timeline", "update"): lambda c, a: c.timeline_update(
            a.hash,
            a.time,
            a.duration,
            a.percent,
            a.profile_id or c.profile,
        ),
        ("users", "find"): lambda c, a: c.users_find(a.email),
        ("users", "get"): lambda c, a: c.users_get(),
        ("users", "give"): lambda c, a: c.users_give(a.to, a.days, a.password),
    }

    if args.command == "timeline" and args.action == "hash":
        if args.movie:
            print_json({"hash": movie_timecode_hash(args.movie)})
            return 0
        if args.tv_season is not None and args.tv_episode is not None and args.tv_name:
            print_json({"hash": tv_timecode_hash(args.tv_season, args.tv_episode, args.tv_name)})
            return 0
        print("Error: use --movie TITLE or --tv-season N --tv-episode N --tv-name NAME", file=sys.stderr)
        return 1

    action = getattr(args, "action", None)
    handler = handlers.get((args.command, action))
    if not handler:
        print(f"Unknown command: {args.command} {action}", file=sys.stderr)
        return 1

    return run_with_errors(
        lambda: _run(
            lambda client: handler(client, args),
            args,
            require_auth=command_requires_auth(args),
            quiet=getattr(args, "quiet", False),
        )
    )


def _bookmarks_remove(client: CubClient, args: argparse.Namespace) -> Any:
    if args.id is None and not args.list:
        raise ValueError("Provide --id or --list '[1,2,3]'")
    return client.bookmarks_remove(
        id=args.id,
        list=json.loads(args.list) if args.list else None,
    )


if __name__ == "__main__":
    raise SystemExit(main())
