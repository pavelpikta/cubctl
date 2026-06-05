"""Shared pytest fixtures for CUB API tests."""

from __future__ import annotations

import os

import pytest

from cubctl import CubClient
from cubctl.auth import login_device
from cubctl.exceptions import CubApiError


def _has_auth_env() -> bool:
    if os.environ.get("CUB_TEST_DEVICE_CODE"):
        return True
    return bool(os.environ.get("CUB_TEST_TOKEN") and os.environ.get("CUB_TEST_PROFILE"))


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: live API tests (requires CUB_TEST_DEVICE_CODE or token env vars)",
    )
    config.addinivalue_line(
        "markers",
        "writes: mutating API calls (skipped unless CUB_TEST_WRITES=1)",
    )


@pytest.fixture(scope="session")
def base_url() -> str:
    return os.environ.get("CUB_BASE_URL", "https://cub.rip/api/")


@pytest.fixture(scope="session")
def authenticated_client(base_url: str) -> CubClient:
    """Client with token/profile from env (device code or saved credentials)."""
    if not _has_auth_env():
        pytest.skip("Set CUB_TEST_DEVICE_CODE or CUB_TEST_TOKEN + CUB_TEST_PROFILE")

    client = CubClient(base_url=base_url)
    code = os.environ.get("CUB_TEST_DEVICE_CODE")
    if code:
        login_device(client, code)
        return client

    client.set_credentials(
        os.environ["CUB_TEST_TOKEN"],
        os.environ["CUB_TEST_PROFILE"],
    )
    return client


@pytest.fixture(scope="session")
def device_code() -> str:
    code = os.environ.get("CUB_TEST_DEVICE_CODE")
    if not code:
        pytest.skip("Set CUB_TEST_DEVICE_CODE for device/add tests")
    return code


@pytest.fixture
def anonymous_client(base_url: str) -> CubClient:
    return CubClient(base_url=base_url)
