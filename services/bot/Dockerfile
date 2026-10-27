FROM python:3.11-slim

WORKDIR /app
COPY pyproject.toml ./
COPY bot ./bot
RUN pip install --no-cache-dir .

ENV BOT_STATE=/data/state.json \
    PYTHONUNBUFFERED=1

CMD ["python", "-m", "bot.main"]
