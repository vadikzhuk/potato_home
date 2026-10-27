FROM python:3.11-slim

WORKDIR /app
COPY pyproject.toml ./
COPY tickets ./tickets
RUN pip install --no-cache-dir .

ENV TICKETS_DB=/data/tickets.db \
    PYTHONUNBUFFERED=1

EXPOSE 8000
CMD ["uvicorn", "tickets.api:app", "--host", "0.0.0.0", "--port", "8000"]
