"""The Alembic revision this build expects the database to be at.

Leaf module (no package imports) so the readiness check and tests share one literal.
Every migration in the v2 lane bumps this constant in the same commit.
"""

from __future__ import annotations

SCHEMA_HEAD = "20261021_decisions_facts"
