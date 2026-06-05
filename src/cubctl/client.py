"""CUB REST API client (v1.29 — https://cub.rip/developer/)."""

from __future__ import annotations

import json
from typing import Any

import requests

from .exceptions import CubApiError

DEFAULT_BASE_URL = "https://cub.rip/api/"


class CubClient:
    """Client for the CUB REST API documented at https://cub.rip/developer/."""

    def __init__(
        self,
        token: str | None = None,
        profile: int | str | None = None,
        *,
        base_url: str = DEFAULT_BASE_URL,
        session: requests.Session | None = None,
        timeout: float = 30.0,
    ):
        self.token = token
        self.profile = str(profile) if profile is not None else None
        self.base_url = base_url if base_url.endswith("/") else base_url + "/"
        self.session = session or requests.Session()
        self.timeout = timeout

    # ------------------------------------------------------------------ auth
    def set_credentials(self, token: str, profile: int | str | None = None) -> None:
        self.token = token
        if profile is not None:
            self.profile = str(profile)

    def _headers(self, *, require_token: bool) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if require_token:
            if not self.token:
                raise CubApiError("Authentication required: set token or call device_add() first")
            headers["token"] = self.token
        elif self.token:
            headers["token"] = self.token
        if self.profile:
            headers["profile"] = self.profile
        return headers

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
        require_token: bool = True,
        raise_on_error: bool = True,
    ) -> Any:
        url = self.base_url + path.lstrip("/")
        filtered_query = {k: v for k, v in (query or {}).items() if v is not None}
        response = self.session.request(
            method=method.upper(),
            url=url,
            headers=self._headers(require_token=require_token),
            params=filtered_query or None,
            json=body if method.upper() == "POST" else None,
            timeout=self.timeout,
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise CubApiError(
                f"Non-JSON response ({response.status_code})",
                status_code=response.status_code,
            ) from exc

        if raise_on_error and (not response.ok or payload.get("error")):
            message = payload.get("text") or payload.get("message") or str(payload)
            raise CubApiError(
                message,
                status_code=response.status_code,
                payload=payload if isinstance(payload, dict) else {"raw": payload},
            )
        return payload

    @staticmethod
    def _card_data(data: dict[str, Any] | str) -> str:
        if isinstance(data, str):
            return data
        return json.dumps(data, ensure_ascii=False)

    # ---------------------------------------------------------------- device
    def device_add(self, code: str | int) -> dict[str, Any]:
        """
        Exchange a 6-digit access code from https://cub.rip/add for an API token.

        On success the full account object is returned (token, profile, email, …)
        and credentials are applied to this client instance.
        """
        from .auth import normalize_device_code

        normalized = normalize_device_code(code)
        result = self._request(
            "POST",
            "device/add",
            body={"code": normalized},
            require_token=False,
        )
        if not result.get("error"):
            if result.get("token"):
                self.token = result["token"]
            if result.get("profile"):
                profile = result["profile"]
                self.profile = str(profile.get("id") if isinstance(profile, dict) else profile)
        return result

    def login(self, code: str | int, *, save: bool = False):
        """
        Authenticate with a device code and return :class:`~cubctl.auth.DeviceCredentials`.

        Convenience wrapper around :func:`~cubctl.auth.login_device`.
        """
        from .auth import DeviceCredentials, login_device

        return login_device(self, code, save=save)

    @classmethod
    def from_config(cls, **kwargs: Any) -> CubClient:
        """Create a client from ``~/.cub/config.json``, account slots, and environment."""
        import os

        from .config import default_account_slot, get_account, load_config, resolve_profile_for_account

        token = kwargs.get("token") or os.environ.get("CUB_TOKEN")
        profile = kwargs.get("profile") or os.environ.get("CUB_PROFILE")
        account = kwargs.get("account") or os.environ.get("CUB_ACCOUNT")

        if not token:
            slot = account or default_account_slot()
            if slot:
                try:
                    saved = get_account(slot)
                    token = saved["token"]
                    profile = resolve_profile_for_account(slot, profile)
                except ValueError:
                    pass

        config = load_config()
        return cls(
            token=token,
            profile=profile,
            base_url=kwargs.get("base_url")
            or os.environ.get("CUB_BASE_URL")
            or config.get("base_url")
            or DEFAULT_BASE_URL,
            timeout=kwargs.get("timeout", 30.0),
        )

    # -------------------------------------------------------------- bookmarks
    def bookmarks_all(self, *, full: int | None = None, type: str | None = None) -> dict[str, Any]:
        """Return user bookmarks. type: book | history | like | wath | viewed | scheduled | …"""
        return self._request("GET", "bookmarks/all", query={"full": full, "type": type})

    def bookmarks_add(
        self,
        data: dict[str, Any] | str,
        type: str,
    ) -> dict[str, Any]:
        """Add a card to bookmarks. type: book | history | like | wath | viewed | scheduled | look | thrown | …"""
        return self._request(
            "POST",
            "bookmarks/add",
            body={"data": self._card_data(data), "type": type},
        )

    def bookmarks_remove(
        self,
        *,
        id: int | None = None,
        list: list[int] | None = None,
    ) -> dict[str, Any]:
        """Remove bookmark(s) by id or list of ids."""
        body: dict[str, Any] = {}
        if id is not None:
            body["id"] = id
        if list is not None:
            body["list"] = list
        return self._request("POST", "bookmarks/remove", body=body)

    # ------------------------------------------------------------------- card
    def card_season(self, id: int, original_name: str, season: int) -> dict[str, Any]:
        """Get episode list for a TV season."""
        return self._request(
            "POST",
            "card/season",
            body={"id": id, "original_name": original_name, "season": season},
        )

    def card_subscribed(self, id: int) -> dict[str, Any]:
        """Check if subscribed to translation notifications for a card."""
        return self._request("POST", "card/subscribed", body={"id": id})

    def card_translations(self, id: int, season: int) -> dict[str, Any]:
        """Get available translations for a TV series season."""
        return self._request("POST", "card/translations", body={"id": id, "season": season})

    def card_unsubscribe(self, id: int) -> dict[str, Any]:
        """Unsubscribe from translation notifications."""
        return self._request("POST", "card/unsubscribe", body={"id": id})

    # ------------------------------------------------------------- collections
    def collections_list(
        self,
        *,
        page: int | None = None,
        cid: int | None = None,
        category: str | None = None,
    ) -> dict[str, Any]:
        """List public collections or a user's collections."""
        return self._request(
            "GET",
            "collections/list",
            query={"page": page, "cid": cid, "category": category},
            require_token=bool(cid),
        )

    def collections_roll(self, *, cid: int | None = None) -> dict[str, Any]:
        """Return 20 latest public collections, or all user collections when cid matches token."""
        return self._request(
            "GET",
            "collections/roll",
            query={"cid": cid},
            require_token=bool(cid),
        )

    def collections_top_collectors(self) -> dict[str, Any]:
        """Top 10 users by public collection count and likes."""
        return self._request("GET", "collections/top-collectors", require_token=False)

    def collections_view(self, id: int, *, page: int | None = None) -> dict[str, Any]:
        """View cards in a collection."""
        return self._request(
            "GET",
            f"collections/view/{id}",
            query={"page": page},
            require_token=False,
        )

    def collections_add(self, id: int, card_id: int, card_type: str) -> dict[str, Any]:
        """Add a card to a collection. card_type: movie | tv."""
        return self._request(
            "POST",
            "collections/add",
            body={"id": id, "card_id": card_id, "card_type": card_type},
        )

    def collections_background(self, id: int, backdrop_path: str) -> dict[str, Any]:
        """Set collection backdrop image."""
        return self._request(
            "POST",
            "collections/background",
            body={"id": id, "backdrop_path": backdrop_path},
        )

    def collections_change(self, id: int, title: str, public: int) -> dict[str, Any]:
        """Change collection title and public flag (0 private, 1 public)."""
        return self._request(
            "POST",
            "collections/change",
            body={"id": id, "title": title, "public": public},
        )

    def collections_create(self, name: str) -> dict[str, Any]:
        """Create a new user collection."""
        return self._request("POST", "collections/create", body={"name": name})

    def collections_liked(self, id: int, dir: int) -> dict[str, Any]:
        """Like (1) or unlike (-1) a collection."""
        return self._request(
            "POST",
            "collections/liked",
            body={"id": id, "dir": dir},
            require_token=False,
        )

    def collections_remove_card(self, id: int, card_id: int, card_type: str) -> dict[str, Any]:
        """Remove a card from a collection."""
        return self._request(
            "POST",
            "collections/remove-card",
            body={"id": id, "card_id": card_id, "card_type": card_type},
        )

    def collections_remove(self, id: int) -> dict[str, Any]:
        """Delete a collection and all its cards."""
        return self._request("POST", "collections/remove", body={"id": id})

    # ------------------------------------------------------------------ notice
    def notice_all(self) -> dict[str, Any]:
        """Get user notices."""
        return self._request("GET", "notice/all")

    def notice_clear(self) -> dict[str, Any]:
        """Mark all notices as read."""
        return self._request("GET", "notice/clear")

    # ----------------------------------------------------------- notifications
    def notifications_all(self) -> dict[str, Any]:
        """List cards subscribed for translation release notifications."""
        return self._request("GET", "notifications/all")

    def notifications_add(
        self,
        data: dict[str, Any] | str,
        voice: str,
        *,
        season: int = 1,
        episode: int = 1,
    ) -> dict[str, Any]:
        """Subscribe to translation release notifications."""
        return self._request(
            "POST",
            "notifications/add",
            body={
                "data": self._card_data(data),
                "voice": voice,
                "season": season,
                "episode": episode,
            },
        )

    def notifications_remove(self, id: int) -> dict[str, Any]:
        """Remove a translation notification subscription."""
        return self._request("POST", "notifications/remove", body={"id": id})

    def notifications_status(self, id: int, status: int) -> dict[str, Any]:
        """Enable (1) or disable (0) a notification."""
        return self._request("POST", "notifications/status", body={"id": id, "status": status})

    # ---------------------------------------------------------------- profiles
    def profiles_all(self) -> dict[str, Any]:
        """List user profiles."""
        return self._request("GET", "profiles/all")

    def profiles_change(self, id: int, name: str) -> dict[str, Any]:
        """Rename a profile."""
        return self._request("POST", "profiles/change", body={"id": id, "name": name})

    def profiles_create(self, name: str) -> dict[str, Any]:
        """Create a new profile."""
        return self._request("POST", "profiles/create", body={"name": name})

    def profiles_remove(self, id: int) -> dict[str, Any]:
        """Delete a profile and its bookmarks."""
        return self._request("POST", "profiles/remove", body={"id": id})

    # --------------------------------------------------------------- reactions
    def reactions_add(self, card_id: str, type: str) -> dict[str, Any]:
        """Add reaction to a card. id format: movie_123 | tv_456. type: fire | nice | think | bore | shit."""
        return self._request(
            "GET",
            f"reactions/add/{card_id}/{type}",
            require_token=False,
        )

    def reactions_get(self, card_id: str) -> dict[str, Any]:
        """Get reactions for a card. id format: movie_123 | tv_456."""
        return self._request("GET", f"reactions/get/{card_id}", require_token=False)

    # ---------------------------------------------------------------- timeline
    def timeline_all(self, *, full: int | None = None) -> dict[str, Any]:
        """Get playback timecodes for current profile (Premium). full=1 removes 50-item limit."""
        return self._request("GET", "timeline/all", query={"full": full})

    def timeline_changelog(self, since: int) -> dict[str, Any]:
        """Get timecodes changed after timestamp ms (Premium sync)."""
        return self._request("GET", "timeline/changelog", query={"since": since})

    def timeline_dump(self) -> dict[str, Any]:
        """Export all profile timecodes with version (Premium backup)."""
        return self._request("GET", "timeline/dump")

    def timeline_update(
        self,
        hash: str,
        time: int,
        duration: int,
        percent: int,
        profile: int,
    ) -> dict[str, Any]:
        """Save or update a playback timecode (Premium)."""
        return self._request(
            "POST",
            "timeline/update",
            body={
                "hash": hash,
                "time": time,
                "duration": duration,
                "percent": percent,
                "profile": profile,
            },
        )

    # ------------------------------------------------------------------- users
    def users_find(self, email: str) -> dict[str, Any]:
        """Find a user by email."""
        return self._request("GET", "users/find", query={"email": email}, require_token=False)

    def users_get(self) -> dict[str, Any]:
        """Get authenticated user info."""
        return self._request("GET", "users/get")

    def users_give(self, to: int, days: int, password: str) -> dict[str, Any]:
        """Gift CUB Premium days to another user (min 5 days)."""
        return self._request("POST", "users/give", body={"to": to, "days": days, "password": password})
