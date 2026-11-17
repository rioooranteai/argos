"""
Installer dependency ArgosAI dengan deteksi GPU otomatis.

Cara pakai (jalankan dengan python dari venv/project Anda):
    python install.py              # auto: deteksi GPU NVIDIA
    python install.py --device cpu # paksa versi CPU
    python install.py --device cuda

Yang dilakukan:
  1. Cek apakah ada GPU NVIDIA (lewat `nvidia-smi`).
  2. Pasang PyTorch versi CUDA (kalau ada GPU) atau versi CPU.
  3. Pasang sisa dependency dari requirements.txt.
  4. Verifikasi: tampilkan apakah torch bisa melihat GPU.
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
CUDA_TAG = "cu129"  # butuh driver NVIDIA yang mendukung CUDA 12.9 (>= 576.x)
INDEX_BASE = "https://download.pytorch.org/whl"
ROOT = Path(__file__).resolve().parent


def detect_nvidia_gpu() -> str | None:
    """Kembalikan nama GPU NVIDIA kalau ada, selain itu None."""
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
        print(f"Python {platform.python_version()} tidak didukung. Pakai Python 3.11 - 3.13.")
        return 1

    if platform.system() == "Darwin" and platform.machine() == "x86_64":
        print("Mac Intel tidak didukung PyTorch versi ini. Jalankan lewat Docker (lihat README).")
        return 1

    if sys.prefix == sys.base_prefix:
        print("PERINGATAN: Anda tidak sedang di virtual environment. "
              "Paket akan dipasang ke Python global.")

    env_file, env_example = ROOT / ".env", ROOT / ".env.example"
    if not env_file.exists() and env_example.exists():
        shutil.copyfile(env_example, env_file)
        print("File .env dibuat dari .env.example — isi API key Anda di sana.")

    device = args.device
    if device == "auto":
        gpu = detect_nvidia_gpu()
        if gpu:
            print(f"GPU NVIDIA terdeteksi: {gpu} -> pasang PyTorch {CUDA_TAG}")
            device = "cuda"
        else:
            print("GPU NVIDIA tidak terdeteksi -> pasang PyTorch versi CPU")
            device = "cpu"

    pip("install", "--upgrade", "pip")

    torch_pkgs = [f"torch=={TORCH_VERSION}", f"torchvision=={TORCHVISION_VERSION}"]
    if platform.system() == "Darwin":
        # macOS: wheel PyPI biasa (sudah termasuk dukungan MPS / Apple Silicon)
        pip("install", *torch_pkgs)
    else:
        tag = CUDA_TAG if device == "cuda" else "cpu"
        pip("install", *torch_pkgs, "--index-url", f"{INDEX_BASE}/{tag}")

    pip("install", "-r", str(ROOT / "requirements.txt"))

    print("\n=== Verifikasi ===")
    check = subprocess.run([
        sys.executable, "-c",
        "import torch, docling, fastapi; ok = torch.cuda.is_available(); "
        "print('torch', torch.__version__, '| CUDA tersedia:', ok, "
        "'|', torch.cuda.get_device_name(0) if ok else 'CPU'); "
        "raise SystemExit(0 if ok else 3)",
    ], check=False)
    if check.returncode not in (0, 3):
        print("Verifikasi gagal: paket inti tidak bisa di-import.")
        return 1
    if device == "cuda" and check.returncode == 3:
        print("PERINGATAN: PyTorch CUDA terpasang tapi GPU tidak terbaca "
              "(driver NVIDIA mungkin terlalu lama). Aplikasi tetap jalan di CPU. "
              "Update driver, atau jalankan: python install.py --device cpu")

    print("\nSelesai. Jalankan aplikasi:  python -m uvicorn app.main:app --reload")
    print("Device Docling diatur lewat DOCLING_DEVICE di .env (auto/cuda/cpu), default 'auto'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
