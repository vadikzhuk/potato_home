FROM python:3.11-slim

WORKDIR /app
COPY pyproject.toml ./
COPY screen ./screen
RUN pip install --no-cache-dir .
COPY config.yaml ./

ENV SCREEN_CONFIG=/app/config.yaml \
    PYTHONUNBUFFERED=1

EXPOSE 8000
CMD ["uvicorn", "screen.main:app", "--host", "0.0.0.0", "--port", "8000"]
