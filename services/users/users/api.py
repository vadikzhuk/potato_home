"""HTTP API of the users service, used by the other services and the bot.

Each endpoint reads the request, calls one function from core.py and returns JSON.
Open http://localhost:8002/docs to see and try every endpoint.

Headers:
  X-Api-Token    must match API_TOKEN from .env (every endpoint except /health)
  X-Telegram-Id  the person acting (or X-User-Id). Needed for changes.
                 Optional for reading: with it, the person needs read access to users;
                 without it, it's a service asking (e.g. tickets looking up names).
"""

import os
import sqlite3
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from . import core, db


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = db.connect()  # creates tables on the first start
    db.seed_users(conn)
    conn.close()
    yield


app = FastAPI(title="Users", lifespan=lifespan)


@app.exception_handler(core.UsersError)
def users_error(request: Request, error: core.UsersError) -> JSONResponse:
    status = {core.NotFound: 404, core.Forbidden: 403}.get(type(error), 400)
    return JSONResponse({"detail": str(error)}, status_code=status)


# --- Dependencies -------------------------------------------------------------

def get_conn():
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


def check_token(x_api_token: str | None = Header(None)) -> None:
    expected = os.environ.get("API_TOKEN", "")
    if expected and x_api_token != expected:
        raise HTTPException(401, "Bad or missing X-Api-Token.")


def optional_actor(conn: sqlite3.Connection = Depends(get_conn),
                   x_telegram_id: int | None = Header(None),
                   x_user_id: int | None = Header(None)) -> core.User | None:
    if x_telegram_id is None and x_user_id is None:
        return None
    try:
        if x_telegram_id is not None:
            return core.get_user_by_telegram(conn, x_telegram_id)
        return core.get_user(conn, x_user_id)
    except core.NotFound:
        raise HTTPException(401, "Unknown user.") from None


def get_actor(actor: core.User | None = Depends(optional_actor)) -> core.User:
    if actor is None:
        raise HTTPException(401, "Send X-Telegram-Id or X-User-Id of the person making the change.")
    return actor


def check_reader(actor: core.User | None = Depends(optional_actor)) -> None:
    """A person needs read access to users to see them; services may always look."""
    if actor is not None and not core.has_level(actor, core.USERS, "read"):
        raise HTTPException(403, "You have no access to the user list.")


# --- Request bodies -----------------------------------------------------------

class NewUser(BaseModel):
    name: str
    telegram_id: int | None = None


class UserChanges(BaseModel):  # only the fields you send are changed
    name: str | None = None
    telegram_id: int | None = None
    is_active: bool | None = None


class Level(BaseModel):
    level: str  # read, write or admin


# --- Endpoints ----------------------------------------------------------------

@app.get("/health")
def health(conn=Depends(get_conn)):
    """Used by the info screen and Docker. Fails (HTTP 500) if the database doesn't answer."""
    conn.execute("SELECT 1")
    return {"status": "ok"}


router = APIRouter(dependencies=[Depends(check_token)])
reading = [Depends(check_reader)]


# Lookups used to identify who is talking: no access needed
@router.get("/users/by-telegram/{telegram_id}")
def user_by_telegram(telegram_id: int, conn=Depends(get_conn)):
    return core.get_user_by_telegram(conn, telegram_id)


@router.get("/users", dependencies=reading)
def list_users(include_inactive: bool = False, conn=Depends(get_conn)):
    return core.list_users(conn, include_inactive)


@router.get("/users/by-name/{name}", dependencies=reading)
def user_by_name(name: str, conn=Depends(get_conn)):
    return core.get_user_by_name(conn, name)


@router.get("/users/{user_id}", dependencies=reading)
def get_user(user_id: int, conn=Depends(get_conn)):
    return core.get_user(conn, user_id)


@router.post("/users", status_code=201)
def add_user(body: NewUser, actor=Depends(get_actor), conn=Depends(get_conn)):
    return core.add_user(conn, actor, body.name, body.telegram_id)


@router.patch("/users/{user_id}")
def update_user(user_id: int, body: UserChanges, actor=Depends(get_actor), conn=Depends(get_conn)):
    return core.update_user(conn, actor, user_id, **body.model_dump(exclude_unset=True))


@router.put("/users/{user_id}/access/{service}")
def grant(user_id: int, service: str, body: Level, actor=Depends(get_actor), conn=Depends(get_conn)):
    return core.grant(conn, actor, user_id, service, body.level)


@router.delete("/users/{user_id}/access/{service}")
def revoke(user_id: int, service: str, actor=Depends(get_actor), conn=Depends(get_conn)):
    return core.revoke(conn, actor, user_id, service)


app.include_router(router)
