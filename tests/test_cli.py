"""CLI tests (subprocess). Live API cases are marked integration."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"


def _run_cub(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    run_env = os.environ.copy()
    run_env["PYTHONPATH"] = str(SRC)
    run_env["CUB_CONFIG_DIR"] = run_env.get("CUB_CONFIG_DIR", "/tmp/cub-cli-test-empty")
    if env:
        run_env.update(env)
    return subprocess.run(
        [sys.executable, "-m", "cubctl", *args],
        capture_output=True,
        text=True,
        env=run_env,
        check=False,
    )


@pytest.mark.integration
class TestPublicCommands:
    def test_collections_top_collectors_without_auth(self):
        proc = _run_cub("collections", "top-collectors")
        assert proc.returncode == 0, proc.stderr
        data = json.loads(proc.stdout)
        assert data.get("secuses") is True

    def test_reactions_get_without_auth(self):
        proc = _run_cub("reactions", "get", "movie_550")
        assert proc.returncode == 0, proc.stderr
        assert "secuses" in proc.stdout


class TestAuthRequired:
    def test_bookmarks_requires_auth(self):
        proc = _run_cub("bookmarks", "all", "--type", "book")
        assert proc.returncode == 1
        assert "Authentication required" in proc.stderr


class TestCliValidation:
    def test_bookmarks_remove_requires_id_or_list(self):
        proc = _run_cub("bookmarks", "remove", "--token", "x", "--profile", "1")
        assert proc.returncode == 1
        assert "Provide --id or --list" in proc.stderr

    def test_migrate_run_requires_profiles(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text(
            json.dumps(
                {
                    "account_src": {"token": "a", "profile": "111"},
                    "account_target": {"token": "b", "profile": "222"},
                }
            ),
            encoding="utf-8",
        )
        proc = _run_cub(
            "migrate", "run", "--from", "src", "--to", "target",
            env={"CUB_CONFIG_DIR": str(tmp_path)},
        )
        assert proc.returncode == 1
        assert "--from-profile" in proc.stderr


class TestCliSmoke:
    def test_endpoints_command(self):
        proc = _run_cub("endpoints")
        assert proc.returncode == 0
        assert "device/add" in proc.stdout

    def test_config_path(self):
        proc = _run_cub("config", "path")
        assert proc.returncode == 0
        assert proc.stdout.strip().endswith("config.json")

    def test_config_show_empty(self):
        proc = _run_cub("config", "show", env={"CUB_CONFIG_DIR": "/tmp/cub-cli-test-empty-config"})
        assert proc.returncode == 0
        data = json.loads(proc.stdout)
        assert "config_file" in data

    def test_profiles_pick_unit(self, tmp_path, monkeypatch):
        from cubctl.cli_helpers import pick_profile_by_name

        profiles = [
            {"id": 1, "name": "Pavel"},
            {"id": 2, "name": "DEVOPS"},
        ]
        assert pick_profile_by_name(profiles, "pavel")["id"] == 1
        assert pick_profile_by_name(profiles, "dev", exact=False)["id"] == 2
