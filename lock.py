"""
Regenerate requirements.txt (the lock file) from requirements.in.

Needs uv: https://docs.astral.sh/uv/   ->   python lock.py

- The lock is cross-platform (--universal), so it is the same on Windows/Linux/Mac.
- Resolved against torch==2.8.0, but torch/torchvision/triton/nvidia-* are dropped
  from the result because install.py / Dockerfile install them separately (CPU or CUDA).
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TORCH_PINS = "torch==2.8.0\ntorchvision==0.23.0\n"
EXCLUDE = re.compile(r"^(torch|torchvision|triton|nvidia-[\w-]+)==", re.IGNORECASE)
HEADER = (
    "# LOCK FILE — do not edit by hand. Regenerate with: python lock.py\n"
    "# PyTorch is not listed here: install.py / Dockerfile install it (CPU or CUDA).\n"
)


def main() -> int:
    uv = shutil.which("uv")
    if not uv:
        print("uv not found. Install it: https://docs.astral.sh/uv/getting-started/installation/")
        return 1

    with tempfile.TemporaryDirectory() as tmp:
        torch_c = Path(tmp) / "torch.txt"
        raw = Path(tmp) / "lock.txt"
        torch_c.write_text(TORCH_PINS, encoding="utf-8")
        cmd = [
            uv, "pip", "compile", str(ROOT / "requirements.in"),
            "--universal", "--python-version", "3.11",
            "-c", str(torch_c), "-o", str(raw),
            "--no-annotate", "--no-header", "-q",
        ]
        # Keep the tested versions when they still satisfy requirements.in
        if (ROOT / "requirements.txt").exists():
            cmd += ["-c", str(ROOT / "requirements.txt")]
        subprocess.run(cmd, check=True)

        lines = [ln for ln in raw.read_text(encoding="utf-8").splitlines() if not EXCLUDE.match(ln)]

    (ROOT / "requirements.txt").write_text(HEADER + "\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"requirements.txt updated ({len(lines)} packages).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
