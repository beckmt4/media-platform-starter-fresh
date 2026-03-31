FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    mediainfo \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir "fastapi>=0.111" "pydantic>=2.7" "uvicorn[standard]>=0.29"

COPY subtitle_intel/ subtitle_intel/

EXPOSE 8002

CMD ["uvicorn", "subtitle_intel.main:app", "--host", "0.0.0.0", "--port", "8002"]
