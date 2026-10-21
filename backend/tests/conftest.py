"""Shared fixtures for domain tests."""

from __future__ import annotations

import os
import warnings

import pytest
from hypothesis import HealthCheck, settings
from hypothesis.errors import InvalidArgument

from flooreplay.fixtures import (
    DEFAULT_FRESHNESS,
    hero_context,
    hero_snapshots_v1,
    hero_snapshots_v2,
)

# Integration tests always use a separate database. Never fall back to owner data.
_test_url = os.environ.get("FLOORREPLAY_TEST_DATABASE_URL", "postgresql+psycopg://localhost:5433/flooreplay_release_test")
if not _test_url.split("?", 1)[0].endswith(("_test", "/test")):
    raise RuntimeError("FLOORREPLAY_TEST_DATABASE_URL must name a database ending in _test")
os.environ["FLOORREPLAY_DATABASE_URL"] = _test_url

# Wall-clock deadlines and generation-speed health checks flake on a loaded machine; they
# say nothing about correctness. Per-test max_examples is left alone.
settings.register_profile("default", deadline=None, suppress_health_check=[HealthCheck.too_slow])
_profile = os.environ.get("HYPOTHESIS_PROFILE", "default")
try:
    settings.load_profile(_profile)
except InvalidArgument:
    warnings.warn(f"unknown HYPOTHESIS_PROFILE {_profile!r}; using 'default'", stacklevel=1)
    settings.load_profile("default")


@pytest.fixture
def hero_v1():
    return hero_context(hero_snapshots_v1())


@pytest.fixture
def hero_v2():
    return hero_context(hero_snapshots_v2())


@pytest.fixture
def settings():
    return DEFAULT_FRESHNESS


@pytest.fixture(scope="session")
def owner_headers():
    import uuid

    from flooreplay.auth import create_account, sign_in
    name = "test-owner-" + uuid.uuid4().hex
    create_account(name, "test-password-long-enough", "owner")
    return {"Authorization": "Bearer " + sign_in(name, "test-password-long-enough", name)["token"]}


@pytest.fixture(scope="session")
def reviewer_headers():
    import uuid

    from flooreplay.auth import create_account, sign_in
    name = "test-reviewer-" + uuid.uuid4().hex
    create_account(name, "test-password-long-enough", "reviewer")
    return {"Authorization": "Bearer " + sign_in(name, "test-password-long-enough", name)["token"]}
