"""Saved demo bundles must not depend on the database session timezone."""

from __future__ import annotations

import os
from contextlib import contextmanager

import pytest
from sqlalchemy import func, select

from flooreplay import release_tools
from flooreplay.db import SessionLocal
from flooreplay.seeding import run_seed

pytestmark = pytest.mark.skipif(os.environ.get("FLOORREPLAY_SKIP_DB") == "1", reason="database not available")


def test_demo_export_is_identical_across_database_timezones(tmp_path, monkeypatch) -> None:
    run_seed()
    exports = []
    for timezone in ("UTC", "Asia/Kolkata", "America/New_York"):
        @contextmanager
        def export_session(timezone=timezone):
            with SessionLocal() as session:
                session.execute(select(func.set_config("TimeZone", timezone, True)))
                yield session
                # Each export must compute a fresh report rather than reuse a cached one.
                session.rollback()

        monkeypatch.setattr(release_tools, "session_scope", export_session)
        directory = tmp_path / timezone.replace("/", "-")
        release_tools.export_demo(directory)
        exports.append({path.name: path.read_bytes() for path in directory.glob("*.json")})

    assert len(exports[0]) == 6
    assert exports[0] == exports[1] == exports[2]
