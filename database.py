"""SQLite storage for the OJT Journal."""
from contextlib import contextmanager
import json
import os
import sqlite3
import tempfile
from datetime import date, datetime, timedelta

import rules

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if os.environ.get("OJT_DATA_DIR"):
    DATA_DIR = os.path.abspath(os.environ["OJT_DATA_DIR"])
elif os.environ.get("VERCEL"):
    DATA_DIR = os.path.join(tempfile.gettempdir(), "ojt_journal_data")
else:
    DATA_DIR = os.path.join(BASE_DIR, "data")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
DB_PATH = os.path.join(DATA_DIR, "ojt_journal.db")

DEFAULT_VERIFIER_DIRECTORY = [
    {"name": "Luis D. Solmayor", "title": "Accounting Supervisor", "keywords": "luis, solmayor, accounting, acct"},
    {"name": "Jerwin Dominick A. Bernabe", "title": "IT Supervisor", "keywords": "jerwin, dominick, bernabe, it"},
    {"name": "Nikki Dela Cruz", "title": "", "keywords": "nikki, dela cruz"},
    {"name": "Jerry Apostol Jr.", "title": "", "keywords": "jerry, apostol"},
]

DEFAULT_SETTINGS = {
    "student_name": "Jeriel Maningas",
    "internship_site": "Aljay Agro-Industrial Solutions, Inc.",
    "start_date": "2026-11-16",
    "required_hours": "486",
    "prior_hours": "0",
    "supervisor_name": "Jerwin Dominick A. Bernabe",
    "supervisor_title": "IT Supervisor",
    "default_verifiers": "[]",
    "saved_verifiers": json.dumps(DEFAULT_VERIFIER_DIRECTORY),
    "groq_api_key": "",
    "groq_model": "openai/gpt-oss-120b",
    "default_morning_in": "08:00",
    "default_morning_out": "12:00",
    "default_afternoon_in": "13:00",
    "default_afternoon_out": "17:00",
    "phone_access": "0",
    "phone_pin": "",
    "secret_key": "",
    "last_modified_at": "",
    "last_exported_at": "",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS days (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    date          TEXT UNIQUE NOT NULL,
    morning_in    TEXT DEFAULT '',
    morning_out   TEXT DEFAULT '',
    afternoon_in  TEXT DEFAULT '',
    afternoon_out TEXT DEFAULT '',
    verifiers     TEXT DEFAULT '[]',
    notes         TEXT DEFAULT '',
    updated_at    TEXT
);
CREATE TABLE IF NOT EXISTS activities (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    day_id     INTEGER NOT NULL REFERENCES days(id) ON DELETE CASCADE,
    position   INTEGER DEFAULT 0,
    start_time TEXT DEFAULT '',
    end_time   TEXT DEFAULT '',
    minutes    INTEGER DEFAULT 0,
    raw_text   TEXT DEFAULT '',
    text       TEXT DEFAULT '',
    caption    TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS photos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    day_id      INTEGER NOT NULL REFERENCES days(id) ON DELETE CASCADE,
    activity_id INTEGER REFERENCES activities(id) ON DELETE SET NULL,
    kind        TEXT DEFAULT 'work',
    filename    TEXT NOT NULL,
    caption     TEXT DEFAULT '',
    position    INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS weeks (
    number INTEGER PRIMARY KEY,
    data   TEXT DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS audit_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    entity     TEXT NOT NULL,
    entity_id  TEXT NOT NULL,
    action     TEXT NOT NULL,
    actor      TEXT DEFAULT '',
    remark     TEXT DEFAULT '',
    created_at TEXT NOT NULL
);
"""

WEEK_FIELDS = [
    "status",
    "problems_raw", "solutions_raw", "goals_raw",
    "problems", "solutions", "goals",
    "duties", "new_trainings", "proposed", "accomplishments",
    "learning_activities", "learning_outcomes", "training",
]


@contextmanager
def connect():
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_db():
    with connect() as conn:
        conn.executescript(SCHEMA)
        for key, value in DEFAULT_SETTINGS.items():
            conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (key, value))
        row = conn.execute("SELECT value FROM settings WHERE key = 'secret_key'").fetchone()
        if not row or not row["value"]:
            import secrets
            conn.execute("UPDATE settings SET value = ? WHERE key = 'secret_key'", (secrets.token_hex(32),))


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------
def get_settings():
    with connect() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    data = dict(DEFAULT_SETTINGS)
    data.update({r["key"]: r["value"] for r in rows})
    if not data.get("groq_api_key") and os.environ.get("OJT_GROQ_API_KEY"):
        data["groq_api_key"] = os.environ["OJT_GROQ_API_KEY"].strip()
    return data


def save_settings(values):
    now = datetime.now().isoformat()
    meta_only = set(values.keys()).issubset({"last_modified_at", "last_exported_at"})
    with connect() as conn:
        for key, value in values.items():
            conn.execute("INSERT INTO settings(key, value) VALUES (?, ?) "
                         "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))
        if not meta_only:
            conn.execute("INSERT INTO settings(key, value) VALUES ('last_modified_at', ?) "
                         "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (now,))


def touch_modified(conn=None):
    now = datetime.now().isoformat()
    if conn is not None:
        conn.execute("INSERT INTO settings(key, value) VALUES ('last_modified_at', ?) "
                     "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (now,))
    else:
        save_settings({"last_modified_at": now})


def mark_exported():
    now = datetime.now().isoformat()
    save_settings({"last_exported_at": now})


def needs_export(settings=None):
    settings = settings or get_settings()
    mod = (settings.get("last_modified_at") or "").strip()
    exp = (settings.get("last_exported_at") or "").strip()
    if not mod:
        return False
    return (not exp) or (mod > exp)


def default_verifiers(settings=None):
    settings = settings or get_settings()
    try:
        items = json.loads(settings.get("default_verifiers") or "[]")
    except ValueError:
        items = []
    return [v for v in items if v.get("name")]


def saved_verifiers(settings=None):
    """Return the saved verifier directory (for smart type-to-fill autocomplete)."""
    settings = settings or get_settings()
    try:
        items = json.loads(settings.get("saved_verifiers") or "[]")
    except ValueError:
        items = []
    seen = {}
    out = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        name = (raw.get("name") or "").strip()
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        entry = {
            "name": name,
            "title": (raw.get("title") or "").strip(),
            "keywords": (raw.get("keywords") or "").strip(),
        }
        seen[key] = entry
        out.append(entry)
    return out


def remember_verifiers(verifiers):
    """Merge newly entered verifiers into the saved directory so future entries auto-fill them."""
    if not verifiers:
        return
    current = saved_verifiers()
    by_key = {v["name"].lower(): v for v in current}
    changed = False
    for v in verifiers:
        name = (v.get("name") or "").strip()
        title = (v.get("title") or "").strip()
        if not name:
            continue
        key = name.lower()
        if key in by_key:
            if title and not by_key[key]["title"]:
                by_key[key]["title"] = title
                changed = True
        else:
            first_word = name.split()[0].lower()
            entry = {"name": name, "title": title, "keywords": first_word}
            current.append(entry)
            by_key[key] = entry
            changed = True
    if changed:
        save_settings({"saved_verifiers": json.dumps(current)})


# --------------------------------------------------------------------------
# Date helpers
# --------------------------------------------------------------------------
def parse_date(value):
    return datetime.strptime(value, "%Y-%m-%d").date()


def start_date(settings=None):
    settings = settings or get_settings()
    try:
        return parse_date(settings["start_date"])
    except (ValueError, KeyError):
        return date.today()


def week_monday(settings=None):
    s = start_date(settings)
    return s - timedelta(days=s.weekday())


def week_number(d, settings=None):
    return (d - week_monday(settings)).days // 7 + 1


def week_range(number, settings=None):
    monday = week_monday(settings) + timedelta(weeks=number - 1)
    return monday, monday + timedelta(days=6)


def minutes_between(start, end):
    return rules.minutes_between(start, end)


# --------------------------------------------------------------------------
# Days, activities, photos
# --------------------------------------------------------------------------
def _day_dict(conn, row, day_numbers=None):
    d = dict(row)
    d["date_obj"] = parse_date(d["date"])
    try:
        d["verifiers"] = json.loads(d.get("verifiers") or "[]")
    except ValueError:
        d["verifiers"] = []
    acts = conn.execute("SELECT * FROM activities WHERE day_id = ? ORDER BY position, id",
                        (d["id"],)).fetchall()
    photos = conn.execute("SELECT * FROM photos WHERE day_id = ? ORDER BY position, id",
                          (d["id"],)).fetchall()
    d["activities"] = [dict(a) for a in acts]
    d["photos"] = [dict(p) for p in photos if p["kind"] == "work"]
    d["ncis"] = [dict(p) for p in photos if p["kind"] == "ncis"]
    for a in d["activities"]:
        a["photos"] = [p for p in d["photos"] if p["activity_id"] == a["id"]]
    d["loose_photos"] = [p for p in d["photos"] if not p["activity_id"]]
    d["minutes"] = rules.day_minutes(d["activities"])
    if day_numbers is not None:
        d["day_number"] = day_numbers.get(d["date"])
    return d


def day_numbers(conn):
    rows = conn.execute("SELECT date FROM days ORDER BY date").fetchall()
    return {r["date"]: i + 1 for i, r in enumerate(rows)}


def get_day(date_str):
    with connect() as conn:
        row = conn.execute("SELECT * FROM days WHERE date = ?", (date_str,)).fetchone()
        if not row:
            return None
        return _day_dict(conn, row, day_numbers(conn))


def list_days(start=None, end=None):
    with connect() as conn:
        nums = day_numbers(conn)
        sql, args = "SELECT * FROM days", []
        if start and end:
            sql += " WHERE date BETWEEN ? AND ?"
            args = [start.isoformat(), end.isoformat()]
        rows = conn.execute(sql + " ORDER BY date", args).fetchall()
        return [_day_dict(conn, r, nums) for r in rows]


def total_minutes():
    with connect() as conn:
        row = conn.execute("SELECT COALESCE(SUM(minutes), 0) AS m FROM activities").fetchone()
    return row["m"]


def upsert_day(original_date, values):
    """Create or update a day. Returns the day id."""
    with connect() as conn:
        now = datetime.now().isoformat(timespec="seconds")
        row = None
        if original_date:
            row = conn.execute("SELECT id FROM days WHERE date = ?", (original_date,)).fetchone()
        if row:
            conn.execute("""UPDATE days SET date=?, morning_in=?, morning_out=?, afternoon_in=?,
                            afternoon_out=?, verifiers=?, notes=?, updated_at=? WHERE id=?""",
                         (values["date"], values["morning_in"], values["morning_out"],
                          values["afternoon_in"], values["afternoon_out"],
                          json.dumps(values["verifiers"]), values.get("notes", ""), now, row["id"]))
            touch_modified(conn)
            return row["id"]
        cur = conn.execute("""INSERT INTO days(date, morning_in, morning_out, afternoon_in,
                              afternoon_out, verifiers, notes, updated_at)
                              VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                           (values["date"], values["morning_in"], values["morning_out"],
                            values["afternoon_in"], values["afternoon_out"],
                            json.dumps(values["verifiers"]), values.get("notes", ""), now))
        touch_modified(conn)
        return cur.lastrowid


def date_taken(date_str, except_date=None):
    with connect() as conn:
        row = conn.execute("SELECT date FROM days WHERE date = ?", (date_str,)).fetchone()
    return bool(row) and row["date"] != except_date


def save_activities(day_id, items):
    """items: list of dicts (id may be None). Returns {client_key: activity_id}."""
    keys = {}
    removed_files = []
    with connect() as conn:
        existing = {r["id"] for r in conn.execute("SELECT id FROM activities WHERE day_id = ?",
                                                  (day_id,)).fetchall()}
        kept = set()
        for pos, it in enumerate(items):
            minutes = rules.activity_minutes(it.get("start", ""), it.get("end", ""), it.get("minutes") or 0)
            fields = (pos, it.get("start", ""), it.get("end", ""), minutes,
                      it.get("raw", ""), it.get("text", ""), it.get("caption", ""))
            aid = it.get("id")
            if aid and int(aid) in existing:
                aid = int(aid)
                conn.execute("""UPDATE activities SET position=?, start_time=?, end_time=?, minutes=?,
                                raw_text=?, text=?, caption=? WHERE id=?""", fields + (aid,))
            else:
                cur = conn.execute("""INSERT INTO activities(position, start_time, end_time, minutes,
                                      raw_text, text, caption, day_id) VALUES (?,?,?,?,?,?,?,?)""",
                                   fields + (day_id,))
                aid = cur.lastrowid
            kept.add(aid)
            keys[str(it.get("key"))] = aid
        for aid in existing - kept:
            for p in conn.execute("SELECT filename FROM photos WHERE activity_id = ?", (aid,)):
                removed_files.append(p["filename"])
            conn.execute("DELETE FROM photos WHERE activity_id = ?", (aid,))
            conn.execute("DELETE FROM activities WHERE id = ?", (aid,))
    return keys, removed_files


def add_photo(day_id, filename, kind="work", activity_id=None, caption=""):
    with connect() as conn:
        conn.execute("INSERT INTO photos(day_id, activity_id, kind, filename, caption) VALUES (?,?,?,?,?)",
                     (day_id, activity_id, kind, filename, caption))


def update_photo(photo_id, caption):
    with connect() as conn:
        conn.execute("UPDATE photos SET caption = ? WHERE id = ?", (caption, photo_id))


def delete_photo(photo_id):
    with connect() as conn:
        row = conn.execute("SELECT filename FROM photos WHERE id = ?", (photo_id,)).fetchone()
        conn.execute("DELETE FROM photos WHERE id = ?", (photo_id,))
    return row["filename"] if row else None


def delete_day(date_str):
    with connect() as conn:
        row = conn.execute("SELECT id FROM days WHERE date = ?", (date_str,)).fetchone()
        if not row:
            return []
        files = [p["filename"] for p in conn.execute("SELECT filename FROM photos WHERE day_id = ?",
                                                     (row["id"],))]
        conn.execute("DELETE FROM days WHERE id = ?", (row["id"],))
        touch_modified(conn)
    return files


# --------------------------------------------------------------------------
# Weeks
# --------------------------------------------------------------------------
def get_week_data(number):
    with connect() as conn:
        row = conn.execute("SELECT data FROM weeks WHERE number = ?", (number,)).fetchone()
    data = {}
    if row:
        try:
            data = json.loads(row["data"] or "{}")
        except ValueError:
            data = {}
    for f in WEEK_FIELDS:
        if f == "status":
            data.setdefault(f, "draft")
        elif f in ("problems_raw", "solutions_raw", "goals_raw"):
            data.setdefault(f, "")
        else:
            data.setdefault(f, [])
    if data.get("status") not in rules.WEEK_STATUSES:
        data["status"] = "draft"
    return data


def save_week_data(number, data):
    with connect() as conn:
        conn.execute("INSERT INTO weeks(number, data) VALUES (?, ?) "
                     "ON CONFLICT(number) DO UPDATE SET data = excluded.data",
                     (number, json.dumps(data)))
        touch_modified(conn)


def is_week_locked(number):
    return get_week_data(number).get("status") in ("submitted", "approved")


def add_audit(entity, entity_id, action, actor="", remark=""):
    now = datetime.now().isoformat(timespec="seconds")
    with connect() as conn:
        conn.execute(
            "INSERT INTO audit_log(entity, entity_id, action, actor, remark, created_at) VALUES (?,?,?,?,?,?)",
            (str(entity), str(entity_id), str(action), (actor or "").strip(), (remark or "").strip(), now),
        )


def list_audit(entity=None, entity_id=None, limit=30):
    sql = "SELECT * FROM audit_log"
    args = []
    clauses = []
    if entity is not None:
        clauses.append("entity = ?")
        args.append(str(entity))
    if entity_id is not None:
        clauses.append("entity_id = ?")
        args.append(str(entity_id))
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(int(limit))
    with connect() as conn:
        rows = conn.execute(sql, args).fetchall()
    return [dict(r) for r in rows]
