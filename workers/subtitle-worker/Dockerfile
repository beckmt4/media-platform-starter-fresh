FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml .
# Install runtime deps including faster-whisper
RUN pip install --no-cache-dir \
    "fastapi>=0.111" \
    "pydantic>=2.7" \
    "uvicorn[standard]>=0.29" \
    "faster-whisper>=1.0"

COPY subtitle_worker/ subtitle_worker/

# Whisper model cache — mount a host path here to avoid re-downloading models
ENV HF_HOME=/models

EXPOSE 8004

CMD ["uvicorn", "subtitle_worker.main:app", "--host", "0.0.0.0", "--port", "8004"]
