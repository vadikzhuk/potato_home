# potato_home

Small home services, each in its own folder and container, talking over HTTP.

| Service | What it does | Port |
|---|---|---|
| `users` | people and their access to every service | 8002 (this machine only) |
| `tickets` | home ticket tracker: tickets and their full history | 8001 (this machine only) |
| `estate` | cheap houses and apartments in Italy: found daily, ranked, sent as a digest | 8003 (this machine only) |
| `screen` | 16:9 info screen for the TV: today's weather, homes in Italy, news, health, tickets | 8080 |
| `bot` | Telegram bot for all services | none (long polling) |

```
potato_home/
├── docker-compose.yml    # which services run and how
├── .env                  # secrets (copy from .env.example, never committed)
├── data/<service>/       # each service's data, mounted into its container (never committed)
├── scripts/              # one-time maintenance scripts
└── services/<name>/      # one folder per service, with its own Dockerfile
```

```
bot ──► users   (who is this? what may they do?)
 ├────► tickets ──► users (access levels, names)
 └────► estate  ──► users (access levels)
                └─► trovacasa.it, pvp.giustizia.it (once a day)
screen ──► tickets, estate
```

## First start

On a new machine (Arch Linux, Raspberry Pi OS 64-bit, Debian/Ubuntu or macOS):
**see [SETUP.md](SETUP.md)**. In short:

```bash
git clone <this repository> ~/potato_home && cd ~/potato_home
./setup.sh            # installs Docker if needed, creates .env, builds and starts everything
./setup.sh --check    # later: is everything installed, configured and answering?
```

By hand, on a machine that already has Docker:

```bash
cp .env.example .env      # then put a random string into API_TOKEN
docker compose up -d --build
```

On the first start the users service creates the users from
`services/users/users.yaml`. Edit that file before the first start if you like.

## Everyday commands

```bash
docker compose ps                      # what is running
docker compose logs -f tickets         # follow a service's log
docker compose restart tickets         # restart one service
docker compose up -d --build tickets   # apply code changes to one service
docker compose stop                    # stop everything
```

Short aliases for the terminal tools, which run inside the containers. Add them to
`~/.zshrc` (macOS) or `~/.bashrc` (Linux) so every new terminal has them, and change the
path if you cloned somewhere other than `~/potato_home`:

```bash
alias dc="docker compose -f ~/potato_home/docker-compose.yml"
alias users="dc exec users users"
alias tk="dc exec tickets tickets"
alias estate="dc exec estate estate"
```

The `users` alias hides the system's own `users` command (which lists logged-in users).
If a command prints just `usage: users`, the alias isn't defined in that terminal.

## Users and access

Every person has one **access level per service**: `read`, `write` or `admin`. Each level
includes the ones before it. No level means no access. Each service decides what the
levels mean for it:

| Level | tickets | estate | users |
|---|---|---|---|
| read | see all tickets | see listings, get the daily digest | see the user list |
| write | create tickets; change ones you created or are assigned to; get tickets assigned | star and hide listings | — |
| admin | change any ticket; morning list of late unassigned tickets | start a fetch by hand | add/change users, grant and revoke access |

```bash
users list --all                     # everyone and their access
users add Anna --telegram-id 123456  # new users start without any access
users grant Anna tickets write
users revoke Anna tickets
users edit Anna --name "Anna Maria" --telegram-id 654321
users deactivate Anna                # users are never deleted, only deactivated
users export                         # write everyone to services/users/users.yaml
users import                         # apply your edits of users.yaml
```

The very first user becomes users admin automatically. The last users admin can't be
removed or deactivated, so somebody can always manage access.

A new service gets access rows just by using its name: `users grant Anna garden write`.
No changes to the users service are needed.

## Tickets from the terminal

```bash
tk list                                   # active tickets (--all, --mine, --assignee NAME)
tk new "Fix kitchen tap" -d "Drips" --due tomorrow --assign anna
tk show 12                                # details + full history
tk assign 12 alex                         # assign / reassign
tk start 12 | tk done 12 | tk cancel 12 | tk reopen 12
tk edit 12 --title "..." --due +3         # or --no-due
tk --as anna done 12                      # act as someone else (default: first tickets admin)
```

Due dates accept `2026-11-05`, `today`, `tomorrow` or `+N` days. Nothing is deleted:
"removing" a ticket means cancelling it, and every change is recorded in its history.

## Homes in Italy (estate)

Every day the estate service reads cheap homes for sale from two sites, keeps them
all (with every price they ever had), and ranks the ones that match
[`services/estate/criteria.yaml`](services/estate/criteria.yaml). When it's done, the bot
sends everyone with estate access the best new ones.

**Sources** (only sites that answer a plain, polite request; most big portals block them):

| Site | What | How |
|---|---|---|
| [Trovacasa](https://www.trovacasa.it) | agencies and private sellers, court auctions too | its search pages, province by province, newest first, ~400 pages a day with a pause between them |
| [PVP](https://pvp.giustizia.it) | Italy's official list of court auctions (every one must be published there) | the JSON API its own page uses |

Subito, Idealista, Immobiliare, Casa.it, Gate-away and Kyero block automated requests,
so they aren't used. Green-Acres answers, but has almost nothing under 30 000 €.

**How a listing gets into the digest:**
1. **Fetch** at `fetch.time` (default 05:00; a machine that was off catches up when it
   starts). A full fetch of all four regions takes about 15 minutes.
2. **One per property:** the same auction on both sites, or the same flat from two
   agencies, is shown once, with a link to each copy.
3. **Filter** by the `search` part: regions, price, bedrooms, kind, auctions, and
   `exclude_words` ("nuda proprietà", "quota indivisa"...: cheap for a reason you don't want).
4. **Score 0–100** with the `scoring` weights: price per m² compared with the province,
   price, condition words, extras (garden, terrace...), price drops, and how much the
   listing says (m², bedrooms, photo). `estate show 12` explains every listing's score.
5. **Digest:** the best `digest.top` new listings and `digest.auctions` new auctions with a
   score of at least `digest.min_score`, plus starred listings that got cheaper.

Good to know:
- **Bedrooms** are often not stated. Italian listings give *locali* (rooms including the
  living room), so 3 locali counts as ~2 bedrooms. A `~` marks such a guess.
- **Auction prices** are the lowest offer the court accepts (75% of the base price),
  as Trovacasa shows them. The base price is in the listing's details. "Occupied" auctions
  can take months to free.
- **Save `criteria.yaml` and it applies at once**, also to listings found earlier. Check
  your edits with `estate check`.

```bash
estate top                 # the best listings now (-n 30, --auctions, --no-auctions)
estate show 12             # everything about one listing, and why it scored what it did
estate star 12             # watch it: price drops come in the digest (unstar)
estate hide 12             # never show it again (unhide)
estate starred
estate check               # is criteria.yaml fine? how many listings does it let through?
estate fetch               # fetch now (--source pvp for one site)
estate runs                # the latest fetches: when, how many, errors
```

Hidden and starred are shared by everyone at home.

## APIs

Browse and try them on this machine: http://localhost:8002/docs (users),
http://localhost:8001/docs (tickets) and http://localhost:8003/docs (estate). Every request needs the header `X-Api-Token`
(from `.env`). Changes also need who is acting: `X-Telegram-Id` or `X-User-Id`.
Reading with those headers checks the person's read access. Reading without them is
a service asking, e.g. the screen.

Only a service's own container should touch its database in `data/<service>/`. Don't
open one from the host while the service is running; stop it first.

## Info screen

Open `http://<host>:8080` on the TV (full screen). The page reloads itself every minute.

- **Top left:** a strip with the clock and today's weather from [Open-Meteo](https://open-meteo.com):
  now, today's high / low and chance of rain
- **Homes in Italy:** the best listings now (`estate.count`, default 2), each with price,
  town, size, bedrooms, auction date, the start of its description, and a **QR code**:
  point a phone's camera at the TV to open the listing's page
- **Then:** trending news from [rus.lsm.lv/populjarnoe](https://rus.lsm.lv/populjarnoe/)
  (switches to the latest-news RSS feed if that page can't be read)
- **Lower left:** service health (see below)
- **Right:** active tickets, most urgent first; overdue in red, due today in orange

Settings (location, refresh times, how many items, which services to watch) are in
`services/screen/config.yaml`. After editing it, run `docker compose restart screen`.

**Service health.** Every 30 seconds the screen asks each of our services for
`GET /health`. Each row shows:

| Column | Meaning |
|---|---|
| ● | now: 🟢 ok · 🟡 slow (over `slow_ms`) · 🟠 warn (running, but something it needs isn't) · 🔴 down (no answer, error) |
| ms | how long the answer took |
| ●●●○● | the last 10 checks, so a service that keeps failing now and then stands out |
| detail | the problem, e.g. "can't connect", "no answer in 5 s", "Users service is not reachable", and since when |

What each service checks for its `/health`:
- **users:** its database answers.
- **tickets:** its database answers. It reports "degraded" if the users service doesn't
  answer, because then nobody can change tickets.
- **estate:** its database answers. It reports "degraded" if `criteria.yaml` is broken, the
  last fetch had errors or is more than two days old, or the users service doesn't answer.
- **bot:** once a minute it checks Telegram, users, tickets and estate, so it shows problems up to
  a minute late. It reports "degraded" if one of them fails, or if that check stopped running.

The last two rows are the outside websites. They show how long the last fetch took and
when it happened; the screen doesn't ask them extra. The 10-check history starts fresh
when the screen restarts.

To watch a new service: give it a `/health` endpoint and add it under `health.services`
in `config.yaml`.

Each panel's corner shows when its data was last refreshed. If a source fails, the
panel keeps its last data and that note turns red. http://localhost:8080/data shows
the raw data of every panel.

**OLED TVs:** a static page can burn into an OLED panel. Every few minutes the whole page
moves a few pixels to the next spot of a small 5×5 grid (`pixel_shift` in `config.yaml`;
`max_rem: 0` turns it off). Also leave the TV's own Pixel shift on and switch it off at night.

The layout is sized in screen widths, so any 16:9 resolution works (tested at 1920×1080
and 1280×720). It uses only old, widely supported CSS, so a TV's built-in browser
should cope. Otherwise, a Raspberry Pi with Chromium in kiosk mode works:
`chromium-browser --kiosk http://<host>:8080`.

## Telegram bot

The bot asks Telegram for new messages itself (long polling), so it needs no public
address or port forwarding.

**Setup (once):**
1. In Telegram, talk to [@BotFather](https://t.me/BotFather), send `/newbot`, pick a name.
   It gives you a token.
2. Put the token into `.env` as `TELEGRAM_TOKEN=...` and run `docker compose up -d bot`.
3. Write `/start` to your bot. It doesn't know you yet and replies with your Telegram id.
4. Connect your user to that id: `users edit admin --telegram-id <id>`
   (the first user is called `admin`; rename it with `users edit admin --name YourName`).
5. Add family members: they write `/start` to get their id. You send
   `/user_add Anna <id>` and `/user_grant Anna tickets write` in the bot.

**Commands:** named `/<service>_<action>`. `/help` shows only the services you have access to.

| Command | What it does |
|---|---|
| `/ticket` | menu with My / All tickets buttons |
| `/ticket 12` | ticket card with history and buttons: Start, Done, Cancel, Reopen, Assign |
| `/ticket_my`, `/ticket_all` | your / everyone's active tickets, with a button per ticket |
| `/ticket_new` | create a ticket step by step: title, details, assignee, due date (`/cancel` stops) |
| `/ticket_due 12 tomorrow` | set the due date (`today`, `tomorrow`, `+3`, `2026-11-05`, `-` to remove) |
| `/estate` | menu: best listings, best auctions, starred |
| `/estate 12` | listing card with its photo, score reasons, ⭐ Star / 🙈 Hide and links to the sites |
| `/estate_top`, `/estate_auctions`, `/estate_starred` | lists with a button per listing |
| `/user_list` | users and their access |
| `/user_add Name [id]`, `/user_link Name id` | add a user, connect a Telegram id |
| `/user_grant Name service level`, `/user_revoke Name service` | change access |
| `/user_deactivate Name`, `/user_activate Name` | (de)activate a user |

**Notifications** (sent by the bot on its own):
- **Assigned to you:** within a minute of a ticket being assigned to you by someone else
  (from the bot, the CLI or the API), with an "Open" button.
- **Morning summary:** at `MORNING_SUMMARY_TIME` (in `.env`, default 08:30), each person
  gets their tickets that are due today or late. Tickets admins also get late tickets
  that nobody is assigned to. Nobody gets a message when nothing is urgent.
- **Homes in Italy:** after the estate service's daily fetch, everyone with estate access
  gets the best new listings, new auctions and starred listings that got cheaper.
  No message when nothing is new.

How it works: the tickets service lists every change at `/events`. The bot checks it
every minute and remembers the last change it handled in `data/bot/state.json`, so
nothing is sent twice after a restart. On its very first start the bot skips older changes.
The same file remembers the last estate fetch it reported.
After changing `.env`, run `docker compose up -d bot` so the container picks it up.

## Security

Everything runs at home. Nothing needs to be reachable from the internet, so **never
set up port forwarding** on the router for these services.

| What | Who can reach it |
|---|---|
| Users API (8002), Tickets API (8001), Estate API (8003) | only this machine (`127.0.0.1`); other services use Docker's internal network |
| Info screen (8080) | every device on the home network, so the TV can open it. It has no password, so put guests on a guest Wi-Fi. |
| Bot health (8000) | only inside Docker, for the info screen and Docker's own health check |
| Telegram bot | anyone on Telegram can write to it, but only known, active users get answers |

**Bot rules:**
- Every message and button press is checked against the users service: Telegram sets the
  sender's id, and it can't be faked.
- Strangers only get their own Telegram id. Each attempt is logged:
  `docker compose logs bot | grep Stranger`.
- The bot works only in one-to-one chats. If someone adds it to a group or channel, it
  leaves immediately, so ticket lists never end up in front of others. Also turn groups
  off in @BotFather: `/mybots` → your bot → Bot Settings → Allow Groups → Turn off.
- What each person may do is decided by the service they use, by their access level.

**Secrets:** `.env` holds the bot token and `API_TOKEN` and is never committed.
If the bot token leaks: send `/revoke` to @BotFather, put the new token into `.env` and run
`docker compose up -d bot`.

Telegram stores bot chats on its servers, without end-to-end encryption. Don't put
passwords or codes into tickets.

## Developing a service without Docker

```bash
cd services/users                      # or tickets, estate, screen, bot
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest                       # run the tests
```

Run them locally (stop the Docker versions first; `API_TOKEN` must match `.env`):

```bash
services/users/.venv/bin/uvicorn users.api:app --reload --port 8002
USERS_URL=http://localhost:8002 services/tickets/.venv/bin/uvicorn tickets.api:app --reload --port 8001
USERS_URL=http://localhost:8002 services/estate/.venv/bin/uvicorn estate.api:app --reload --port 8003
TICKETS_URL=http://localhost:8001 services/screen/.venv/bin/uvicorn screen.main:app --reload --port 8080
USERS_URL=http://localhost:8002 TICKETS_URL=http://localhost:8001 ESTATE_URL=http://localhost:8003 TELEGRAM_TOKEN=... services/bot/.venv/bin/python -m bot.main
```

The local CLIs use `data/users/users.db`, `data/tickets/tickets.db` and `data/estate/estate.db`.

How the services are built:
- **users, tickets:** `core.py` holds all the rules; `api.py` and `cli.py` only call it.
  Tickets asks the users service who is who (`people.py`).
- **estate:** the same, plus `sources/` with one file per website (each has a
  `fetch()` that yields listings), `parse.py` to read rooms, m² and towns out of Italian
  text, `criteria.py` for the settings file and `fetcher.py` for the daily fetch.
- **screen:** each data source is one file in `collectors/` with a `fetch(config)`
  function. `main.py` runs each one on a timer, and `templates/index.html` shows the results.
- **bot:** one folder per service (`users/`, `tickets/`, `estate/`), each with a client for the
  service's API, `texts.py` for messages and buttons, and `handlers.py` with its commands.
  `general.py` lists the services, and `access.py` decides who may talk to the bot.
  To add a service to the bot, add a folder like these and list it in `general.py`.

## History

- **October 2026:** users moved out of the tickets service into their own service, with
  per-service access levels (`scripts/split_users.py`). The old database is kept in `data/backups/`.

## License

[MIT](LICENSE): use, change and share it freely, keeping the copyright notice.

Not covered by it, because the screen only fetches them while running: weather data
from [Open-Meteo](https://open-meteo.com) (free for non-commercial use, CC BY 4.0) and
news headlines, which belong to [LSM](https://rus.lsm.lv). The same goes for listings,
which belong to the sites and agencies they come from: the estate service keeps them
only for your own home's use.
