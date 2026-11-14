"""Finding Blender and running jobs in it, headless, cleaning up only what we started."""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
from pathlib import Path

JOB_SCRIPT = Path(__file__).parent / "blender_side" / "job.py"
WINDOWS_GLOB = "C:/Program Files/Blender Foundation/Blender */blender.exe"


class BlenderMissing(RuntimeError):
    pass


def find(configured: str | None = None) -> str:
    """The profile's path, then $BLENDER, then PATH, then the newest standard install."""
    for candidate in (configured, os.environ.get("BLENDER"), shutil.which("blender")):
        if candidate and Path(candidate).exists():
            return str(candidate)
    installs = sorted(glob.glob(WINDOWS_GLOB), key=_version_key)
    if installs:
        return installs[-1]
    raise BlenderMissing("Blender not found: set [foundry] blender in the profile, or $BLENDER")


def _version_key(path: str) -> tuple:
    name = Path(path).parent.name.replace("Blender", "").strip()
    return tuple(int(p) if p.isdigit() else 0 for p in name.split("."))


def run(blender: str, script: Path, args: list[str], timeout: float = 300.0) -> subprocess.CompletedProcess:
    cmd = [blender, "--background", "--factory-startup", "--python", str(script), "--", *args]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8", errors="replace")
    try:
        out, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()  # only the process this call started
        out, _ = proc.communicate()
        return subprocess.CompletedProcess(cmd, -1, out + f"\n[foundry] killed after {timeout:.0f} s", None)
    return subprocess.CompletedProcess(cmd, proc.returncode, out, None)


def run_job(blender: str, job_path: Path, timeout: float = 300.0) -> subprocess.CompletedProcess:
    return run(blender, JOB_SCRIPT, [str(job_path)], timeout)


def version(blender: str) -> str:
    out = subprocess.run([blender, "--version"], capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
    return out.splitlines()[0].strip() if out else "unknown"
