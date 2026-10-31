"""Info screen: one 16:9 page for the TV with today's weather, homes in Italy,
news, service health and active tickets.

How it works:
  * On start, one background loop per collector fetches its data on a timer
    and keeps the latest result in `panels` (in memory).
  * The page is rendered from `panels`, so it is always instant; a slow or
    broken website never blocks it. A failed fetch keeps the old data.
  * The page reloads itself every minute (<meta refresh>, no JavaScript needed).
  * Each reload may move the page a few pixels (pixel_shift), against OLED burn-in.

To add a panel: write collectors/<name>.py, add it to COLLECTORS and the template.
"""

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .collectors import estate, health, news, tickets, weather

HERE = Path(__file__).parent
log = logging.getLogger("uvicorn.error")


def load_config() -> dict:
    path = os.environ.get("SCREEN_CONFIG") or HERE.parent / "config.yaml"
    config = yaml.safe_load(Path(path).read_text())
    config["tickets"]["url"] = os.environ.get("TICKETS_URL") or config["tickets"]["url"]
    config["estate"]["url"] = os.environ.get("ESTATE_URL") or config["estate"]["url"]
    return config


CONFIG = load_config()
LOCAL_TZ = ZoneInfo(CONFIG["timezone"])
COLLECTORS = {"weather": weather.fetch, "estate": estate.fetch, "news": news.fetch, "tickets": tickets.fetch,
              "health": health.fetch}

# The latest result of every collector: what the page shows.
# took_ms: how long the last fetch took, shown in the health panel for outside sources.
panels = {name: {"data": None, "updated": None, "error": None, "took_ms": None} for name in COLLECTORS}


async def keep_fresh(name: str) -> None:
    """Run one collector forever, every `refresh_minutes` from its config section."""
    while True:
        started = time.monotonic()
        try:
            # Collectors are plain (blocking) functions; run them in a thread
            panels[name]["data"] = await asyncio.to_thread(COLLECTORS[name], CONFIG)
            panels[name]["updated"] = datetime.now(LOCAL_TZ)
            panels[name]["error"] = None
        except Exception as error:
            log.warning("Collector %s failed: %r", name, error)
            panels[name]["error"] = str(error) or type(error).__name__
        panels[name]["took_ms"] = round((time.monotonic() - started) * 1000)
        await asyncio.sleep(CONFIG[name]["refresh_minutes"] * 60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    tasks = [asyncio.create_task(keep_fresh(name)) for name in COLLECTORS]
    yield
    for task in tasks:
        task.cancel()


app = FastAPI(title="Info screen", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")


def pixel_shift(now: datetime, settings: dict) -> tuple[float, float]:
    """How far to move the page now, in rem: (right, down).

    The page walks a 5×5 grid around its normal place, row by row like a snake,
    one step every `every_minutes`. A CSS animation wouldn't do: the page
    reloads every minute and would start from the beginning each time.
    """
    size = settings["max_rem"]
    if not size:
        return 0.0, 0.0
    steps = [-size, -size / 2, 0.0, size / 2, size]
    spots = [(x, y) for row, y in enumerate(steps) for x in (steps if row % 2 == 0 else steps[::-1])]
    minute_of_day = now.hour * 60 + now.minute
    return spots[minute_of_day // settings["every_minutes"] % len(spots)]


@app.get("/", response_class=HTMLResponse)
def page(request: Request):
    slow_ms = CONFIG["health"]["slow_source_ms"]
    sources = [  # outside websites, shown in the health panel below our services
        health.source_row("Weather · Open-Meteo", panels["weather"], slow_ms),
        health.source_row("News · rus.lsm.lv", panels["news"], slow_ms),
    ]
    return templates.TemplateResponse(request, "index.html", {
        "panels": panels,
        "sources": sources,
        "now": datetime.now(LOCAL_TZ),
        "reload_seconds": CONFIG["page_reload_seconds"],
        "shift": pixel_shift(datetime.now(LOCAL_TZ), CONFIG["pixel_shift"]),
    })


@app.get("/data")
def data():
    """Everything the page shows, as JSON: handy for checking a collector."""
    return panels


@app.get("/health")
def own_health():  # not named `health`: that's the health collector module
    return {"status": "ok"}
