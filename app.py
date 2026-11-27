"""
OJT Journal - AI-assisted OJT daily activity and weekly documentation system.
Run:  python app.py   then open http://127.0.0.1:5000
"""
import io
import json
import math
import os
import re
import secrets
import shutil
import socket
import sqlite3
import tempfile
import threading
import time
import uuid
import webbrowser
import zipfile
from datetime import date, datetime, timedelta

from flask import (Flask, abort, flash, jsonify, redirect, render_template, request,
                   send_file, send_from_directory, session, url_for)
from PIL import Image, ImageOps
from werkzeug.middleware.proxy_fix import ProxyFix

try:  # iPhone HEIC photos (optional)
    from pillow_heif import register_heif_opener
    register_heif_opener()
    HEIC_OK = True
except ImportError:
    HEIC_OK = False

import ai_helper
import database as db
import docgen
import rules

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS = {"style.css", "app.js", "manifest.webmanifest", "icon-192.png", "icon-512.png",
          "apple-touch-icon.png"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".heic", ".heif"}
LOCAL_ADDRS = {"127.0.0.1", "::1", "::ffff:127.0.0.1"}
PORT = 5000
IS_VERCEL = bool(os.environ.get("VERCEL"))
IS_CLOUD = bool(
    os.environ.get("PYTHONANYWHERE_DOMAIN")
    or os.environ.get("PYTHONANYWHERE_SITE")
    or os.environ.get("OJT_CLOUD") == "1"
    or IS_VERCEL
)

app = Flask(__name__, template_folder=BASE_DIR, static_folder=None)
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.config["MAX_CONTENT_LENGTH"] = 300 * 1024 * 1024
app.config["PERMANENT_SESSION_LIFETIME"] = 60 * 60 * 24 * 30
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
if IS_CLOUD:
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
db.init_db()
app.secret_key = os.environ.get("OJT_SECRET_KEY") or db.get_settings()["secret_key"]


# --------------------------------------------------------------------------
# Phone / Cloud access with PIN
# --------------------------------------------------------------------------
def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def is_local_request():
    if IS_CLOUD:
        return False
    return request.remote_addr in LOCAL_ADDRS


def active_pin(settings=None):
    env_pin = (os.environ.get("OJT_PIN") or "").strip()
    if env_pin:
        return env_pin
    settings = settings or db.get_settings()
    return (settings.get("phone_pin") or "").strip()


@app.before_request
def phone_guard():
    if is_local_request() or request.endpoint in ("assets", "phone_login", "logout"):
        return None
    settings = db.get_settings()
    pin = active_pin(settings)
    if IS_CLOUD:
        if not pin:
            return redirect(url_for("phone_login"))
        if not session.get("phone_ok"):
            return redirect(url_for("phone_login", next=request.full_path))
        return None
    if settings.get("phone_access") != "1" or not pin:
        return render_template("phone_login.html", blocked=True, setup_mode=False), 403
    if not session.get("phone_ok"):
        return redirect(url_for("phone_login", next=request.full_path))
    return None


@app.route("/phone-login", methods=["GET", "POST"])
def phone_login():
    settings = db.get_settings()
    pin_saved = active_pin(settings)
    setup_mode = IS_CLOUD and not pin_saved
    blocked = (not IS_CLOUD) and (settings.get("phone_access") != "1" or not pin_saved)
    if blocked and not is_local_request():
        return render_template("phone_login.html", blocked=True, setup_mode=False), 403
    error = None
    if request.method == "POST":
        if setup_mode:
            new_pin = request.form.get("pin", "").strip()
            confirm = request.form.get("pin_confirm", "").strip()
            if not new_pin.isdigit() or not 4 <= len(new_pin) <= 8:
                error = "PIN must be 4 to 8 digits."
            elif new_pin != confirm:
                error = "PINs do not match. Try again."
            else:
                db.save_settings({"phone_pin": new_pin, "phone_access": "1"})
                session.permanent = True
                session["phone_ok"] = True
                flash("PIN set! Your OJT Journal is now protected.", "success")
                return redirect(url_for("dashboard"))
        else:
            pin = request.form.get("pin", "").strip()
            if pin_saved and secrets.compare_digest(pin, pin_saved):
                session.permanent = True
                session["phone_ok"] = True
                nxt = request.args.get("next") or "/"
                return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else "/")
            time.sleep(1)
            error = "Wrong PIN. Try again."
    return render_template("phone_login.html", blocked=False, setup_mode=setup_mode, error=error)


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("phone_login"))


def phone_qr_data_uri(url):
    try:
        import base64
        import qrcode
        img = qrcode.make(url, box_size=6, border=2)
        buf = io.BytesIO()
        img.save(buf, "PNG")
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return None


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def fmt_minutes(minutes):
    return rules.fmt_minutes(minutes)


def nice_date(d):
    return f"{d:%a}, {d:%b} {d.day}, {d.year}"


app.jinja_env.globals.update(fmt_minutes=fmt_minutes, nice_date=nice_date,
                             long_date=docgen.long_date, range_compact=docgen.range_compact)


@app.context_processor
def inject_globals():
    settings = db.get_settings()
    nav_week = 1
    if date.today() >= db.start_date(settings):
        nav_week = db.week_number(date.today(), settings)
    return {
        "settings": settings,
        "today": date.today(),
        "nav_week": nav_week,
        "is_cloud": IS_CLOUD,
        "is_vercel": IS_VERCEL,
        "needs_export": db.needs_export(settings),
    }


def lines(text):
    return [x.strip() for x in (text or "").splitlines() if x.strip()]


def save_upload(file_storage, day_date, kind):
    """Save one uploaded image. Returns relative filename or None."""
    if not file_storage or not file_storage.filename:
        return None
    ext = os.path.splitext(file_storage.filename)[1].lower()
    if ext not in IMAGE_EXT:
        flash(f"Skipped '{file_storage.filename}': only JPG, PNG, WEBP, BMP or GIF images are allowed.",
              "warning")
        return None
    try:
        img = Image.open(file_storage.stream)
        img = ImageOps.exif_transpose(img)
    except Exception:
        flash(f"Skipped '{file_storage.filename}': the image could not be opened.", "warning")
        return None
    folder = os.path.join(db.UPLOAD_DIR, day_date)
    os.makedirs(folder, exist_ok=True)
    if kind == "ncis":
        name = f"ncis_{uuid.uuid4().hex[:10]}.png"
        if img.mode not in ("RGB", "RGBA", "L"):
            img = img.convert("RGBA")
        img.thumbnail((2400, 2400))
        img.save(os.path.join(folder, name), "PNG", optimize=True)
    else:
        name = f"{uuid.uuid4().hex[:12]}.jpg"
        if img.mode != "RGB":
            img = img.convert("RGB")
        img.thumbnail((2000, 2000))
        img.save(os.path.join(folder, name), "JPEG", quality=88)
    return f"{day_date}/{name}"


def remove_files(filenames):
    for name in filenames:
        if not name:
            continue
        path = os.path.join(db.UPLOAD_DIR, name)
        if os.path.isfile(path):
            try:
                os.remove(path)
            except OSError:
                pass


def move_day_folder(old_date, new_date):
    """When the date of an entry changes, keep photo paths valid."""
    with db.connect() as conn:
        rows = conn.execute("SELECT p.id AS id, p.filename AS filename FROM photos p JOIN days d ON d.id = p.day_id "
                            "WHERE d.date = ?", (new_date,)).fetchall()
        for r in rows:
            if r["filename"].startswith(old_date + "/"):
                new_name = new_date + r["filename"][len(old_date):]
                src = os.path.join(db.UPLOAD_DIR, r["filename"])
                dst = os.path.join(db.UPLOAD_DIR, new_name)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                if os.path.exists(src):
                    os.replace(src, dst)
                conn.execute("UPDATE photos SET filename = ? WHERE id = ?", (new_name, r["id"]))


def progress_stats():
    settings = db.get_settings()
    days = db.list_days()
    prog = rules.compute_progress(
        days,
        required_hours=settings.get("required_hours") or 486,
        prior_hours=settings.get("prior_hours") or 0,
    )
    start = db.start_date(settings)
    current_week = max(1, db.week_number(date.today(), settings)) if date.today() >= start else 1
    return {
        "days": days, "start": start, "current_week": current_week, **prog,
    }


def week_summaries(days, settings):
    weeks = {}
    for d in days:
        n = db.week_number(d["date_obj"], settings)
        w = weeks.setdefault(n, {"number": n, "days": [], "minutes": 0})
        w["days"].append(d)
        w["minutes"] += d["minutes"]
    out = []
    for n in sorted(weeks):
        mon, sun = db.week_range(n, settings)
        w = weeks[n]
        w["start"], w["end"] = mon, mon + timedelta(days=4)
        data = db.get_week_data(n)
        w["status"] = data.get("status", "draft")
        w["status_label"] = rules.WEEK_STATUS_LABELS.get(w["status"], "Draft")
        w["ready"] = bool(data.get("duties")) and bool(data.get("problems") or data.get("problems_raw"))
        out.append(w)
    return out


def week_bundle(n):
    """Everything docgen needs for one week."""
    settings = db.get_settings()
    mon, sun = db.week_range(n, settings)
    days = db.list_days(mon, sun)
    data = db.get_week_data(n)
    end = mon + timedelta(days=4)
    if days and days[-1]["date_obj"] > end:
        end = days[-1]["date_obj"]

    out_days = []
    for d in days:
        acts = [a for a in d["activities"] if (a["text"] or a["raw_text"]).strip()]
        photos = []
        for a in d["activities"]:
            for p in a["photos"]:
                photos.append({"path": os.path.join(db.UPLOAD_DIR, p["filename"]),
                               "caption": p["caption"] or a["caption"] or a["text"] or a["raw_text"]})
        for p in d["loose_photos"]:
            photos.append({"path": os.path.join(db.UPLOAD_DIR, p["filename"]), "caption": p["caption"]})
        out_days.append({
            "date": d["date_obj"],
            "morning_in": d["morning_in"], "morning_out": d["morning_out"],
            "afternoon_in": d["afternoon_in"], "afternoon_out": d["afternoon_out"],
            "minutes": d["minutes"],
            "activities": [{"text": a["text"] or a["raw_text"], "caption": a["caption"],
                            "minutes": a["minutes"]} for a in acts],
            "verifiers": d["verifiers"],
            "photos": photos,
            "ncis": [{"path": os.path.join(db.UPLOAD_DIR, p["filename"]),
                      "label": (p["caption"] or "").strip()} for p in d["ncis"]],
        })

    all_acts = []
    for d in out_days:
        for a in d["activities"]:
            if a["text"] not in all_acts:
                all_acts.append(a["text"])

    def pick(key, fallback=None):
        value = data.get(key)
        return value if value else (fallback or [])

    return {
        "number": n, "start": mon, "end": end,
        "student_name": settings["student_name"], "site": settings["internship_site"],
        "supervisor_name": settings["supervisor_name"], "supervisor_title": settings["supervisor_title"],
        "days": out_days,
        "duties": pick("duties", all_acts),
        "new_trainings": pick("new_trainings"),
        "proposed": pick("proposed"),
        "accomplishments": pick("accomplishments"),
        "problems": pick("problems", lines(data.get("problems_raw"))),
        "solutions": pick("solutions", lines(data.get("solutions_raw"))),
        "goals": pick("goals", lines(data.get("goals_raw"))),
        "learning_activities": pick("learning_activities", all_acts),
        "learning_outcomes": pick("learning_outcomes"),
        "training": pick("training"),
    }


def week_trainers(days):
    names = []
    for d in days:
        for v in d["verifiers"]:
            if v.get("name") and v["name"] not in names:
                names.append(v["name"])
    return names


# --------------------------------------------------------------------------
# Pages
# --------------------------------------------------------------------------
@app.route("/")
def dashboard():
    settings = db.get_settings()
    stats = progress_stats()
    today_entry = db.get_day(date.today().isoformat())
    weeks = week_summaries(stats["days"], settings)
    recent = list(reversed(stats["days"]))[:5]
    return render_template("dashboard.html", stats=stats, today_entry=today_entry,
                           weeks=weeks, recent=recent)


@app.route("/entry")
def entry_today():
    settings = db.get_settings()
    d = max(date.today(), db.start_date(settings))
    return redirect(url_for("entry", date_str=d.isoformat()))


@app.route("/entry/<date_str>", methods=["GET", "POST"])
def entry(date_str):
    settings = db.get_settings()
    try:
        current_date = db.parse_date(date_str)
    except ValueError:
        abort(404)
    day = db.get_day(date_str)

    if request.method == "POST":
        new_date = request.form.get("date") or date_str
        try:
            new_date_obj = db.parse_date(new_date)
        except ValueError:
            flash("Please choose a valid date.", "error")
            return redirect(url_for("entry", date_str=date_str))
        if new_date_obj < db.start_date(settings):
            flash("That date is before your OJT start date (see Settings).", "error")
            return redirect(url_for("entry", date_str=date_str))
        orig_week = db.week_number(current_date, settings)
        target_week = db.week_number(new_date_obj, settings)
        if db.is_week_locked(orig_week) or db.is_week_locked(target_week):
            locked_no = orig_week if db.is_week_locked(orig_week) else target_week
            flash(f"Week {locked_no} is locked (Submitted/Approved). Reopen Week {locked_no} with a remark before editing entries.", "error")
            return redirect(url_for("entry", date_str=date_str))
        if new_date != date_str and db.date_taken(new_date):
            flash(f"There is already an entry for {nice_date(new_date_obj)}.", "error")
            return redirect(url_for("entry", date_str=date_str))

        names = request.form.getlist("verifier_name")
        titles = request.form.getlist("verifier_title")
        verifiers = [{"name": n.strip(), "title": t.strip()} for n, t in zip(names, titles) if n.strip()]
        db.remember_verifiers(verifiers)
        day_id = db.upsert_day(date_str if day else None, {
            "date": new_date,
            "morning_in": request.form.get("morning_in", ""),
            "morning_out": request.form.get("morning_out", ""),
            "afternoon_in": request.form.get("afternoon_in", ""),
            "afternoon_out": request.form.get("afternoon_out", ""),
            "verifiers": verifiers,
            "notes": request.form.get("notes", ""),
        })
        if day and new_date != date_str:
            move_day_folder(date_str, new_date)

        try:
            items = json.loads(request.form.get("activities_json") or "[]")
        except ValueError:
            items = []
        items = [i for i in items if (i.get("raw") or i.get("text") or "").strip()]
        keys, removed = db.save_activities(day_id, items)
        remove_files(removed)

        # existing photo edits / deletions
        for key in list(request.form.keys()):
            if key.startswith("pcap_"):
                db.update_photo(int(key[5:]), request.form[key].strip())
        for key in request.form.keys():
            if key.startswith("pdel_"):
                remove_files([db.delete_photo(int(key[5:]))])

        # new uploads
        for key, act_id in keys.items():
            for f in request.files.getlist(f"photos_{key}"):
                name = save_upload(f, new_date, "work")
                if name:
                    db.add_photo(day_id, name, "work", act_id)
        ncis_label = request.form.get("ncis_label", "").strip()
        for f in request.files.getlist("ncis_files"):
            name = save_upload(f, new_date, "ncis")
            if name:
                db.add_photo(day_id, name, "ncis", caption=ncis_label)

        db.add_audit("week", str(target_week), f"Saved daily entry ({new_date})", settings.get("student_name", ""))
        flash("Entry saved.", "success")
        unpolished = sum(1 for i in items if not (i.get("text") or "").strip())
        if unpolished:
            flash(f"{unpolished} activit{'ies have' if unpolished > 1 else 'y has'} no English report text yet. "
                  "Click ✨ Polish all with AI (or type it) so your documents are in English.", "warning")
        if request.form.get("after") == "dashboard":
            return redirect(url_for("dashboard"))
        return redirect(url_for("entry", date_str=new_date))

    if day is None:
        with db.connect() as conn:
            nums = db.day_numbers(conn)
        day_no = sum(1 for k in nums if k < date_str) + 1
        day = {
            "date": date_str, "date_obj": current_date, "day_number": day_no, "is_new": True,
            "morning_in": settings["default_morning_in"], "morning_out": settings["default_morning_out"],
            "afternoon_in": settings["default_afternoon_in"],
            "afternoon_out": settings["default_afternoon_out"],
            "verifiers": db.default_verifiers(settings), "activities": [], "photos": [],
            "loose_photos": [], "ncis": [], "minutes": 0, "notes": "",
        }
    week_no = db.week_number(current_date, settings)
    validation = rules.validate_day(day, db.start_date(settings)) if not day.get("is_new") else {"errors": [], "warnings": [], "info": []}
    return render_template("entry.html", day=day, week_no=week_no,
                           saved_verifiers=db.saved_verifiers(settings),
                           validation=validation, week_locked=db.is_week_locked(week_no),
                           before_start=current_date < db.start_date(settings),
                           prev_date=(current_date - timedelta(days=1)).isoformat(),
                           next_date=(current_date + timedelta(days=1)).isoformat())


@app.route("/entry/<date_str>/delete", methods=["POST"])
def delete_entry(date_str):
    settings = db.get_settings()
    try:
        wk_no = db.week_number(db.parse_date(date_str), settings)
    except ValueError:
        wk_no = None
    if wk_no and db.is_week_locked(wk_no):
        flash(f"Week {wk_no} is locked. Reopen Week {wk_no} with a remark before deleting an entry.", "error")
        return redirect(url_for("entry", date_str=date_str))
    remove_files(db.delete_day(date_str))
    if wk_no:
        db.add_audit("week", str(wk_no), f"Deleted daily entry ({date_str})", settings.get("student_name", ""))
    flash("Entry deleted.", "success")
    return redirect(url_for("days"))


@app.route("/days")
def days():
    settings = db.get_settings()
    all_days = db.list_days()
    weeks = list(reversed(week_summaries(all_days, settings)))
    return render_template("days.html", weeks=weeks)


def _apply_week_fields(data, source, is_json=False):
    """Apply weekly report fields from form data or autosave JSON onto week dict."""
    for key in ("problems_raw", "solutions_raw", "goals_raw"):
        data[key] = str(source.get(key) or "")
    for key in ("problems", "solutions", "goals", "duties", "new_trainings", "proposed",
                "learning_activities", "learning_outcomes"):
        raw = source.get(key)
        data[key] = [str(x).strip() for x in raw if str(x).strip()] if isinstance(raw, list) else lines(raw)
    acc = source.get("accomplishments")
    if isinstance(acc, list):
        data["accomplishments"] = [str(p).strip() for p in acc if str(p).strip()]
    else:
        acc_text = str(acc or "").replace("\r\n", "\n")
        data["accomplishments"] = [p.strip() for p in re.split(r"\n\s*\n", acc_text) if p.strip()]
    if is_json:
        training = source.get("training") if isinstance(source.get("training"), list) else []
    else:
        try:
            training = json.loads(source.get("training_json") or "[]")
        except ValueError:
            training = []
    clean_training = []
    for t in training:
        if not isinstance(t, dict):
            continue
        cat = str(t.get("category") or "").strip()
        how = t.get("how") if isinstance(t.get("how"), list) else lines(t.get("how"))
        trainers = t.get("trainers") if isinstance(t.get("trainers"), list) else lines(t.get("trainers"))
        raw_tl = t.get("timeline")
        timeline = [str(x).strip() for x in raw_tl if str(x).strip()] if isinstance(raw_tl, list) else lines(raw_tl)
        outputs = t.get("outputs") if isinstance(t.get("outputs"), list) else lines(t.get("outputs"))
        if cat or how or trainers or timeline or outputs:
            clean_training.append({
                "category": cat,
                "how": [str(x).strip() for x in how if str(x).strip()],
                "trainers": [str(x).strip() for x in trainers if str(x).strip()],
                "timeline": timeline,
                "outputs": [str(x).strip() for x in outputs if str(x).strip()],
            })
    data["training"] = clean_training
    return data


@app.route("/week/<int:n>", methods=["GET", "POST"])
def week(n):
    if n < 1:
        abort(404)
    settings = db.get_settings()
    mon, sun = db.week_range(n, settings)
    days_in_week = db.list_days(mon, sun)

    if request.method == "POST":
        data = db.get_week_data(n)
        locked = data.get("status") in ("submitted", "approved")
        action = request.form.get("action") or "save"

        if not locked:
            _apply_week_fields(data, request.form, is_json=False)
            db.save_week_data(n, data)
            db.add_audit("week", str(n), "Saved weekly report", settings.get("student_name", ""))
        elif action != "download":
            flash(f"Week {n} is locked ({rules.WEEK_STATUS_LABELS.get(data.get('status'), 'Locked')}). Reopen it with a remark to make edits.", "error")
            return redirect(url_for("week", n=n))

        if action == "download":
            validation = rules.validate_week(days_in_week, data, settings)
            if validation["errors"]:
                for err in validation["errors"]:
                    flash(err, "error")
                return redirect(url_for("week", n=n))
            db.add_audit("week", str(n), "Downloaded WEEK ZIP pack", settings.get("student_name", ""))
            payload = docgen.build_week_zip(week_bundle(n), BASE_DIR)
            return send_file(io.BytesIO(payload), mimetype="application/zip",
                             as_attachment=True, download_name=f"WEEK {n}.zip")
        flash("Week saved.", "success")
        return redirect(url_for("week", n=n))

    data = db.get_week_data(n)
    end = mon + timedelta(days=4)
    if days_in_week and days_in_week[-1]["date_obj"] > end:
        end = days_in_week[-1]["date_obj"]
    total = rules.week_minutes(days_in_week)
    last_week = max([db.week_number(d["date_obj"], settings) for d in db.list_days()] or [1])
    unpolished = sum(1 for d in days_in_week for a in d["activities"]
                     if a["raw_text"].strip() and not a["text"].strip())
    validation = rules.validate_week(days_in_week, data, settings)
    status = data.get("status", "draft")
    locked = status in ("submitted", "approved")
    return render_template("week.html", n=n, mon=mon, end=end, days=days_in_week, data=data,
                           unpolished=unpolished, validation=validation,
                           status=status, status_label=rules.WEEK_STATUS_LABELS.get(status, "Draft"),
                           locked=locked, audit=db.list_audit("week", str(n)),
                           total=total, trainers=week_trainers(days_in_week),
                           saved_verifiers=db.saved_verifiers(settings),
                           has_prev=n > 1, has_next=n < max(last_week, progress_stats()["current_week"]))


@app.route("/week/<int:n>/status", methods=["POST"])
def week_status(n):
    if n < 1:
        abort(404)
    settings = db.get_settings()
    target = (request.form.get("status") or "").strip().lower()
    remark = (request.form.get("remark") or "").strip()
    if target not in rules.WEEK_STATUSES:
        flash("Invalid workflow status.", "error")
        return redirect(url_for("week", n=n))
    data = db.get_week_data(n)
    current = data.get("status", "draft")
    mon, sun = db.week_range(n, settings)
    days_in_week = db.list_days(mon, sun)

    # Reopening a locked week requires a remark
    if current in ("submitted", "approved") and target in ("draft", "ready"):
        if not remark:
            flash("Please enter a remark explaining why this week is being reopened.", "error")
            return redirect(url_for("week", n=n))
    # Submitting/approving requires no blocking errors
    if target in ("submitted", "approved"):
        validation = rules.validate_week(days_in_week, data, settings)
        if validation["errors"]:
            for err in validation["errors"]:
                flash(err, "error")
            return redirect(url_for("week", n=n))

    data["status"] = target
    db.save_week_data(n, data)
    action_label = f"Status: {rules.WEEK_STATUS_LABELS.get(current, current)} → {rules.WEEK_STATUS_LABELS.get(target, target)}"
    db.add_audit("week", str(n), action_label, settings.get("student_name", ""), remark)
    flash(f"Week {n} marked as {rules.WEEK_STATUS_LABELS.get(target, target)}.", "success")
    return redirect(url_for("week", n=n))


@app.route("/settings", methods=["GET", "POST"])
def settings_page():
    if request.method == "POST":
        names = request.form.getlist("verifier_name")
        titles = request.form.getlist("verifier_title")
        verifiers = [{"name": a.strip(), "title": b.strip()} for a, b in zip(names, titles) if a.strip()]
        sv_names = request.form.getlist("sv_name")
        sv_titles = request.form.getlist("sv_title")
        sv_keywords = request.form.getlist("sv_keywords")
        saved_list = [
            {"name": a.strip(), "title": b.strip(), "keywords": c.strip()}
            for a, b, c in zip(sv_names, sv_titles, sv_keywords) if a.strip()
        ]
        values = {k: request.form.get(k, "").strip() for k in (
            "student_name", "internship_site", "start_date", "required_hours", "prior_hours",
            "supervisor_name", "supervisor_title", "groq_model",
            "default_morning_in", "default_morning_out", "default_afternoon_in",
            "default_afternoon_out")}
        try:
            db.parse_date(values["start_date"])
        except ValueError:
            flash("Please enter a valid start date.", "error")
            return redirect(url_for("settings_page"))
        try:
            prior = max(0.0, float(values["prior_hours"] or 0))
            values["prior_hours"] = str(int(prior)) if prior.is_integer() else str(prior)
        except ValueError:
            values["prior_hours"] = "0"
        values["default_verifiers"] = json.dumps(verifiers)
        values["saved_verifiers"] = json.dumps(saved_list)
        pin = request.form.get("phone_pin", "").strip()
        if pin:
            if not pin.isdigit() or not 4 <= len(pin) <= 8:
                flash("The phone PIN must be 4 to 8 digits.", "error")
                return redirect(url_for("settings_page"))
            values["phone_pin"] = pin
        values["phone_access"] = "1" if request.form.get("phone_access") else "0"
        if values["phone_access"] == "1" and not (pin or db.get_settings().get("phone_pin")):
            values["phone_access"] = "0"
            flash("Set a PIN first before turning on phone access.", "error")
        new_key = request.form.get("groq_api_key", "").strip()
        if new_key:
            values["groq_api_key"] = new_key
        if request.form.get("clear_key"):
            values["groq_api_key"] = ""
        db.save_settings(values)
        flash("Settings saved.", "success")
        return redirect(url_for("settings_page"))
    ip = lan_ip()
    phone_url = f"http://{ip}:{PORT}" if ip else None
    return render_template("settings.html", verifiers=db.default_verifiers(),
                           saved_verifiers=db.saved_verifiers(), phone_url=phone_url,
                           phone_qr=phone_qr_data_uri(phone_url) if phone_url else None,
                           heic_ok=HEIC_OK, is_local=is_local_request())


def _validate_sqlite_file(path):
    """Verify path is a valid OJT Journal SQLite database."""
    conn = sqlite3.connect(path)
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()
    if not {"settings", "days"}.issubset(tables):
        raise ValueError("Missing required OJT Journal tables (settings, days).")


def _restore_from_bytes(raw_bytes, filename=""):
    """Restore from either a full backup .zip (DB + photos) or a standalone .db SQLite file."""
    lower = (filename or "").lower()
    is_sqlite = raw_bytes[:16] == b"SQLite format 3\x00" or lower.endswith((".db", ".sqlite", ".sqlite3"))

    if is_sqlite and not raw_bytes[:2] == b"PK":
        with tempfile.TemporaryDirectory() as tmp:
            tmp_db = os.path.join(tmp, "check.db")
            with open(tmp_db, "wb") as out_f:
                out_f.write(raw_bytes)
            try:
                _validate_sqlite_file(tmp_db)
            except Exception:
                raise ValueError("That .db file is not a valid OJT Journal database.")
            os.makedirs(db.UPLOAD_DIR, exist_ok=True)
            shutil.copy2(tmp_db, db.DB_PATH)
        db.init_db()
        db.mark_exported()
        days_count = len(db.list_days())
        return f"Database imported! ({days_count} day{'s' if days_count != 1 else ''} loaded — photos were not included in .db-only file.)"

    try:
        zf = zipfile.ZipFile(io.BytesIO(raw_bytes))
    except zipfile.BadZipFile:
        raise ValueError("Please upload a valid OJT backup (.zip) or SQLite database (.db) file.")

    with zf:
        names = [n.replace("\\", "/") for n in zf.namelist()]
        db_member = None
        for orig, norm in zip(zf.namelist(), names):
            if norm in ("data/ojt_journal.db", "ojt_journal.db"):
                db_member = orig
                break
        if not db_member:
            raise ValueError("Backup ZIP does not contain ojt_journal.db.")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_db = os.path.join(tmp, "check.db")
            with open(tmp_db, "wb") as out_f:
                out_f.write(zf.read(db_member))
            try:
                _validate_sqlite_file(tmp_db)
            except Exception:
                raise ValueError("The ojt_journal.db inside this ZIP is corrupted or invalid.")

            os.makedirs(db.UPLOAD_DIR, exist_ok=True)
            shutil.copy2(tmp_db, db.DB_PATH)
            restored_files = 0
            for orig, norm in zip(zf.namelist(), names):
                if norm.endswith("/"):
                    continue
                if norm.startswith("data/uploads/"):
                    rel_up = norm[len("data/uploads/"):]
                elif norm.startswith("uploads/"):
                    rel_up = norm[len("uploads/"):]
                else:
                    continue
                rel_up = os.path.normpath(rel_up)
                if rel_up.startswith("..") or os.path.isabs(rel_up):
                    continue
                dst = os.path.join(db.UPLOAD_DIR, rel_up)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                with open(dst, "wb") as out_f:
                    out_f.write(zf.read(orig))
                restored_files += 1

    db.init_db()
    db.mark_exported()
    days_count = len(db.list_days())
    return (f"Backup imported! ({days_count} day{'s' if days_count != 1 else ''} and "
            f"{restored_files} photo{'s' if restored_files != 1 else ''} loaded.)")


@app.route("/backup")
def backup():
    db.mark_exported()
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(db.DATA_DIR):
            for f in files:
                if f.endswith(".zip"):
                    continue
                full = os.path.join(root, f)
                rel = os.path.relpath(full, db.DATA_DIR)
                zf.write(full, os.path.join("data", rel))
    out.seek(0)
    return send_file(out, mimetype="application/zip", as_attachment=True,
                     download_name=f"ojt_journal_backup_{date.today().isoformat()}.zip")


@app.route("/backup/db")
def backup_db():
    db.mark_exported()
    if not os.path.isfile(db.DB_PATH):
        db.init_db()
    with open(db.DB_PATH, "rb") as f:
        payload = f.read()
    return send_file(io.BytesIO(payload), mimetype="application/x-sqlite3", as_attachment=True,
                     download_name=f"ojt_journal_{date.today().isoformat()}.db")


@app.route("/restore", methods=["POST"])
def restore():
    f = request.files.get("backup_zip")
    if not f or not f.filename:
        flash("Please choose a backup (.zip) or database (.db) file first.", "error")
        return redirect(request.referrer or url_for("settings_page"))
    try:
        msg = _restore_from_bytes(f.read(), f.filename)
    except ValueError as e:
        flash(str(e), "error")
        return redirect(request.referrer or url_for("settings_page"))
    if IS_CLOUD:
        session.permanent = True
        session["phone_ok"] = True
    flash(msg, "success")
    return redirect(url_for("dashboard"))


@app.route("/api/restore-chunk", methods=["POST"])
def api_restore_chunk():
    """Chunked upload endpoint so large photo backup ZIPs (>4 MB) import smoothly."""
    upload_id = re.sub(r"[^a-zA-Z0-9_-]", "", request.form.get("upload_id") or "")
    filename = request.form.get("filename") or "backup.zip"
    try:
        index = int(request.form.get("index", 0))
        total = int(request.form.get("total", 1))
    except ValueError:
        return jsonify(error="Invalid chunk metadata."), 400
    chunk = request.files.get("chunk")
    if not upload_id or not chunk or total < 1 or index < 0 or index >= total:
        return jsonify(error="Invalid chunk upload."), 400

    chunk_dir = os.path.join(tempfile.gettempdir(), "ojt_restore_chunks")
    os.makedirs(chunk_dir, exist_ok=True)
    part_path = os.path.join(chunk_dir, f"{upload_id}.part")
    mode = "wb" if index == 0 else "ab"
    with open(part_path, mode) as out_f:
        out_f.write(chunk.read())

    if index + 1 < total:
        return jsonify(ok=True, done=False, received=index + 1, total=total)

    try:
        with open(part_path, "rb") as f:
            raw = f.read()
        msg = _restore_from_bytes(raw, filename)
    except ValueError as e:
        return jsonify(error=str(e)), 400
    finally:
        try:
            os.remove(part_path)
        except OSError:
            pass
    if IS_CLOUD:
        session.permanent = True
        session["phone_ok"] = True
    flash(msg, "success")
    return jsonify(ok=True, done=True, message=msg, redirect=url_for("dashboard"))


# --------------------------------------------------------------------------
# Files
# --------------------------------------------------------------------------
@app.route("/uploads/<path:filename>")
def uploads(filename):
    return send_from_directory(db.UPLOAD_DIR, filename)


@app.route("/assets/<name>")
def assets(name):
    if name not in ASSETS:
        abort(404)
    mimetype = "application/manifest+json" if name.endswith(".webmanifest") else None
    return send_from_directory(BASE_DIR, name, max_age=0, mimetype=mimetype)


# --------------------------------------------------------------------------
# AI endpoints
# --------------------------------------------------------------------------
@app.route("/api/polish", methods=["POST"])
def api_polish():
    notes = [str(n) for n in (request.get_json(silent=True) or {}).get("notes", []) if str(n).strip()]
    if not notes:
        return jsonify(error="Write what you did first."), 400
    try:
        return jsonify(items=ai_helper.polish_activities(db.get_settings(), notes))
    except ai_helper.AIError as e:
        return jsonify(error=str(e)), 502


@app.route("/api/reflection", methods=["POST"])
def api_reflection():
    body = request.get_json(silent=True) or {}
    if not any((body.get(k) or "").strip() for k in ("problems", "solutions", "goals")):
        return jsonify(error="Write your notes first."), 400
    try:
        return jsonify(ai_helper.polish_reflection(db.get_settings(), body.get("problems"),
                                                   body.get("solutions"), body.get("goals")))
    except ai_helper.AIError as e:
        return jsonify(error=str(e)), 502


@app.route("/api/week/<int:n>/autosave", methods=["POST"])
def api_autosave_week(n):
    if n < 1:
        return jsonify(error="Invalid week number."), 404
    data = db.get_week_data(n)
    if data.get("status") in ("submitted", "approved"):
        return jsonify(error=f"Week {n} is locked."), 409
    body = request.get_json(force=True, silent=True)
    if not isinstance(body, dict):
        return jsonify(error="Invalid payload."), 400
    _apply_week_fields(data, body, is_json=True)
    db.save_week_data(n, data)
    saved_at = datetime.now().strftime("%I:%M %p").lstrip("0")
    return jsonify(ok=True, saved_at=saved_at)


@app.route("/api/week/<int:n>/generate", methods=["POST"])
def api_generate_week(n):
    settings = db.get_settings()
    mon, sun = db.week_range(n, settings)
    days_in_week = db.list_days(mon, sun)
    if not days_in_week:
        return jsonify(error="This week has no entries yet."), 400
    payload = [{"date": nice_date(d["date_obj"]),
                "activities": [a["text"] or a["raw_text"] for a in d["activities"]
                               if (a["text"] or a["raw_text"]).strip()]} for d in days_in_week]
    end = max(mon + timedelta(days=4), days_in_week[-1]["date_obj"])
    try:
        result = ai_helper.generate_week(settings, n, docgen.range_compact(mon, end), payload,
                                         week_trainers(days_in_week))
    except ai_helper.AIError as e:
        return jsonify(error=str(e)), 502
    return jsonify(result)


@app.route("/api/test-ai", methods=["POST"])
def api_test_ai():
    try:
        ai_helper.test_connection(db.get_settings())
        return jsonify(ok=True)
    except ai_helper.AIError as e:
        return jsonify(error=str(e)), 502


# --------------------------------------------------------------------------
if __name__ == "__main__":
    if os.environ.get("OJT_NO_BROWSER") != "1":
        threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{PORT}")).start()
    ip = lan_ip()
    print(f"\n  OJT Journal is running at http://127.0.0.1:{PORT}")
    if ip:
        print(f"  On your phone (same WiFi, turn on Phone access in Settings): http://{ip}:{PORT}")
    print("  Keep this window open while using the system. Press CTRL+C to stop.\n")
    app.run(host="0.0.0.0", port=PORT, debug=False)
