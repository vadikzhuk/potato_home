"""HTTP API of botwatch, used by the home bot, the info screen and the bots themselves.

Open http://localhost:8004/docs to see and try every endpoint in the browser.

Headers:
  X-Api-Token    must match API_TOKEN from .env (every endpoint except /health and POST /usage)
  X-Usage-Token  must match USAGE_TOKEN from .env, for POST /usage. The bots get only this
                 token, so they can send usage counts but read nothing.

Who may see the bots is decided by the home bot (access to "botwatch" in the users
service); it asks here with the API token, as a service.

Starting the service also starts checking the bots in the background (see watcher.py).
"""

import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import core, db, watcher
from . import settings as settings_file

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)  # its log lines would show bot tokens (they are in the URLs)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.connect().close()  # creates tables on the first start
    stop = watcher.start()
    yield
    stop.set()


app = FastAPI(title="Botwatch", lifespan=lifespan)


@app.exception_handler(core.BotwatchError)
def botwatch_error(request: Request, error: core.BotwatchError) -> JSONResponse:
    return JSONResponse({"detail": str(error)}, status_code=404 if isinstance(error, core.NotFound) else 400)


def get_conn():
    """One database connection per request, closed afterwards."""
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


def check_token(x_api_token: str | None = Header(None)) -> None:
    expected = os.environ.get("API_TOKEN", "")
    if expected and x_api_token != expected:
        raise HTTPException(401, "Bad or missing X-Api-Token.")


def check_usage_token(x_usage_token: str | None = Header(None), x_api_token: str | None = Header(None)) -> None:
    usage, api = os.environ.get("USAGE_TOKEN", ""), os.environ.get("API_TOKEN", "")
    if not usage and not api:
        return  # developing without tokens
    if (usage and x_usage_token == usage) or (api and x_api_token == api):
        return
    raise HTTPException(401, "Bad or missing X-Usage-Token.")


class Event(BaseModel):
    at: datetime
    kind: str = Field(max_length=20)
    name: str | None = Field(None, max_length=64)
    user: int | None = None
    chat: str | None = Field(None, max_length=20)
    ms: int | None = Field(None, ge=0)
    ok: bool = True


class Usage(BaseModel):
    username: str = Field(max_length=64)
    events: list[Event] = Field(max_length=1000)


@app.get("/health")
def health(conn=Depends(get_conn)):
    """For the info screen and Docker: "degraded" when a bot has a problem, or checking itself has one."""
    problems = []
    try:
        settings_file.load()
    except core.Invalid as error:
        problems.append(str(error))
    if watcher.last_round["problem"]:
        problems.append(watcher.last_round["problem"])
    elif watcher.last_round["at"] and time.monotonic() - watcher.last_round["at"] > 3 * watcher.last_round["every"]:
        problems.append("checks stopped running")
    bots = core.status(conn)
    problems += [f"{b['bot']}: {', '.join(b['problems'])}" for b in bots if b["problems"]]
    if problems:
        return {"status": "degraded", "detail": "; ".join(problems)}
    if watcher.last_round["at"] is None and not bots:
        return {"status": "ok", "detail": "starting"}
    return {"status": "ok", "detail": f"{len(bots)} bot{'s' if len(bots) != 1 else ''} ok"}


@app.post("/usage", dependencies=[Depends(check_usage_token)])
def add_usage(body: Usage, conn=Depends(get_conn)):
    """botstats.py inside a bot sends what the bot handled, once a minute."""
    events = [e.model_dump() for e in body.events]
    for e in events:
        if e["at"].tzinfo is None:
            e["at"] = e["at"].replace(tzinfo=timezone.utc)
    return {"saved": core.save_events(conn, body.username, events)}


router = APIRouter(dependencies=[Depends(check_token)])


@router.get("/bots")
def bots(conn=Depends(get_conn)):
    """Every bot as last checked: state, problems, memory, uptime, errors and usage today."""
    return core.status(conn)


@router.get("/bots/{name}/usage")
def usage(name: str, days: int = Query(7, ge=1, le=366), conn=Depends(get_conn)):
    """How a bot (by name or @username) was used, day by day."""
    return core.usage(conn, name, days)


@router.get("/alerts")
def alerts(after: int | None = Query(None, description="Only alerts after this id (the home bot's bookmark)"),
           limit: int = Query(50, le=500), conn=Depends(get_conn)):
    """Alerts oldest first. Without `after`: the latest `limit` ones."""
    return core.alerts(conn, after, limit)


app.include_router(router)
