# V-Check AICTE (independent demonstration prototype). Builds a single container: API + web UI + Tesseract OCR.
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY . .
ENV API_HOST=0.0.0.0 STORAGE_DIR=/app/storage SEED_DEMO=1
WORKDIR /app/backend
EXPOSE 8000
CMD ["python", "-m", "vcheck_api"]
