"""HTTP API of the estate service, used by the bot (and later the info screen).

Each endpoint reads the request, calls one function from core.py and returns JSON.
Open http://localhost:8003/docs to see and try every endpoint in the browser.

Headers:
  X-Api-Token    must match API_TOKEN from .env (every endpoint except /health)
  X-Telegram-Id  the person asking (or X-User-Id). Needed for changes.
                 Optional for reading: with it, the person needs read access to estate;
                 without it, it's a service asking (e.g. the bot's daily digest).

Starting the service also starts the daily fetch in the background (see fetcher.py).
"""

import logging
import os
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from . import core, criteria, db, fetcher
from .people import People, Person, Unavailable

people = People.from_service()
logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)  # otherwise every page fetched is logged


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.connect().close()  # creates tables on the first start
    stop = threading.Event()
    threading.Thread(target=fetcher.daily, args=(stop,), daemon=True, name="daily-fetch").start()
    yield
    stop.set()


app = FastAPI(title="Estate", lifespan=lifespan)


@app.exception_handler(core.EstateError)
def estate_error(request: Request, error: core.EstateError) -> JSONResponse:
    status = {core.NotFound: 404, core.Forbidden: 403, fetcher.Busy: 409}.get(type(error), 400)
    return JSONResponse({"detail": str(error)}, status_code=status)


@app.exception_handler(Unavailable)
def users_unavailable(request: Request, error: Unavailable) -> JSONResponse:
    return JSONResponse({"detail": str(error)}, status_code=503)


# --- Dependencies: things endpoints ask for in their arguments -------------------

def get_conn():
    """One database connection per request, closed afterwards."""
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


def get_people() -> People:
    return people  # tests replace this with fake people


def get_criteria() -> dict:
    return criteria.load()  # read on every request: saving the file is enough


def check_token(x_api_token: str | None = Header(None)) -> None:
    expected = os.environ.get("API_TOKEN", "")
    if expected and x_api_token != expected:
        raise HTTPException(401, "Bad or missing X-Api-Token.")


def optional_actor(people: People = Depends(get_people),
                   x_telegram_id: int | None = Header(None),
                   x_user_id: int | None = Header(None)) -> Person | None:
    if x_telegram_id is None and x_user_id is None:
        return None
    person = people.by_telegram(x_telegram_id) if x_telegram_id is not None else people.get(x_user_id)
    if person is None:
        raise HTTPException(401, "Unknown user.")
    return person


def get_actor(actor: Person | None = Depends(optional_actor)) -> Person:
    if actor is None:
        raise HTTPException(401, "Send X-Telegram-Id or X-User-Id of the person making the change.")
    return actor


def check_reader(actor: Person | None = Depends(optional_actor)) -> None:
    """A person needs read access to see listings; services may always look."""
    if actor is not None:
        core.require(actor, "read")


class ListingChanges(BaseModel):
    hidden: bool | None = None
    starred: bool | None = None


# --- Endpoints ----------------------------------------------------------------

@app.get("/health")
def health(conn=Depends(get_conn), people=Depends(get_people)):
    """Used by the info screen and Docker. Fails (HTTP 500) if the database doesn't answer;
    "degraded" if criteria.yaml is broken, the last fetch had errors or is old,
    or the users service doesn't answer."""
    conn.execute("SELECT 1")
    problems = []
    try:
        criteria.load()
    except core.Invalid as error:
        problems.append(str(error))
    run = core.latest_run(conn)
    if run and run["errors"]:
        problems.append("last fetch: " + run["errors"].replace("\n", "; "))
    two_days_ago = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    if run and run["finished_at"] < two_days_ago:
        problems.append(f"no fetch since {run['finished_at'][:10]}")
    try:
        people.all()
    except Unavailable as error:
        problems.append(str(error))
    if problems:
        return {"status": "degraded", "detail": "; ".join(problems)}
    return {"status": "ok", "detail": f"last fetch {run['finished_at'][:16]}" if run else "no fetch yet"}


router = APIRouter(dependencies=[Depends(check_token)])
reading = [Depends(check_reader)]


@router.get("/listings/top", dependencies=reading)
def top(limit: int = Query(10, le=100),
        auctions: bool | None = Query(None, description="true: only auctions, false: none, empty: all"),
        conn=Depends(get_conn), settings=Depends(get_criteria)):
    """The best listings matching criteria.yaml, best first."""
    return core.top(conn, settings, limit, auctions)


@router.get("/listings/starred", dependencies=reading)
def starred(conn=Depends(get_conn), settings=Depends(get_criteria)):
    return core.starred(conn, settings)


@router.get("/listings/{listing_id}", dependencies=reading)
def get_listing(listing_id: int, conn=Depends(get_conn), settings=Depends(get_criteria)):
    """One listing with its score details, price history and why it isn't shown (if it isn't)."""
    return core.get_listing(conn, settings, listing_id)


@router.patch("/listings/{listing_id}")
def update_listing(listing_id: int, body: ListingChanges, actor=Depends(get_actor),
                   conn=Depends(get_conn), settings=Depends(get_criteria)):
    """Hide or star a listing. Needs write access."""
    return core.set_flags(conn, settings, actor, listing_id, **body.model_dump(exclude_unset=True))


@router.get("/digest", dependencies=reading)
def digest(after_run: int | None = None, conn=Depends(get_conn), settings=Depends(get_criteria)):
    """New listings since fetch `after_run` finished (default: from the latest fetch),
    and starred listings that got cheaper. Used by the bot for the daily message."""
    return core.digest(conn, settings, after_run)


@router.get("/runs", dependencies=reading)
def runs(limit: int = Query(10, le=100), conn=Depends(get_conn)):
    """The latest fetches, newest first."""
    return core.list_runs(conn, limit)


@router.post("/runs", status_code=202)
def start_run(actor=Depends(get_actor), settings=Depends(get_criteria)):
    """Fetch now instead of waiting for the daily time. Needs admin access.
    Returns at once; the fetch takes a while (see GET /runs)."""
    core.require(actor, "admin")
    fetcher.start(settings)
    return {"detail": "Fetch started."}


app.include_router(router)
