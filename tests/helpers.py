"""Test helpers."""

from __future__ import annotations

from cubctl.exceptions import CubApiError


def assert_success(payload: dict) -> None:
    assert isinstance(payload, dict)
    assert payload.get("error") is not True
    assert payload.get("secuses") is True


def assert_api_error(exc: CubApiError, *, allowed_codes: set[int] | None = None) -> None:
    assert exc.payload.get("error") is True
    if allowed_codes is not None:
        assert exc.payload.get("code") in allowed_codes
