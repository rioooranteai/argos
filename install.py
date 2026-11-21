"""
ArgosAI dependency installer with automatic GPU detection.

Usage (run it with the python of your venv/project):
    python install.py              # auto: detect an NVIDIA GPU
    python install.py --device cpu # force the CPU build
    python install.py --device cuda

What it does:
  1. Checks for an NVIDIA GPU (via `nvidia-smi`).
  2. Installs the CUDA build of PyTorch (with a GPU) or the CPU build.
  3. Installs the remaining dependencies from requirements.txt.
  4. Verifies: shows whether torch can see the GPU.
"""

from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path

TORCH_VERSION = "2.8.0"
TORCHVISION_VERSION = "0.23.0"
CUDA_TAG = "cu129"  # needs an NVIDIA driver that supports CUDA 12.9 (>= 576.x)
INDEX_BASE = "https://download.pytorch.org/whl"
ROOT = Path(__file__).resolve().parent


def detect_nvidia_gpu() -> str | None:
    """Return the NVIDIA GPU name if there is one, otherwise None."""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        out = subprocess.run(
            [exe, "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    name = out.stdout.strip().splitlines()[0] if out.returncode == 0 and out.stdout.strip() else None
    return name


def pip(*args: str) -> None:
    cmd = [sys.executable, "-m", "pip", *args]
    print(f"\n$ {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--device", choices=["auto", "cuda", "cpu"], default="auto")
    args = parser.parse_args()

    if not ((3, 11) <= sys.version_info[:2] <= (3, 13)):
        print(f"Python {platform.python_version()} is not supported. Use Python 3.11 - 3.13.")
        return 1

    if platform.system() == "Darwin" and platform.machine() == "x86_64":
        print("Intel Macs are not supported by this PyTorch version. Run it with Docker (see README).")
        return 1

    if sys.prefix == sys.base_prefix:
        print("WARNING: you are not in a virtual environment. "
              "Packages will be installed into the global Python.")

    env_file, env_example = ROOT / ".env", ROOT / ".env.example"
    if not env_file.exists() and env_example.exists():
        shutil.copyfile(env_example, env_file)
        print("Created .env from .env.example — put your API keys there.")

    device = args.device
    if device == "auto":
        gpu = detect_nvidia_gpu()
        if gpu:
            print(f"NVIDIA GPU detected: {gpu} -> installing PyTorch {CUDA_TAG}")
            device = "cuda"
        else:
            print("No NVIDIA GPU detected -> installing the CPU build of PyTorch")
            device = "cpu"

    pip("install", "--upgrade", "pip")

    torch_pkgs = [f"torch=={TORCH_VERSION}", f"torchvision=={TORCHVISION_VERSION}"]
    if platform.system() == "Darwin":
        # macOS: the regular PyPI wheel (already includes MPS / Apple Silicon support)
        pip("install", *torch_pkgs)
    else:
        tag = CUDA_TAG if device == "cuda" else "cpu"
        pip("install", *torch_pkgs, "--index-url", f"{INDEX_BASE}/{tag}")

    pip("install", "-r", str(ROOT / "requirements.txt"))

    print("\n=== Verification ===")
    check = subprocess.run([
        sys.executable, "-c",
        "import torch, docling, fastapi; ok = torch.cuda.is_available(); "
        "print('torch', torch.__version__, '| CUDA available:', ok, "
        "'|', torch.cuda.get_device_name(0) if ok else 'CPU'); "
        "raise SystemExit(0 if ok else 3)",
    ], check=False)
    if check.returncode not in (0, 3):
        print("Verification failed: the core packages cannot be imported.")
        return 1
    if device == "cuda" and check.returncode == 3:
        print("WARNING: CUDA PyTorch is installed but the GPU is not visible "
              "(the NVIDIA driver may be too old). The app still runs on CPU. "
              "Update the driver, or run: python install.py --device cpu")

    print("\nDone. Start the app:  python -m uvicorn app.main:app --reload")
    print("The Docling device is set by the DOCLING_DEVICE environment variable (auto/cuda/cpu), default 'auto'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
