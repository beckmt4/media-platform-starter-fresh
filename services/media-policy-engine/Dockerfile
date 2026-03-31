FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir "fastapi>=0.111" "pydantic>=2.7" "pyyaml>=6.0" "uvicorn[standard]>=0.29"

COPY media_policy_engine/ media_policy_engine/

EXPOSE 8001

CMD ["uvicorn", "media_policy_engine.main:app", "--host", "0.0.0.0", "--port", "8001"]
