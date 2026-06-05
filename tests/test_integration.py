"""Live integration tests against the CUB API."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from cubctl import CubClient
from cubctl.auth import login_device
from cubctl.exceptions import CubApiError

from tests.helpers import assert_api_error, assert_success

pytestmark = pytest.mark.integration

API_SPEC = Path(__file__).resolve().parents[1] / "src" / "cubctl" / "api_spec.json"
KNOWN_TV_ID = 95396
KNOWN_TV_NAME = "Severance"


class TestDeviceAdd:
    def test_invalid_code_returns_error(self, anonymous_client: CubClient):
        with pytest.raises(CubApiError) as exc:
            anonymous_client.device_add("000000")
        assert_api_error(exc.value)

    def test_login_with_device_code(self, anonymous_client: CubClient, device_code: str):
        credentials = login_device(anonymous_client, device_code)
        assert len(credentials.token) > 10
        assert credentials.profile_id.isdigit()
        assert credentials.email


class TestPublicEndpoints:
    def test_collections_top_collectors(self, anonymous_client: CubClient):
        result = anonymous_client.collections_top_collectors()
        assert_success(result)
        assert isinstance(result["results"], list)

    def test_collections_list(self, anonymous_client: CubClient):
        result = anonymous_client.collections_list(category="new", page=1)
        assert_success(result)
        assert isinstance(result["results"], list)

    def test_collections_roll(self, anonymous_client: CubClient):
        result = anonymous_client.collections_roll()
        assert_success(result)

    def test_collections_view(self, anonymous_client: CubClient):
        listing = anonymous_client.collections_list(category="new", page=1)
        assert_success(listing)
        if not listing["results"]:
            pytest.skip("No public collections to view")
        collection_id = listing["results"][0]["id"]
        result = anonymous_client.collections_view(collection_id, page=1)
        assert_success(result)

    def test_reactions_get(self, anonymous_client: CubClient):
        result = anonymous_client.reactions_get("movie_550")
        assert_success(result)
        assert isinstance(result["result"], list)

    def test_users_find(self, anonymous_client: CubClient, authenticated_client: CubClient):
        user = authenticated_client.users_get()
        email = user["user"]["email"]
        result = anonymous_client.users_find(email)
        assert_success(result)
        assert result["email"] == email


class TestAuthenticatedReads:
    def test_users_get(self, authenticated_client: CubClient):
        result = authenticated_client.users_get()
        assert_success(result)
        assert "email" in result["user"]

    def test_profiles_all(self, authenticated_client: CubClient):
        result = authenticated_client.profiles_all()
        assert_success(result)
        assert len(result["profiles"]) >= 1

    @pytest.mark.parametrize("bookmark_type", ["book", "history", "like", "wath"])
    def test_bookmarks_all(self, authenticated_client: CubClient, bookmark_type: str):
        result = authenticated_client.bookmarks_all(type=bookmark_type)
        assert_success(result)
        assert "counts" in result
        assert isinstance(result["bookmarks"], list)
        assert isinstance(result["counts"], list)

    def test_notice_all(self, authenticated_client: CubClient):
        result = authenticated_client.notice_all()
        assert_success(result)
        assert isinstance(result["notice"], list)

    def test_notifications_all(self, authenticated_client: CubClient):
        result = authenticated_client.notifications_all()
        assert_success(result)
        assert isinstance(result["notifications"], list)

    def test_timeline_all(self, authenticated_client: CubClient):
        result = authenticated_client.timeline_all()
        assert_success(result)
        assert isinstance(result["timelines"], dict)

    def test_timeline_dump(self, authenticated_client: CubClient):
        result = authenticated_client.timeline_dump()
        assert_success(result)
        assert "version" in result

    def test_timeline_changelog(self, authenticated_client: CubClient):
        result = authenticated_client.timeline_changelog(since=1700000000000)
        assert_success(result)
        assert "version" in result


class TestCardEndpoints:
    def test_card_season(self, authenticated_client: CubClient):
        result = authenticated_client.card_season(KNOWN_TV_ID, KNOWN_TV_NAME, 1)
        assert_success(result)
        assert "season" in result

    def test_card_translations(self, authenticated_client: CubClient):
        result = authenticated_client.card_translations(KNOWN_TV_ID, 1)
        assert_success(result)
        assert isinstance(result["translations"], dict)
        assert "voice" in result["translations"]

    def test_card_subscribed(self, authenticated_client: CubClient):
        try:
            result = authenticated_client.card_subscribed(KNOWN_TV_ID)
            assert_success(result)
        except CubApiError as exc:
            # 466 = no subscriptions — valid account state
            assert_api_error(exc, allowed_codes={466})


class TestReactionsAdd:
    def test_reactions_add_or_already_reacted(self, anonymous_client: CubClient):
        try:
            result = anonymous_client.reactions_add("movie_539972", "think")
            assert_success(result)
        except CubApiError as exc:
            # Already reacted on this card/IP is acceptable
            assert exc.payload.get("error") is True


class TestApiSpecCoverage:
    """Ensure every documented endpoint has a client method."""

    def test_all_endpoints_implemented(self):
        spec = json.loads(API_SPEC.read_text(encoding="utf-8"))
        client = CubClient(token="x", profile="1")
        missing = []
        for item in spec:
            category = item["category"].replace("-", "_")
            name = item["name"].replace("-", "_")
            method_name = f"{category}_{name}"
            if not hasattr(client, method_name):
                missing.append(f"{item['method']} {item['url']} -> {method_name}")
        assert not missing, "Missing client methods:\n" + "\n".join(missing)


class TestCliSmoke:
    def test_endpoints_command(self):
        import subprocess
        import sys

        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
        proc = subprocess.run(
            [sys.executable, "-m", "cubctl", "endpoints"],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        assert proc.returncode == 0
        assert "device/add" in proc.stdout
        assert "bookmarks/all" in proc.stdout
