"""HTTP API of the tickets service, used by the bot and the info screen.

Each endpoint reads the request, calls one function from core.py and returns JSON.
Open http://localhost:8001/docs to see and try every endpoint in the browser.

Headers:
  X-Api-Token    must match API_TOKEN from .env (every endpoint except /health)
  X-Telegram-Id  the person acting (or X-User-Id). Needed for changes.
                 Optional for reading: with it, the person needs read access to tickets;
                 without it, it's a service asking (e.g. the info screen).
"""

import os
import sqlite3
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from . import core, db
from .people import People, Person, Unavailable

people = People.from_service()


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.connect().close()  # creates tables on the first start
    yield


app = FastAPI(title="Tickets", lifespan=lifespan)


@app.exception_handler(core.TicketsError)
def tickets_error(request: Request, error: core.TicketsError) -> JSONResponse:
    status = {core.NotFound: 404, core.Forbidden: 403}.get(type(error), 400)
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
    """A person needs read access to see tickets; services may always look."""
    if actor is not None:
        core.require(actor, "read")


# --- Request bodies -----------------------------------------------------------
# In PATCH bodies only the fields you send are changed; send null to clear a value.

class NewTicket(BaseModel):
    title: str
    description: str = ""
    due_date: str | None = None  # YYYY-MM-DD, today, tomorrow or +N
    assignee_id: int | None = None


class TicketChanges(BaseModel):
    title: str | None = None
    description: str | None = None
    due_date: str | None = None
    assignee_id: int | None = None
    status: str | None = None


# --- Endpoints ----------------------------------------------------------------

@app.get("/health")
def health(conn=Depends(get_conn), people=Depends(get_people)):
    """Used by the info screen and Docker. Fails (HTTP 500) if the database doesn't answer;
    "degraded" if the users service doesn't, because then nobody can change tickets."""
    conn.execute("SELECT 1")
    try:
        people.all()
    except Unavailable as error:
        return {"status": "degraded", "detail": str(error)}
    return {"status": "ok"}


router = APIRouter(dependencies=[Depends(check_token)])
reading = [Depends(check_reader)]


@router.get("/tickets", dependencies=reading)
def list_tickets(status: list[str] = Query(list(core.ACTIVE_STATUSES), description="Repeat for several; 'all' for every ticket."),
                 assignee_id: int | None = None, conn=Depends(get_conn), people=Depends(get_people)):
    tickets = core.list_tickets(conn, None if "all" in status else status, assignee_id)
    return [core.named(t, people) for t in tickets]


@router.get("/tickets/{ticket_id}", dependencies=reading)
def get_ticket(ticket_id: int, conn=Depends(get_conn), people=Depends(get_people)):
    return {"ticket": core.named(core.get_ticket(conn, ticket_id), people),
            "history": core.history(conn, people, ticket_id)}


@router.post("/tickets", status_code=201)
def create_ticket(body: NewTicket, actor=Depends(get_actor), conn=Depends(get_conn), people=Depends(get_people)):
    ticket = core.create_ticket(conn, people, actor, body.title, body.description, body.due_date, body.assignee_id)
    return core.named(ticket, people)


@router.patch("/tickets/{ticket_id}")
def update_ticket(ticket_id: int, body: TicketChanges, actor=Depends(get_actor),
                  conn=Depends(get_conn), people=Depends(get_people)):
    ticket = core.update_ticket(conn, people, actor, ticket_id, **body.model_dump(exclude_unset=True))
    return core.named(ticket, people)


@router.get("/events", dependencies=reading)
def events(after_id: int = 0, limit: int = Query(100, le=500), conn=Depends(get_conn), people=Depends(get_people)):
    """Ticket changes with id > after_id, oldest first: used by the bot for notifications."""
    return core.events_after(conn, people, after_id, limit)


@router.get("/summary", dependencies=reading)
def summary(conn=Depends(get_conn), people=Depends(get_people)):
    """Active tickets, most urgent first, with overdue flags: used by the info screen."""
    return core.summary(conn, people)


app.include_router(router)
