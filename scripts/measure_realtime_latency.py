"""Run Task 6b latency acceptance harness (writes docs/acceptance/evidence JSON).

  $env:PYTHONPATH='apps/api'
  $env:LLM_PROVIDER='fake'
  .\\.venv-clean\\Scripts\\python.exe scripts/measure_realtime_latency.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    py = ROOT / ".venv-clean" / "Scripts" / "python.exe"
    exe = str(py if py.exists() else sys.executable)
    cmd = [
        exe,
        "-m",
        "pytest",
        "-c",
        "apps/api/pyproject.toml",
        "apps/api/tests/test_realtime_latency_measure.py",
        "-q",
        "--tb=short",
    ]
    env = dict(**{k: v for k, v in __import__("os").environ.items()})
    env["PYTHONPATH"] = str(ROOT / "apps" / "api")
    env.setdefault("LLM_PROVIDER", "fake")
    raise SystemExit(subprocess.call(cmd, cwd=str(ROOT), env=env))


if __name__ == "__main__":
    main()
