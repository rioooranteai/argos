# Gunakan image Python yang ringan
FROM python:3.11-slim

# Set direktori kerja di dalam container
WORKDIR /app

# Install system dependencies (kadang dibutuhkan oleh ChromaDB/SQLite)
RUN apt-get update && apt-get install -y \
    build-essential \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Copy file requirements.txt
COPY requirements.txt .

# Install library Python
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy seluruh kode project ke dalam container
COPY . .

# Buat folder sementara untuk upload di dalam container
RUN mkdir -p temp_uploads

# Buka port 8000
EXPOSE 8000

# Jalankan FastAPI di host 0.0.0.0 agar bisa diakses dari luar container
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]