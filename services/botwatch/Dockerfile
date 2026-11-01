FROM python:3.11-slim

WORKDIR /app
COPY pyproject.toml ./
COPY botwatch ./botwatch
RUN pip install --no-cache-dir .

ENV BOTWATCH_DB=/data/botwatch.db \
    BOTWATCH_SETTINGS=/app/settings.yaml \
    PYTHONUNBUFFERED=1

EXPOSE 8000
CMD ["uvicorn", "botwatch.api:app", "--host", "0.0.0.0", "--port", "8000"]
