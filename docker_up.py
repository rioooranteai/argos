"""
Jalankan Docker Compose dengan deteksi GPU otomatis.

Cara pakai:
    python docker_up.py                 # auto: GPU kalau ada, kalau tidak CPU
    python docker_up.py --device cpu    # paksa CPU
    python docker_up.py --device cuda   # paksa GPU
    python docker_up.py -- logs -f      # perintah compose lain (default: up -d --build)

Pilihan file:
    CPU -> docker-compose.yml
    GPU -> docker-compose.yml + docker-compose.gpu.yml
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from install import detect_nvidia_gpu

ROOT = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--device", choices=["auto", "cuda", "cpu"], default="auto")
    parser.add_argument("compose_args", nargs="*", help="argumen untuk docker compose (setelah --)")
    args = parser.parse_args()

    if not shutil.which("docker"):
        print("Docker tidak ditemukan. Install / jalankan Docker Desktop dulu.")
        return 1

    device = args.device
    if device == "auto":
        gpu = detect_nvidia_gpu()
        device = "cuda" if gpu else "cpu"
        print(f"GPU terdeteksi: {gpu}" if gpu else "GPU NVIDIA tidak terdeteksi.")
    print(f"Mode Docker: {device.upper()}")

    files = ["-f", str(ROOT / "docker-compose.yml")]
    if device == "cuda":
        files += ["-f", str(ROOT / "docker-compose.gpu.yml")]

    compose_args = args.compose_args or ["up", "-d", "--build"]
    cmd = ["docker", "compose", *files, *compose_args]
    print("$", " ".join(cmd))
    return subprocess.run(cmd, cwd=ROOT).returncode


if __name__ == "__main__":
    sys.exit(main())
