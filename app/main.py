import os
import asyncio
import hmac
import uuid
from datetime import date, datetime
from contextlib import asynccontextmanager
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException, Query, Depends
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import Literal

from . import coc_api, database, sync


@asynccontextmanager
async def lifespan(_app):
    database.initialize()
    if not (os.getenv("CLAN_TAG") and os.getenv("COC_API_TOKEN")):
        database.remove_demo()
    else:
        database.remove_demo()
        task = asyncio.create_task(sync.run_periodically())
        _app.state.sync_task = task
        try:
            yield
        finally:
            task.cancel()
        return
    yield


app = FastAPI(title="CoC Clan Tracker", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
basic_auth = HTTPBasic(auto_error=False)


def require_admin(credentials: HTTPBasicCredentials | None = Depends(basic_auth)):
    username = os.getenv("ADMIN_USERNAME")
    password = os.getenv("ADMIN_PASSWORD")
    if not username or not password:
        raise HTTPException(503, "Admin-Zugang fehlt. ADMIN_USERNAME und ADMIN_PASSWORD in .env setzen.")
    if credentials is None or not (hmac.compare_digest(credentials.username, username) and hmac.compare_digest(credentials.password, password)):
        raise HTTPException(401, "Anmeldung fehlgeschlagen", headers={"WWW-Authenticate": "Basic"})
    return credentials.username


class Adjustment(BaseModel):
    player_tag: str = Field(min_length=3, max_length=20)
    event_key: str = Field(min_length=1, max_length=80)
    category: str = Field(min_length=1, max_length=40)
    description: str = Field(min_length=1, max_length=200)
    points: int = Field(ge=-1000, le=1000)


class MemberAdminUpdate(BaseModel):
    player_tag: str = Field(min_length=3, max_length=20)
    absence_end: date | None = None


@app.get("/")
def index():
    return FileResponse("app/static/index.html")


@app.get("/admin")
def admin_page():
    return FileResponse("app/static/admin.html")


@app.get("/api/health")
def health():
    configured = bool(os.getenv("CLAN_TAG") and os.getenv("COC_API_TOKEN"))
    return {"status": "ok", "api_configured": configured, "last_sync": database.get_state("last_sync")}


@app.get("/api/config")
def public_config():
    return {
        "support_discord": os.getenv("SUPPORT_DISCORD", "").strip(),
        "clan_name": database.get_state("clan_name") or "",
    }


@app.get("/api/dashboard")
def dashboard():
    return database.dashboard_data()


@app.get("/api/history")
def points_history(limit: int = Query(default=250, ge=1, le=1000), category: str | None = None, player_tag: str | None = None):
    with database.connect() as db:
        if player_tag and category:
            rows = db.execute("""SELECT p.player_tag,m.name,p.category,p.description,p.points,p.created_at
                FROM point_entries p JOIN members m ON m.player_tag=p.player_tag
                WHERE p.player_tag=? AND p.category=? ORDER BY p.id DESC""", (player_tag, category)).fetchall()
        elif player_tag:
            rows = db.execute("""SELECT p.player_tag,m.name,p.category,p.description,p.points,p.created_at
                FROM point_entries p JOIN members m ON m.player_tag=p.player_tag
                WHERE p.player_tag=? ORDER BY p.id DESC""", (player_tag,)).fetchall()
        elif category:
            rows = db.execute("""SELECT p.player_tag,m.name,p.category,p.description,p.points,p.created_at
                FROM point_entries p JOIN members m ON m.player_tag=p.player_tag
                WHERE p.category=? ORDER BY p.id DESC LIMIT ?""", (category, limit)).fetchall()
        else:
            rows = db.execute("""SELECT p.player_tag,m.name,p.category,p.description,p.points,p.created_at
                FROM point_entries p JOIN members m ON m.player_tag=p.player_tag
                ORDER BY p.id DESC LIMIT ?""", (limit,)).fetchall()
    return {"items": [dict(row) for row in rows]}


@app.get("/api/member-table")
def member_table():
    categories = {
        "Krieg": "CK",
        "CWL": "CWL",
        "Überfall-Wochenende": "Überfall-WE",
        "Spenden": "Spende",
        "Clan-Spiele": "Clan-Spiele",
        "Bonus": "Bonus",
    }
    with database.connect() as db:
        members = db.execute("""SELECT m.player_tag,m.name,m.role,m.town_hall_level,m.weekly_activity,m.absence_start,m.absence_end,m.admin_comment,m.is_current_clan,
            COALESCE(SUM(p.points),0) AS points
            FROM members m LEFT JOIN point_entries p ON p.player_tag=m.player_tag
            GROUP BY m.player_tag ORDER BY points DESC,m.name COLLATE NOCASE""").fetchall()
        breakdown = db.execute("""SELECT player_tag,category,SUM(points) AS points
            FROM point_entries GROUP BY player_tag,category""").fetchall()
    by_member = {}
    for item in breakdown:
        key = categories.get(item["category"], "Bonus")
        values = by_member.setdefault(item["player_tag"], {})
        values[key] = values.get(key, 0) + item["points"]
    return {"members": [{**dict(member), "categories": by_member.get(member["player_tag"], {})} for member in members]}


@app.get("/api/members/{player_tag}")
def member_entries(player_tag: str):
    with database.connect() as db:
        member = db.execute("SELECT player_tag,name FROM members WHERE player_tag=?", (player_tag,)).fetchone()
        if not member:
            raise HTTPException(404, "Spieler nicht gefunden")
        entries = db.execute("SELECT category,description,points,created_at FROM point_entries WHERE player_tag=? ORDER BY id DESC", (player_tag,)).fetchall()
    return {"member": dict(member), "entries": [dict(x) for x in entries]}


@app.get("/api/members/{player_tag}/breakdown")
def member_breakdown(player_tag: str):
    with database.connect() as db:
        member = db.execute("SELECT player_tag,name FROM members WHERE player_tag=?", (player_tag,)).fetchone()
        if not member:
            raise HTTPException(404, "Spieler nicht gefunden")
        categories = db.execute("""SELECT category, SUM(points) AS points, COUNT(*) AS entries
            FROM point_entries WHERE player_tag=? GROUP BY category ORDER BY category""", (player_tag,)).fetchall()
    return {"member": dict(member), "categories": [dict(row) for row in categories]}


@app.get("/api/admin/session")
def admin_session(admin: str = Depends(require_admin)):
    return {"authenticated": True, "username": admin}


@app.get("/api/admin/members")
def admin_members(_admin: str = Depends(require_admin)):
    with database.connect() as db:
        rows = db.execute("SELECT player_tag,name,role,town_hall_level,weekly_activity,absence_start,absence_end,admin_comment,is_current_clan FROM members ORDER BY is_current_clan DESC,name COLLATE NOCASE").fetchall()
    return {"members": [dict(row) for row in rows]}


@app.get("/api/admin/history")
def admin_history(limit: int = Query(default=250, ge=1, le=1000), kind: Literal["manual", "activity"] | None = None, _admin: str = Depends(require_admin)):
    manual_condition = "(p.event_key LIKE 'manual:%' OR (p.category='Clan-Spiele' AND p.description NOT LIKE 'Automatisch erfasst:%'))"
    where = ""
    if kind == "manual":
        where = f"WHERE {manual_condition}"
    elif kind == "activity":
        where = f"WHERE NOT {manual_condition}"
    with database.connect() as db:
        rows = db.execute(f"""SELECT p.id,p.event_key,p.player_tag,m.name,p.category,p.description,p.points,p.created_at
            FROM point_entries p JOIN members m ON m.player_tag=p.player_tag
            {where} ORDER BY p.id DESC LIMIT ?""", (limit,)).fetchall()
    return {"items": [dict(row) for row in rows]}


@app.delete("/api/admin/history/{entry_id}")
def delete_admin_history_entry(entry_id: int, _admin: str = Depends(require_admin)):
    with database.connect() as db:
        row = db.execute("SELECT event_key FROM point_entries WHERE id=?", (entry_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Buchung nicht gefunden")
        if not row["event_key"].startswith(("manual:", "clangames:")):
            raise HTTPException(409, "Automatische Buchungen können hier nicht gelöscht werden.")
        db.execute("DELETE FROM point_entries WHERE id=?", (entry_id,))
    return {"deleted": True, "id": entry_id}


@app.put("/api/admin/member-status")
def update_member_status(item: MemberAdminUpdate, _admin: str = Depends(require_admin)):
    today = datetime.now(ZoneInfo("Europe/Berlin")).date()
    if item.absence_end is not None and item.absence_end < today:
        raise HTTPException(422, "Das Abmeldedatum muss heute oder in der Zukunft liegen.")
    with database.connect() as db:
        if item.absence_end is None:
            result = db.execute("""UPDATE members SET weekly_activity='aktiv',absence_start=NULL,absence_end=NULL
                WHERE player_tag=?""", (item.player_tag,))
        else:
            result = db.execute("""UPDATE members SET weekly_activity='abgemeldet',absence_start=?,absence_end=?
                WHERE player_tag=?""", (today.isoformat(), item.absence_end.isoformat(), item.player_tag))
        if result.rowcount == 0:
            raise HTTPException(404, "Mitglied nicht gefunden")
    return {"saved": True, "weekly_activity": "abgemeldet" if item.absence_end else "aktiv"}


@app.post("/api/admin/adjustments")
def add_adjustment(item: Adjustment, _admin: str = Depends(require_admin)):
    with database.connect() as db:
        member = db.execute("SELECT is_current_clan FROM members WHERE player_tag=?", (item.player_tag,)).fetchone()
        if not member:
            raise HTTPException(404, "Spieler nicht gefunden")
        if not member["is_current_clan"]:
            raise HTTPException(409, "Punkte können nur an aktuelle Clanmitglieder vergeben werden.")
        try:
            db.execute("INSERT INTO point_entries(player_tag,event_key,category,description,points) VALUES(?,?,?,?,?)", (item.player_tag, f"manual:{uuid.uuid4().hex}", item.category, item.description, item.points))
        except Exception as exc:
            if "UNIQUE" in str(exc):
                raise HTTPException(409, "Diese Buchung existiert bereits")
            raise
    return {"saved": True}


@app.post("/api/admin/sync")
async def admin_sync(_admin: str = Depends(require_admin)):
    return await sync.sync_once()


@app.get("/api/coc/{endpoint}")
async def api_preview(endpoint: str):
    allowed = {"members", "currentwar", "capitalraidseasons"}
    if endpoint not in allowed:
        raise HTTPException(404, "Endpunkt nicht freigegeben")
    try:
        return await coc_api.get_clan_endpoint(endpoint)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))
    except Exception as exc:
        raise HTTPException(502, f"CoC API Anfrage fehlgeschlagen: {exc}")


# Also serve relative asset paths (style.css/app.js) for standalone HTML previews.
app.mount("/", StaticFiles(directory="app/static", html=True), name="frontend")

