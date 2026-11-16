# Consola web de Reachy Mini (FastAPI + WebSocket + voz/visión/escritura)
#
# Desplegable como Space Docker de Hugging Face (usa el puerto 7860).

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    REACHY_HOST=0.0.0.0 \
    REACHY_PORT=7860 \
    HF_HOME=/tmp/hf

# ffmpeg: conversión de audio (edge-tts/ASR) · libgomp1: onnxruntime (Piper)
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg libgomp1 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements-docker.txt .
RUN pip install --no-cache-dir -r requirements-docker.txt

COPY . .

EXPOSE 7860

# uvicorn escucha en 0.0.0.0:7860 (HF Spaces lo detecta por app_port)
CMD ["python", "-u", "server.py"]
