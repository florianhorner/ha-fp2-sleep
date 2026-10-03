"""No-network regression tests for Conductor workspace bootstrap."""

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("setup_workspace", ROOT / "scripts/setup_workspace.py")
setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(setup)


def no_install(_venv):
    pass


class SetupWorkspaceTest(unittest.TestCase):
    def test_failed_candidate_does_not_contaminate_working_fallback(self):
        with tempfile.TemporaryDirectory(prefix="sleepradar-setup-test-") as temp:
            workspace = Path(temp)
            (workspace / "requirements-ci.txt").write_text("", encoding="utf-8")
            broken = workspace / "broken-python313"
            broken.write_text(
                "#!/bin/sh\n"
                "if [ \"$1\" = '-c' ]; then printf '[3,13]\\n'; exit 0; fi\n"
                "if [ \"$1\" = '-m' ]; then\n"
                "  mkdir -p \"$3/bin\"\n"
                "  ln -s /missing/python3.13 \"$3/bin/python\"\n"
                "  exit 1\n"
                "fi\n"
                "exit 1\n",
                encoding="utf-8",
            )
            broken.chmod(0o755)

            selected, error = setup.probe_candidate(str(broken))
            self.assertIsNone(selected)
            self.assertIsNotNone(error)
            setup.setup_workspace(
                workspace,
                candidates=(str(broken), sys.executable),
                installer=no_install,
                verifier=no_install,
            )

            self.assertEqual(setup.healthy_venv(workspace / ".venv"), sys.version_info[:2])
            self.assertFalse((workspace / ".context").exists())

    def test_repairs_mixed_venv_and_reuses_it_on_second_setup(self):
        with tempfile.TemporaryDirectory(prefix="sleepradar-setup-test-") as temp:
            workspace = Path(temp)
            (workspace / "requirements-ci.txt").write_text("", encoding="utf-8")
            venv = workspace / ".venv"
            (venv / "bin").mkdir(parents=True)
            (venv / "pyvenv.cfg").write_text("version = 3.11.15\n", encoding="utf-8")
            (venv / "bin/python").symlink_to("/missing/python3.13")
            self.assertIsNone(setup.healthy_venv(venv))

            setup.setup_workspace(
                workspace, candidates=(sys.executable,), installer=no_install,
                verifier=no_install,
            )
            self.assertEqual(setup.healthy_venv(venv), sys.version_info[:2])
            backups = workspace / ".context" / "setup-backups"
            self.assertEqual(list(backups.iterdir()), [])

            sentinel = venv / "sentinel"
            sentinel.write_text("keep", encoding="utf-8")
            setup.setup_workspace(
                workspace, candidates=(sys.executable,), installer=no_install,
                verifier=no_install,
            )
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")

    def test_failed_install_restores_previous_venv(self):
        with tempfile.TemporaryDirectory(prefix="sleepradar-setup-test-") as temp:
            workspace = Path(temp)
            (workspace / "requirements-ci.txt").write_text("", encoding="utf-8")
            venv = workspace / ".venv"
            venv.mkdir()
            (venv / "previous-state").write_text("recoverable", encoding="utf-8")

            def fail_install(_venv):
                raise RuntimeError("simulated dependency failure")

            with self.assertRaisesRegex(RuntimeError, "simulated dependency failure"):
                setup.setup_workspace(
                    workspace, candidates=(sys.executable,), installer=fail_install,
                    verifier=no_install,
                )
            self.assertEqual((venv / "previous-state").read_text(encoding="utf-8"), "recoverable")
            backups = workspace / ".context" / "setup-backups"
            self.assertEqual(list(backups.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
