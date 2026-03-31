FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir "fastapi>=0.111" "pydantic>=2.7" "uvicorn[standard]>=0.29"

COPY jav_normalizer/ jav_normalizer/

EXPOSE 8003

CMD ["uvicorn", "jav_normalizer.main:app", "--host", "0.0.0.0", "--port", "8003"]
