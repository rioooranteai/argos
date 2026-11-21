"""
Run Docker Compose with automatic GPU detection.

Usage:
    python docker_up.py                 # auto: GPU if there is one, otherwise CPU
    python docker_up.py --device cpu    # force CPU
    python docker_up.py --device cuda   # force GPU
    python docker_up.py -- logs -f      # any other compose command (default: up -d --build)

Compose files:
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
    parser.add_argument("compose_args", nargs="*", help="arguments for docker compose (after --)")
    args = parser.parse_args()

    if not shutil.which("docker"):
        print("Docker not found. Install / start Docker Desktop first.")
        return 1

    device = args.device
    if device == "auto":
        gpu = detect_nvidia_gpu()
        device = "cuda" if gpu else "cpu"
        print(f"GPU detected: {gpu}" if gpu else "No NVIDIA GPU detected.", flush=True)
    print(f"Docker mode: {device.upper()}", flush=True)

    files = ["-f", str(ROOT / "docker-compose.yml")]
    if device == "cuda":
        files += ["-f", str(ROOT / "docker-compose.gpu.yml")]

    compose_args = args.compose_args or ["up", "-d", "--build"]
    cmd = ["docker", "compose", *files, *compose_args]
    print("$", " ".join(cmd), flush=True)
    return subprocess.run(cmd, cwd=ROOT).returncode


if __name__ == "__main__":
    sys.exit(main())
