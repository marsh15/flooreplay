"""Shared fixtures for domain tests."""

from __future__ import annotations

import pytest

from flooreplay.fixtures import (
    DEFAULT_FRESHNESS,
    hero_context,
    hero_snapshots_v1,
    hero_snapshots_v2,
)


@pytest.fixture
def hero_v1():
    return hero_context(hero_snapshots_v1())


@pytest.fixture
def hero_v2():
    return hero_context(hero_snapshots_v2())


@pytest.fixture
def settings():
    return DEFAULT_FRESHNESS
