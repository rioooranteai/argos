FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# System libraries:
#  - build-essential : compiles packages that have no wheel yet
#  - libgl1, libglib2.0-0 : needed by OpenCV (used by Docling for OCR/layout)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        sqlite3 \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# PyTorch variant: "cpu" (default, smaller image) or "cu129" (NVIDIA GPU)
ARG TORCH_INDEX=cpu

COPY requirements.txt .

# PyTorch first for the chosen variant, then the other Python libraries
RUN pip install --upgrade pip && \
    pip install --no-cache-dir torch==2.8.0 torchvision==0.23.0 \
        --index-url https://download.pytorch.org/whl/${TORCH_INDEX} && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p data

EXPOSE 8000

# MUST be a single process: the document queue worker runs inside the app, and the Chroma
# PersistentClient is not safe across processes (DESIGN_GROUP_B.md §3.4).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
