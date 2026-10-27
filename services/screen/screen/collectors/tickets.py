"""Active tickets from our own tickets service."""

import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx


def fetch(config: dict) -> dict:
    response = httpx.get(
        config["tickets"]["url"].rstrip("/") + "/summary",
        headers={"X-Api-Token": os.environ.get("API_TOKEN", "")},
        timeout=10,
    )
    response.raise_for_status()
    today = datetime.now(ZoneInfo(config["timezone"])).date()
    return prepare(response.json(), config["tickets"]["max_shown"], today)


def prepare(summary: dict, max_shown: int, today: date) -> dict:
    """Keep the most urgent tickets and add a readable due label to each."""
    tickets = []
    for t in summary["tickets"][:max_shown]:
        label, urgency = due_label(t["due_date"], today)
        tickets.append({
            "id": t["id"],
            "title": t["title"],
            "assignee": t["assignee_name"] or "nobody",
            "in_progress": t["status"] == "in_progress",
            "due": label,
            "urgency": urgency,  # late, today, soon or "" (used as a CSS class)
        })
    return {
        "counts": summary["counts"],
        "tickets": tickets,
        "hidden": max(0, len(summary["tickets"]) - max_shown),
    }


def due_label(due_date: str | None, today: date) -> tuple[str, str]:
    if not due_date:
        return "", ""
    days = (date.fromisoformat(due_date) - today).days
    if days < 0:
        return f"{-days} day{'s' if days < -1 else ''} late", "late"
    if days == 0:
        return "today", "today"
    if days == 1:
        return "tomorrow", "soon"
    if days < 7:
        return f"in {days} days", "soon" if days <= 2 else ""
    return date.fromisoformat(due_date).strftime("%-d %b"), ""
