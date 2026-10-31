FROM python:3.11-slim

WORKDIR /app
COPY pyproject.toml ./
COPY estate ./estate
RUN pip install --no-cache-dir .

ENV ESTATE_DB=/data/estate.db \
    ESTATE_CRITERIA=/app/criteria.yaml \
    PYTHONUNBUFFERED=1

EXPOSE 8000
CMD ["uvicorn", "estate.api:app", "--host", "0.0.0.0", "--port", "8000"]
