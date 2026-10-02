"""Recovery guard prevents accidental use of an owner or production database."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

spec = spec_from_file_location("recovery_drill", Path(__file__).parents[2] / "scripts/recovery_drill.py")
assert spec is not None and spec.loader is not None
recovery = module_from_spec(spec)
spec.loader.exec_module(recovery)


@pytest.mark.parametrize("name", ["flooreplay", "customer_test", "flooreplay_prod", "flooreplay_a_test;DROP DATABASE x", "flooreplay_a_test/../x"])
def test_recovery_refuses_unscoped_database(name):
    with pytest.raises(ValueError):
        recovery.validate_database(name)


def test_recovery_accepts_isolated_test_database():
    assert recovery.validate_database("flooreplay_recovery_source_20261001_test") == "flooreplay_recovery_source_20261001_test"
