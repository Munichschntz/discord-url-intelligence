"""Offline checks for the Windows setup and isolated launcher."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which("powershell")
pytestmark = pytest.mark.skipif(
    sys.platform != "win32" or POWERSHELL is None, reason="Windows PowerShell launcher"
)


def run_script(path: Path, *args: str, cwd: Path, env=None):
    return subprocess.run(
        [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(path), *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_launcher_missing_environment_does_not_fall_back(tmp_path: Path):
    shutil.copy(ROOT / "run.ps1", tmp_path)
    result = run_script(tmp_path / "run.ps1", "--help", cwd=tmp_path)
    assert result.returncode != 0
    assert "Run .\\setup.ps1 first" in result.stderr


def test_launcher_rejects_external_base_runtime(tmp_path: Path):
    shutil.copy(ROOT / "run.ps1", tmp_path)
    scripts = tmp_path / ".venv" / "Scripts"
    scripts.mkdir(parents=True)
    (scripts / "python.exe").touch()  # Must be rejected before any executable is called.
    (scripts.parent / "pyvenv.cfg").write_text(
        "home = C:\\system-python\ninclude-system-site-packages = false\n", encoding="utf-8"
    )
    result = run_script(tmp_path / "run.ps1", "--help", cwd=tmp_path)
    assert result.returncode != 0
    assert "private project runtime" in result.stderr


def test_setup_failure_keeps_environment_and_settings(tmp_path: Path):
    project = tmp_path / "Project with spaces"
    project.mkdir()
    shutil.copy(ROOT / "setup.ps1", project)
    shutil.copy(ROOT / ".python-version", project)
    old_venv = project / ".venv"
    old_venv.mkdir()
    marker = old_venv / "keep.txt"
    marker.write_text("preserved", encoding="utf-8")
    # Simulate a download failure. No network or real package installation is invoked.
    shim = tmp_path / "bin"
    shim.mkdir()
    (shim / "uv.cmd").write_text(
        "@echo off\n"
        "echo ARGS=%*\n"
        "echo RUNTIME=%UV_PYTHON_INSTALL_DIR%\n"
        "echo VENV=%UV_PROJECT_ENVIRONMENT%\n"
        "echo BIN=%UV_PYTHON_INSTALL_BIN%\n"
        "echo REGISTRY=%UV_PYTHON_INSTALL_REGISTRY%\n"
        "exit /b 23\n",
        encoding="utf-8",
    )
    harness = tmp_path / "harness.ps1"
    harness.write_text(
        "$env:UV_PYTHON_INSTALL_DIR = 'original-runtime'\n"
        "$env:VIRTUAL_ENV = 'original-venv'\n"
        "$start = (Get-Location).Path\n"
        "try { & (Join-Path $PSScriptRoot 'Project with spaces\\setup.ps1') } catch {\n"
        "  Write-Output $_.Exception.Message\n"
        "}\n"
        "if ($env:UV_PYTHON_INSTALL_DIR -ne 'original-runtime') { exit 31 }\n"
        "if ($env:VIRTUAL_ENV -ne 'original-venv') { exit 32 }\n"
        "if ((Get-Location).Path -ne $start) { exit 33 }\n"
        "exit 0\n",
        encoding="utf-8",
    )
    env = dict(os.environ, PATH=str(shim) + os.pathsep + os.environ["PATH"])
    result = run_script(harness, cwd=tmp_path, env=env)
    assert result.returncode == 0, result.stderr
    assert "Project Python installation failed" in result.stdout
    assert f"RUNTIME={project / '.python'}" in result.stdout
    assert f"VENV={old_venv}" in result.stdout
    assert "--no-bin --no-registry" in result.stdout
    assert "BIN=0" in result.stdout and "REGISTRY=0" in result.stdout
    assert marker.read_text(encoding="utf-8") == "preserved"


def test_installed_launcher_ignores_pythonpath_and_propagates_exit_code(tmp_path: Path):
    config = ROOT / ".venv" / "pyvenv.cfg"
    if not config.exists():
        pytest.skip("Run setup.ps1 for the installed-runtime smoke check")
    if str(ROOT / ".python") not in config.read_text(encoding="utf-8"):
        pytest.skip("Run setup.ps1 for the installed-runtime smoke check")
    (tmp_path / "discord_intel.py").write_text("raise RuntimeError('Wrong module')\n")
    env = dict(os.environ, PYTHONPATH=str(tmp_path), PYTHONHOME=str(tmp_path))
    probe = subprocess.run(
        [
            str(ROOT / ".venv" / "Scripts" / "python.exe"),
            "-I",
            "-c",
            "import json, site, sys; "
            "print(json.dumps([sys.prefix, sys.base_prefix, site.ENABLE_USER_SITE]))",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    prefix, base, user_site = json.loads(probe.stdout)
    assert Path(prefix).resolve() == (ROOT / ".venv").resolve()
    assert Path(base).resolve().is_relative_to((ROOT / ".python").resolve())
    assert user_site is False
    result = run_script(ROOT / "run.ps1", "--help", cwd=tmp_path, env=env)
    assert result.returncode == 0, result.stderr
    assert "usage: discord-intel" in result.stdout
    invalid = run_script(ROOT / "run.ps1", "not-a-command", cwd=tmp_path, env=env)
    assert invalid.returncode == 2
