"""ServiceError lives in its own leaf module so shared code never imports coverage modules."""

import ast
from pathlib import Path

import flooreplay.errors
import flooreplay.service


def test_service_error_is_shared_between_errors_and_service() -> None:
    assert flooreplay.errors.ServiceError is flooreplay.service.ServiceError


def test_errors_module_has_no_intra_package_imports() -> None:
    tree = ast.parse(Path(flooreplay.errors.__file__).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.level == 0, "relative import in errors.py"
            assert not (node.module or "").startswith("flooreplay")
        elif isinstance(node, ast.Import):
            assert not any(a.name.startswith("flooreplay") for a in node.names)
