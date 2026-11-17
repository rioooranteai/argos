FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Library sistem:
#  - build-essential : compile paket yang belum punya wheel
#  - libgl1, libglib2.0-0 : dibutuhkan OpenCV (dipakai Docling untuk OCR/layout)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        sqlite3 \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Varian PyTorch: "cpu" (default, image lebih kecil) atau "cu129" (GPU NVIDIA)
ARG TORCH_INDEX=cpu

COPY requirements.txt .

# PyTorch dulu sesuai varian, lalu sisa library Python
RUN pip install --upgrade pip && \
    pip install --no-cache-dir torch==2.8.0 torchvision==0.23.0 \
        --index-url https://download.pytorch.org/whl/${TORCH_INDEX} && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p temp_uploads data

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
