import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(os.getenv("DATABASE_PATH", "data/tracker.sqlite3"))


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db


def initialize():
    with connect() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS members (
                player_tag TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                role TEXT,
                town_hall_level INTEGER,
                last_seen TEXT DEFAULT CURRENT_TIMESTAMP,
                joined_clan_at TEXT,
                weekly_activity TEXT DEFAULT 'inaktiv',
                absence_start TEXT,
                absence_end TEXT,
                admin_comment TEXT DEFAULT '',
                is_current_clan INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS point_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                player_tag TEXT NOT NULL,
                event_key TEXT NOT NULL,
                category TEXT NOT NULL,
                description TEXT NOT NULL,
                points INTEGER NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(player_tag, event_key, category, description)
            );
            CREATE TABLE IF NOT EXISTS sync_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS events (
                event_key TEXT PRIMARY KEY,
                category TEXT NOT NULL,
                state TEXT NOT NULL,
                payload TEXT NOT NULL,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
        """)
        columns = {row["name"] for row in db.execute("PRAGMA table_info(members)")}
        for name, sql_type in (("joined_clan_at", "TEXT"), ("weekly_activity", "TEXT DEFAULT 'inaktiv'"), ("absence_start", "TEXT"), ("absence_end", "TEXT"), ("admin_comment", "TEXT DEFAULT ''"), ("is_current_clan", "INTEGER NOT NULL DEFAULT 1")):
            if name not in columns:
                db.execute(f"ALTER TABLE members ADD COLUMN {name} {sql_type}")


def remove_demo():
    with connect() as db:
        db.execute("DELETE FROM point_entries WHERE event_key='demo:legacy'")
        db.execute("DELETE FROM members WHERE player_tag IN ('#2L0P9Q8','#8VQ2Y0L','#9GJ8C2P','#2Y8P0RR','#Q8C0V2U') AND NOT EXISTS (SELECT 1 FROM point_entries p WHERE p.player_tag=members.player_tag)")


def dashboard_data():
    with connect() as db:
        members = db.execute("""
            SELECT m.player_tag, m.name, m.role, m.town_hall_level,
                   COALESCE(SUM(p.points), 0) AS points
            FROM members m LEFT JOIN point_entries p ON p.player_tag=m.player_tag
            WHERE m.is_current_clan=1
            GROUP BY m.player_tag ORDER BY points DESC, m.name COLLATE NOCASE
        """).fetchall()
        recent = db.execute("""
            SELECT p.player_tag, m.name, p.category, p.description, p.points, p.created_at
            FROM point_entries p JOIN members m ON m.player_tag=p.player_tag
            ORDER BY p.id DESC LIMIT 8
        """).fetchall()
    return {"members": [dict(x) for x in members], "recent": [dict(x) for x in recent]}


def upsert_member(tag, name, role=None, town_hall_level=None, is_current_clan=False):
    with connect() as db:
        previous = db.execute("SELECT is_current_clan FROM members WHERE player_tag=?", (tag,)).fetchone()
        joined_at = datetime.now(timezone.utc).isoformat() if is_current_clan and (previous is None or not previous["is_current_clan"]) else None
        db.execute("""INSERT INTO members(player_tag,name,role,town_hall_level,last_seen,is_current_clan,joined_clan_at)
            VALUES(?,?,?,?,CURRENT_TIMESTAMP,?,?) ON CONFLICT(player_tag) DO UPDATE SET
            name=excluded.name, role=COALESCE(excluded.role,members.role),
            town_hall_level=COALESCE(excluded.town_hall_level,members.town_hall_level),
            is_current_clan=CASE WHEN excluded.is_current_clan=1 THEN 1 ELSE members.is_current_clan END,
            joined_clan_at=COALESCE(excluded.joined_clan_at,members.joined_clan_at),
            last_seen=CURRENT_TIMESTAMP""", (tag, name, role, town_hall_level, int(is_current_clan), joined_at))
        if joined_at is not None and (previous is None):
            db.execute("""INSERT OR IGNORE INTO point_entries(player_tag,event_key,category,description,points)
                VALUES(?,?,?,?,?)""", (tag, "tracker:starting-points", "Bonus", "Startguthaben", 10))


def set_current_clan_members(tags):
    tags = list(dict.fromkeys(tags))
    with connect() as db:
        db.execute("UPDATE members SET is_current_clan=0")
        if tags:
            placeholders = ",".join("?" for _ in tags)
            db.execute(f"UPDATE members SET is_current_clan=1 WHERE player_tag IN ({placeholders})", tags)


def get_state(key):
    with connect() as db:
        row = db.execute("SELECT value FROM sync_state WHERE key=?", (key,)).fetchone()
        return row[0] if row else None


def set_state(key, value):
    with connect() as db:
        db.execute("INSERT INTO sync_state(key,value,updated_at) VALUES(?,?,CURRENT_TIMESTAMP) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=CURRENT_TIMESTAMP", (key, str(value)))


def save_event(event_key, category, state, payload):
    import json
    with connect() as db:
        db.execute("INSERT INTO events(event_key,category,state,payload,updated_at) VALUES(?,?,?,?,CURRENT_TIMESTAMP) ON CONFLICT(event_key) DO UPDATE SET state=excluded.state,payload=excluded.payload,updated_at=CURRENT_TIMESTAMP", (event_key, category, state, json.dumps(payload)))


def latest_event(category, states=None):
    import json
    with connect() as db:
        rows = db.execute("SELECT event_key,state,payload FROM events WHERE category=? ORDER BY updated_at DESC LIMIT 20", (category,)).fetchall()
    for row in rows:
        if states is None or row["state"] in states:
            return {"event_key": row["event_key"], "state": row["state"], "payload": json.loads(row["payload"])}
    return None


def current_member_tags():
    with connect() as db:
        return [row[0] for row in db.execute("SELECT player_tag FROM members WHERE is_current_clan=1")]


def member_joined_at(player_tag):
    with connect() as db:
        row = db.execute("""SELECT COALESCE(
                joined_clan_at,
                (SELECT MIN(created_at) FROM point_entries
                 WHERE player_tag=members.player_tag AND event_key='tracker:starting-points')
            ) FROM members WHERE player_tag=?""", (player_tag,)).fetchone()
        return row[0] if row else None


def remove_points(player_tag, event_key, category, description):
    with connect() as db:
        db.execute("DELETE FROM point_entries WHERE player_tag=? AND event_key=? AND category=? AND description=?",
                   (player_tag, event_key, category, description))


def book_points(player_tag, event_key, category, description, points):
    with connect() as db:
        member = db.execute("SELECT is_current_clan FROM members WHERE player_tag=?", (player_tag,)).fetchone()
        if not member or not member[0]:
            return False
        result = db.execute("INSERT OR IGNORE INTO point_entries(player_tag,event_key,category,description,points) VALUES(?,?,?,?,?)", (player_tag, event_key, category, description, points))
        return result.rowcount > 0


def replace_points(player_tag, event_key, category, description, points):
    with connect() as db:
        member = db.execute("SELECT is_current_clan FROM members WHERE player_tag=?", (player_tag,)).fetchone()
        if not member or not member[0]:
            return False
        db.execute("DELETE FROM point_entries WHERE player_tag=? AND event_key=? AND category=?", (player_tag, event_key, category))
        db.execute("INSERT INTO point_entries(player_tag,event_key,category,description,points) VALUES(?,?,?,?,?)", (player_tag, event_key, category, description, points))
        return True

