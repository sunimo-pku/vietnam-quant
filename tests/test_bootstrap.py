import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "vn_bootstrap", Path(__file__).parents[1] / "scripts/bootstrap.py"
)
bootstrap = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bootstrap)


class BootstrapTests(unittest.TestCase):
    def test_setup_once_and_reinstall_when_project_config_changes(self):
        with tempfile.TemporaryDirectory(prefix="越南 项目 ") as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("version-one", encoding="utf-8")
            executable = bootstrap.environment_python(root)
            executable.parent.mkdir(parents=True)
            executable.touch()
            completed = subprocess.CompletedProcess([], 0)
            with patch.object(bootstrap.subprocess, "run", return_value=completed) as run:
                self.assertEqual(bootstrap.prepare(root), executable)
                bootstrap.prepare(root)
                installs = [c for c in run.call_args_list if "pip" in c.args[0]]
                self.assertEqual(len(installs), 1)
                self.assertEqual(installs[0].args[0][-1], str(root))
                (root / "pyproject.toml").write_text("version-two", encoding="utf-8")
                bootstrap.prepare(root)
                self.assertEqual(len([c for c in run.call_args_list if "pip" in c.args[0]]), 2)
            marker = json.loads((root / ".venv/.vn-status-ready.json").read_text(encoding="utf-8"))
            self.assertEqual(marker["project"], str(root))

    def test_install_failure_does_not_mark_environment_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("test")
            executable = bootstrap.environment_python(root)
            executable.parent.mkdir(parents=True)
            executable.touch()
            results = [
                subprocess.CompletedProcess([], 0),
                subprocess.CompletedProcess([], 1),
                subprocess.CalledProcessError(1, ["pip"]),
            ]
            with patch.object(bootstrap.subprocess, "run", side_effect=results):
                with self.assertRaises(subprocess.CalledProcessError):
                    bootstrap.prepare(root)
            self.assertFalse((root / ".venv/.vn-status-ready.json").exists())

    def test_check_mode_never_starts_collection(self):
        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch.object(bootstrap, "ROOT", Path(tmp)),
                patch.object(bootstrap, "prepare", return_value=Path(sys_executable())),
            ):
                with (
                    patch("sys.argv", ["bootstrap.py", "--check"]),
                    patch.object(bootstrap.subprocess, "run") as run,
                ):
                    self.assertEqual(bootstrap.main(), 0)
                    run.assert_not_called()


def sys_executable():
    import sys

    return sys.executable
