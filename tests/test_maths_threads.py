"""The app asks numpy's maths library (OpenBLAS) for one thread before numpy loads:
it would start one per processor, and set memory aside for each, for nothing."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _run(code: str, **env) -> str:
    e = {k: v for k, v in os.environ.items() if k != "OPENBLAS_NUM_THREADS"}
    e.update(env, QT_QPA_PLATFORM="offscreen")
    return subprocess.run([sys.executable, "-c", code], check=True, env=e, cwd=ROOT,
                          capture_output=True, text=True, timeout=120).stdout.strip()


def test_the_app_sets_one_maths_thread_before_numpy_loads():
    out = _run("import sys, os\n"
               "import onionwatch.app\n"
               "print('numpy' in sys.modules, os.environ.get('OPENBLAS_NUM_THREADS'))")
    assert out == "False 1"


def test_a_maths_thread_count_given_by_the_user_is_kept():
    out = _run("import os, onionwatch.app\nprint(os.environ['OPENBLAS_NUM_THREADS'])",
               OPENBLAS_NUM_THREADS="4")
    assert out == "4"
