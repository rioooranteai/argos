"""
Generate ulang requirements.txt (lock file) dari requirements.in.

Butuh uv: https://docs.astral.sh/uv/   ->   python lock.py

- Lock bersifat lintas platform (--universal), jadi sama untuk Windows/Linux/Mac.
- Diresolve terhadap torch==2.8.0, tapi torch/torchvision/triton/nvidia-* dibuang
  dari hasil karena dipasang terpisah oleh install.py / Dockerfile (CPU atau CUDA).
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
    "# LOCK FILE — jangan diedit manual. Generate ulang dengan: python lock.py\n"
    "# PyTorch tidak ada di sini: dipasang oleh install.py / Dockerfile (CPU atau CUDA).\n"
)


def main() -> int:
    uv = shutil.which("uv")
    if not uv:
        print("uv tidak ditemukan. Install: https://docs.astral.sh/uv/getting-started/installation/")
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
        # Pertahankan versi yang sudah teruji kalau masih memenuhi requirements.in
        if (ROOT / "requirements.txt").exists():
            cmd += ["-c", str(ROOT / "requirements.txt")]
        subprocess.run(cmd, check=True)

        lines = [ln for ln in raw.read_text(encoding="utf-8").splitlines() if not EXCLUDE.match(ln)]

    (ROOT / "requirements.txt").write_text(HEADER + "\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"requirements.txt diperbarui ({len(lines)} paket).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
