FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    mkvtoolnix \
    mediainfo \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir \
    "fastapi>=0.111" \
    "pydantic>=2.7" \
    "uvicorn[standard]>=0.29"

COPY transcode_worker/ transcode_worker/

EXPOSE 8005

CMD ["uvicorn", "transcode_worker.main:app", "--host", "0.0.0.0", "--port", "8005"]
