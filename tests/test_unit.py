"""Unit tests (no network)."""

from __future__ import annotations

import json

import pytest

from cubctl.auth import DeviceCredentials, normalize_device_code, parse_account_response
from cubctl.exceptions import CubApiError
from cubctl.hash_utils import movie_timecode_hash, timecode_hash, tv_timecode_hash


class TestNormalizeDeviceCode:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("817935", 817935),
            (817935, 817935),
            (" 817935 ", 817935),
        ],
    )
    def test_valid_codes(self, raw, expected):
        assert normalize_device_code(raw) == expected

    @pytest.mark.parametrize("raw", ["12345", "1234567", "abcdef", "", "12ab56"])
    def test_invalid_codes(self, raw):
        with pytest.raises(ValueError, match="6 digits"):
            normalize_device_code(raw)


class TestParseAccountResponse:
    def test_parses_profile_object(self):
        creds = parse_account_response(
            {"token": "abc", "profile": {"id": 311323}, "email": "user@example.com"}
        )
        assert creds == DeviceCredentials(
            token="abc",
            profile_id="311323",
            email="user@example.com",
            raw={"token": "abc", "profile": {"id": 311323}, "email": "user@example.com"},
        )

    def test_parses_profile_scalar(self):
        creds = parse_account_response({"token": "abc", "profile": 99})
        assert creds.profile_id == "99"

    def test_missing_token_raises(self):
        with pytest.raises(CubApiError, match="no token"):
            parse_account_response({"profile": {"id": 1}})

    def test_missing_profile_raises(self):
        with pytest.raises(CubApiError, match="no profile"):
            parse_account_response({"token": "abc"})


class TestConfigAccounts:
    def test_normalize_account_key(self, tmp_path, monkeypatch):
        from cubctl import config

        monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.json")
        assert config.normalize_account_key("src") == "account_src"
        assert config.normalize_account_key("target") == "account_target"
        with pytest.raises(ValueError, match="Unknown account"):
            config.normalize_account_key("one")

    def test_save_and_get_account(self, tmp_path, monkeypatch):
        from cubctl import config

        monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.json")
        config.save_account("src", token="tok1", profile="111", email="a@test.com")
        acc = config.get_account("src")
        assert acc["token"] == "tok1"
        assert acc["profile"] == "111"

    def test_load_env_file(self, tmp_path, monkeypatch):
        from cubctl import config

        env_file = tmp_path / "accounts.env"
        env_file.write_text(
            "# comment\nCUB_CODE_SRC=111111\nCUB_CODE_TARGET=222222\n",
            encoding="utf-8",
        )
        monkeypatch.delenv("CUB_CODE_SRC", raising=False)
        monkeypatch.delenv("CUB_CODE_TARGET", raising=False)
        config.load_env_file(env_file)
        assert config.device_codes_from_env() == ("111111", "222222")

    def test_list_accounts_uses_slot_labels(self, tmp_path, monkeypatch):
        from cubctl import config

        monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.json")
        config.save_account("src", token="tok1", profile="111", email="a@test.com")
        config.save_account("target", token="tok2", profile="222", email="b@test.com")
        listed = config.list_accounts()
        assert set(listed) == {"src", "target"}
        assert listed["src"]["profile"] == "111"

    def test_save_and_resolve_profile_name(self, tmp_path, monkeypatch):
        from cubctl import config

        monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.json")
        config.save_account("src", token="tok1", profile="111", email="a@test.com")
        config.save_profile_alias("src", label="Pavel", profile_id="311483")
        assert config.resolve_profile_id("src", "Pavel") == "311483"
        assert config.resolve_profile_id("src", "311484") == "311484"
        assert config.resolve_profile_for_account("src", "Pavel") == "311483"
        assert config.resolve_profile_for_account("src", None) == "111"

    def test_show_config_redacts_tokens(self, tmp_path, monkeypatch):
        from cubctl import config

        monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.json")
        config.save_account("src", token="secret", profile="111", email="a@test.com")
        payload = config.show_config()
        assert "secret" not in json.dumps(payload)
        assert payload["accounts"]["src"]["token_set"] is True


class TestResolveCredentials:
    def test_account_target(self, tmp_path, monkeypatch):
        from cubctl import config
        from cubctl.cli_helpers import resolve_credentials
        import argparse

        monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.json")
        config.save_account("src", token="tok1", profile="111", email="a@test.com")
        config.save_account("target", token="tok2", profile="222", email="b@test.com")

        args = argparse.Namespace(account="target", profile=None, token=None)
        token, profile = resolve_credentials(args)
        assert token == "tok2"
        assert profile == "222"

    def test_profile_override(self, tmp_path, monkeypatch):
        from cubctl import config
        from cubctl.cli_helpers import resolve_credentials
        import argparse

        monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.json")
        config.save_account("src", token="tok1", profile="111", email="a@test.com")

        args = argparse.Namespace(account="src", profile="999", token=None)
        token, profile = resolve_credentials(args)
        assert token == "tok1"
        assert profile == "999"

    def test_env_account(self, tmp_path, monkeypatch):
        from cubctl import config
        from cubctl.cli_helpers import resolve_credentials
        import argparse

        monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.json")
        config.save_account("target", token="tok2", profile="222", email="b@test.com")
        monkeypatch.setenv("CUB_ACCOUNT", "target")

        args = argparse.Namespace(account=None, profile=None, token=None)
        token, profile = resolve_credentials(args)
        assert token == "tok2"
        assert profile == "222"

    def test_profile_override_by_name(self, tmp_path, monkeypatch):
        from cubctl import config
        from cubctl.cli_helpers import resolve_credentials
        import argparse

        monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.json")
        config.save_account("src", token="tok1", profile="111", email="a@test.com")
        config.save_profile_alias("src", label="Pavel", profile_id="311483")

        args = argparse.Namespace(account="src", profile="Pavel", token=None)
        token, profile = resolve_credentials(args)
        assert token == "tok1"
        assert profile == "311483"

    def test_fallback_to_account_src(self, tmp_path, monkeypatch):
        from cubctl import config
        from cubctl.cli_helpers import resolve_credentials
        import argparse

        monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.json")
        config.save_account("src", token="tok1", profile="111", email="a@test.com")
        monkeypatch.delenv("CUB_ACCOUNT", raising=False)

        args = argparse.Namespace(account=None, profile=None, token=None)
        token, profile = resolve_credentials(args)
        assert token == "tok1"
        assert profile == "111"


class TestTimecodeHash:
    def test_empty_string(self):
        assert timecode_hash("") == "0"

    def test_movie_hash_known_value(self):
        assert movie_timecode_hash("Inception") == "302508925"

    def test_tv_hash_is_numeric_string(self):
        value = tv_timecode_hash(1, 1, "Severance")
        assert value.isdigit()
        assert int(value) >= 0

    def test_tv_hash_season_separator(self):
        # season > 10 inserts ":" in the hash input
        assert tv_timecode_hash(11, 1, "Show") != tv_timecode_hash(1, 1, "Show11")
