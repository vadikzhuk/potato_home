# Your own Telegram bots

This folder runs your own bots (not the home bot, which is `services/bot`) on the server,
next to the home services. Each bot keeps its code in its own GitHub repository;
[`compose.yml`](compose.yml) only says which bots run and how. The **botwatch** service
watches them all (see the main README, "Your own Telegram bots").

| File | What |
|---|---|
| `compose.yml` | one entry per bot. `docker-compose.yml` includes it, so `docker compose up -d`, `ps` and `logs` cover the bots too. |
| `botstats.py` | the usage counter to copy into a bot (optional, python-telegram-bot only) |

Every bot gets:
- **its own container**, started again after a crash and after the server restarts
- **a memory limit** of 256 MB (`mem_limit`), so one bot can't take the server's memory
- **only its own token** from `.env`, never the other secrets
- **its own network:** it reaches the internet and botwatch, but not the home services or Docker
- **log rotation:** at most 3 files of 10 MB

## Adding a bot

### 1. Make the bot ready (in its repository)

- **Token from the environment**, never written in the code: `os.environ["BOT_TOKEN"]`.
  The repositories are public.
- **Long polling**, not a webhook. The server has no public address. In python-telegram-bot:
  `app.run_polling()`; in pyTelegramBotAPI: `bot.infinity_polling()`.
- **A `requirements.txt`** with the libraries, their versions pinned.
- **A `Dockerfile`.** For a single-file Python bot:
  ```dockerfile
  FROM python:3.11-slim
  WORKDIR /app
  COPY requirements.txt ./
  RUN pip install --no-cache-dir -r requirements.txt
  COPY *.py ./
  ENV PYTHONUNBUFFERED=1
  CMD ["python", "my_bot.py"]
  ```
  `PYTHONUNBUFFERED=1` makes its log lines appear at once.
- **Quiet httpx** (python-telegram-bot): `logging.getLogger("httpx").setLevel(logging.WARNING)`.
  Otherwise every request is logged with its full address, **token included**.
- **Optional, usage counts:** copy `botstats.py` next to the bot and call `track(app)` right
  after building the application (see the top of `botstats.py`).

Push it to GitHub.

### 2. Add it here

In `compose.yml`, copy the `digital_gland_bot` entry and change three things: the name,
the repository, and the token variable:

```yaml
  quiz_bot:
    <<: *bot
    build: https://github.com/vadikzhuk/quiz_bot.git#main
    environment:
      <<: *bot-env
      BOT_TOKEN: ${QUIZ_BOT_TOKEN:-}
```

A bot that needs more settings (an API key, say) gets them the same way: a line under
`environment:` here, the value in `.env`.

### 3. Put the token into `.env` on the server

```
QUIZ_BOT_TOKEN=123456789:AA...
```

### 4. Start it

**If the bot runs somewhere else now (Railway…), stop it there first.** Two copies with one
token fight over the messages (`409 Conflict` in the log).

```bash
cd ~/Dev/potato_home
git pull                                 # if you edited compose.yml elsewhere
docker compose up -d --build quiz_bot
docker compose logs -f quiz_bot          # Ctrl+C to stop watching
```

Within a minute, botwatch admins get "👀 Watching a new bot" in the home bot, and
`/bots` lists it.

## Updating a bot

Push the change to its repository, then on the server:

```bash
docker compose build quiz_bot && docker compose up -d quiz_bot
```

The build fetches the latest commit of the branch after `#` (`main`). To try local
changes before pushing, point `build:` at a local clone for a while, e.g. `build: ../../quiz_bot`
for `~/Dev/quiz_bot` (paths in this file start from `bots/`).

## Moving a bot from Railway

1. Make the bot ready (step 1 above). Bots on Railway often use a `Procfile` or
   `nixpacks.toml`: the Dockerfile replaces them here. You can leave them in the repository.
2. Webhook bots: switch to polling. python-telegram-bot's `run_polling()` removes the
   webhook by itself; other libraries may need `deleteWebhook`. botwatch reports a
   webhook that is still set.
3. **Stop the Railway service**, or remove it, so only one copy runs.
4. Steps 2–4 above.
5. Data: these bots keep nothing between restarts, so there is nothing to move.
   A bot with a database needs a folder in `data/` mounted into its container:
   `volumes: - ../data/quiz_bot:/data` (paths in this file start from `bots/`).

## Removing a bot

Delete its entry from `compose.yml` and its token from `.env`, then:

```bash
docker compose up -d --remove-orphans
```

botwatch stops listing it after 15 minutes. Its usage history stays for a year.

## When something is wrong

| You see | What it means, what to do |
|---|---|
| 🔴 keeps crashing | it fails on start. `docker compose logs --tail 50 quiz_bot` shows why (often the token) |
| 🔴 Telegram rejects the token | revoked or mistyped: a new one from @BotFather into `.env`, then `docker compose up -d quiz_bot` |
| 🔴 stuck: messages have waited | it runs but doesn't read messages: `docker compose restart quiz_bot`, then look at its log |
| 🔴 a webhook is set | left from hosting elsewhere. Stop it there. Restarting a python-telegram-bot bot removes it |
| 🔴 close to its memory limit | raise `mem_limit` for it in `compose.yml`, or look for a leak |
| 🔁 crashed and Docker restarted it | it recovered by itself; the alert shows the last error |
| `409 Conflict` in its log | another copy runs with the same token: Railway, or your laptop |
| `/bots` shows no usage | the bot doesn't call `track(app)`, or it isn't python-telegram-bot |
