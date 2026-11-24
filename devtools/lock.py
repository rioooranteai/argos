"""
Regenerate requirements.txt — the one file people and the Dockerfile install — from the direct
dependencies in pyproject.toml.

Needs uv: https://docs.astral.sh/uv/   ->   python devtools/lock.py

- Cross-platform (--universal): the same file for Windows, Linux and macOS.
- Every package is pinned, PyTorch included. The file starts with the PyTorch CPU index as an
  extra index, so a plain `pip install -r requirements.txt` gets the CPU build (2.8.0+cpu ranks
  above the PyPI 2.8.0). The CUDA build: add `--extra-index-url https://download.pytorch.org/whl/cu129`
  (2.8.0+cu129 ranks higher still).
- triton and nvidia-* are left out: only the PyPI/CUDA builds of PyTorch need them, and those
  builds bring them along.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCK = ROOT / "requirements.txt"
TORCH_CPU_INDEX = "https://download.pytorch.org/whl/cpu"
EXCLUDE = re.compile(r"^(triton|nvidia-[\w-]+)==", re.IGNORECASE)
HEADER = (
    "# ArgosAI — every package the app needs, pinned. Install: pip install -r requirements.txt\n"
    "# NVIDIA GPU: add  --extra-index-url https://download.pytorch.org/whl/cu129\n"
    "# Do not edit by hand: change pyproject.toml and run  python devtools/lock.py\n"
    f"--extra-index-url {TORCH_CPU_INDEX}\n"
)


def main() -> int:
    uv = shutil.which("uv")
    if not uv:
        print("uv not found. Install it: https://docs.astral.sh/uv/getting-started/installation/")
        return 1

    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / "lock.txt"
        cmd = [
            uv, "pip", "compile", str(ROOT / "pyproject.toml"),
            "--universal", "--python-version", "3.11",
            "-o", str(raw), "--no-annotate", "--no-header", "-q",
        ]
        # Keep the tested versions when they still satisfy pyproject.toml (pins only, no options)
        if LOCK.exists():
            pins = Path(tmp) / "pins.txt"
            pins.write_text("\n".join(ln for ln in LOCK.read_text(encoding="utf-8").splitlines()
                                      if ln and not ln.startswith(("#", "-"))), encoding="utf-8")
            cmd += ["-c", str(pins)]
        subprocess.run(cmd, check=True)

        lines = [ln for ln in raw.read_text(encoding="utf-8").splitlines() if not EXCLUDE.match(ln)]

    LOCK.write_text(HEADER + "\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"requirements.txt updated ({len(lines)} packages).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
