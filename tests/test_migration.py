"""Unit tests for profile/account migration."""

from __future__ import annotations

import json

import pytest

from cubctl.exceptions import CubApiError
from cubctl.migration import (
    MIGRATION_VERSION,
    import_bookmarks,
    import_timeline,
    load_export,
    save_export,
)


class TestMigrationHelpers:
    def test_bookmark_key(self):
        from cubctl.migration import _bookmark_key

        assert _bookmark_key({"type": "book", "card_id": "123"}) == ("book", "123")

    def test_decode_card_data(self):
        from cubctl.migration import _decode_card_data

        card = {"id": 1, "title": "Test"}
        assert _decode_card_data({"data": json.dumps(card)}) == card
        assert _decode_card_data({"data": card}) == card


class TestImportBookmarksDryRun:
    def test_skip_existing(self):
        class FakeClient:
            profile = None

            def bookmarks_all(self, *, full=None, type=None):
                if full == 1:
                    return {"bookmarks": [{"type": "book", "card_id": "99", "data": "{}"}]}
                if type == "book":
                    return {"bookmarks": [{"type": "book", "card_id": "99", "data": "{}"}]}
                return {"bookmarks": []}

        stats = import_bookmarks(
            FakeClient(),  # type: ignore[arg-type]
            1,
            {
                "book": [
                    {"type": "book", "card_id": "99", "data": "{}"},
                    {"type": "book", "card_id": "100", "data": '{"id":100}'},
                ]
            },
            dry_run=True,
            merge="skip",
        )
        assert stats["book"].skipped == 1
        assert stats["book"].imported == 1

    def test_import_viewed_type(self):
        class FakeClient:
            profile = None
            added: list[tuple[str, str]] = []

            def bookmarks_all(self, *, full=None, type=None):
                return {"bookmarks": []}

            def bookmarks_add(self, data, type):
                self.added.append((type, str(data.get("id") if isinstance(data, dict) else "")))
                return {"secuses": True}

        client = FakeClient()
        stats = import_bookmarks(
            client,  # type: ignore[arg-type]
            1,
            {"viewed": [{"type": "viewed", "card_id": "42", "data": '{"id":42}'}]},
            dry_run=False,
            merge="skip",
        )
        assert stats["viewed"].imported == 1
        assert client.added == [("viewed", "42")]


class TestFetchAllBookmarks:
    def test_groups_by_internal_type(self):
        from cubctl.migration import fetch_all_bookmarks

        class FakeClient:
            def bookmarks_all(self, *, full=None, type=None):
                assert full == 1
                assert type is None
                return {
                    "bookmarks": [
                        {"type": "viewed", "card_id": "1"},
                        {"type": "viewed", "card_id": "2"},
                        {"type": "scheduled", "card_id": "3"},
                    ]
                }

        grouped = fetch_all_bookmarks(FakeClient())  # type: ignore[arg-type]
        assert len(grouped["viewed"]) == 2
        assert len(grouped["scheduled"]) == 1


class TestImportTimelineDryRun:
    def test_skip_existing_hashes(self):
        class FakeClient:
            profile = None

            def timeline_dump(self):
                return {"timelines": {"111": {"hash": "111", "time": 1, "duration": 10, "percent": 10}}}

        stats = import_timeline(
            FakeClient(),  # type: ignore[arg-type]
            2,
            {
                "timelines": {
                    "111": {"hash": "111", "time": 5, "duration": 10, "percent": 50},
                    "222": {"hash": "222", "time": 100, "duration": 200, "percent": 50},
                }
            },
            dry_run=True,
            merge="skip",
        )
        assert stats.exported == 2
        assert stats.skipped == 1
        assert stats.imported == 1


class TestExportFileRoundtrip:
    def test_save_and_load(self, tmp_path):
        payload = {
            "version": MIGRATION_VERSION,
            "source_profile": "1",
            "bookmarks": {"book": []},
            "timeline": {"timelines": {}},
        }
        path = tmp_path / "export.json"
        save_export(str(path), payload)
        loaded = load_export(str(path))
        assert loaded["source_profile"] == "1"

    def test_unsupported_version(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text(json.dumps({"version": 999}), encoding="utf-8")
        with pytest.raises(ValueError, match="Unsupported export version"):
            load_export(str(path))


class TestExportSummary:
    def test_summarize_export(self):
        from cubctl.migration import summarize_export

        summary = summarize_export(
            {
                "bookmarks": {
                    "book": [{"id": 1, "type": "book", "card_id": "1"}],
                    "viewed": [{"id": 2, "type": "viewed", "card_id": "2"}],
                },
                "timeline": {"timelines": {"a": {}, "b": {}}},
                "notifications": [{}],
            }
        )
        assert summary["bookmarks"]["book"] == 1
        assert summary["bookmarks"]["viewed"] == 1
        assert summary["timeline"] == 2
        assert summary["notifications"] == 1

    def test_default_backup_path(self):
        from cubctl.migration import default_backup_path

        path = default_backup_path(311484, profile_name="Viktor")
        assert path.startswith("cub-backup-Viktor-")
        assert path.endswith(".json")


class TestResolveMigrationTokens:
    def test_same_account_one_token(self):
        from cubctl.migration import resolve_migration_tokens

        src, dst, cross = resolve_migration_tokens(
            from_token="abc",
            to_token=None,
            default_token=None,
        )
        assert src == dst == "abc"
        assert cross is False

    def test_cross_account_two_tokens(self):
        from cubctl.migration import resolve_migration_tokens

        src, dst, cross = resolve_migration_tokens(
            from_token="aaa",
            to_token="bbb",
            default_token=None,
        )
        assert src == "aaa"
        assert dst == "bbb"
        assert cross is True

    def test_cross_account_flag_requires_two_tokens(self):
        from cubctl.migration import resolve_migration_tokens

        with pytest.raises(ValueError, match="two tokens"):
            resolve_migration_tokens(
                from_token="aaa",
                to_token=None,
                default_token=None,
                cross_account=True,
            )

    def test_clients_for_migration(self):
        from cubctl.migration import clients_for_migration

        clients = clients_for_migration(
            from_token="aaa",
            from_profile=1,
            to_token="bbb",
            to_profile=2,
            base_url="https://cub.rip/api/",
        )
        assert clients.cross_account is True
        assert clients.source.token == "aaa"
        assert clients.target.token == "bbb"
