"""The rollback harness must refuse production data and unsafe release targets."""
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from application_rollback_drill import validate_ref, validate_restore


class RollbackBoundaries(unittest.TestCase):
    def test_dedicated_restore_is_allowed(self):
        self.assertEqual(validate_restore('flooreplay_recovery_restore_20261002000000_test'), 'flooreplay_recovery_restore_20261002000000_test')

    def test_production_database_is_refused(self):
        with self.assertRaises(ValueError):
            validate_restore('flooreplay')

    def test_another_test_database_is_refused(self):
        with self.assertRaises(ValueError):
            validate_restore('flooreplay_browser_test')

    def test_option_or_branch_cannot_be_a_release_identity(self):
        with patch('application_rollback_drill.command') as command:
            with self.assertRaises(ValueError):
                validate_ref('--unsafe-ref')
            command.assert_not_called()

    def test_optimized_execution_refuses_before_any_drill_action(self):
        result = subprocess.run([sys.executable, '-O', str(Path(__file__).with_name('application_rollback_drill.py')), '--help'], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('without Python optimization', result.stderr)

    def test_pre_workspace_release_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'private workspace boundary'):
            validate_ref('04e0466')


if __name__ == '__main__':
    unittest.main()
