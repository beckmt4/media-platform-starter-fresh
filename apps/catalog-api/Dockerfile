FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir "fastapi>=0.111" "pydantic>=2.7" "uvicorn[standard]>=0.29"

COPY catalog_api/ catalog_api/

ENV CATALOG_DB_PATH=/data/catalog.db

EXPOSE 8000

CMD ["uvicorn", "catalog_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
