FROM python:3.11-slim

WORKDIR /app
COPY pyproject.toml ./
COPY users ./users
RUN pip install --no-cache-dir .
COPY users.yaml ./

ENV USERS_DB=/data/users.db \
    USERS_SEED=/app/users.yaml \
    PYTHONUNBUFFERED=1

EXPOSE 8000
CMD ["uvicorn", "users.api:app", "--host", "0.0.0.0", "--port", "8000"]
