# Gunakan base image Python slim
FROM python:3.11-slim-bookworm


# Set direktori kerja
WORKDIR /app

# Install dependency OS untuk Pillow dan QRCode jika diperlukan
RUN apt-get update && apt-get install -y \
    libjpeg-dev zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY app/requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy seluruh source code ke container
COPY app /app

# ===== FIX: Buat folder uploads & beri izin write =====
RUN mkdir -p /app/uploads && chmod 777 /app/uploads
# ======================================================

# Expose port Flask
EXPOSE 5001

# Jalankan Flask
ENV FLASK_APP=app.py
ENV FLASK_RUN_HOST=0.0.0.0
ENV FLASK_RUN_PORT=5001
ENV PYTHONUNBUFFERED=1

CMD ["flask", "run"]
