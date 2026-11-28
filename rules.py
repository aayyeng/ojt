"""
Shared OJT Journal business rules, calculations, and validation.

Single source of truth used by database.py, app.py, docgen.py, importers, and tests.
"""
import math
import os
import re
from datetime import date, timedelta

# Workflow statuses for weekly documentation packs
WEEK_STATUSES = ("draft", "ready", "submitted", "approved")
WEEK_STATUS_LABELS = {
    "draft": "Draft",
    "ready": "Ready to Submit",
    "submitted": "Submitted",
    "approved": "Approved",
}


# --------------------------------------------------------------------------
# Time & hours formulas
# --------------------------------------------------------------------------
def minutes_between(start, end):
    """Exact positive duration in minutes between two 'HH:MM' strings, or 0."""
    try:
        sh, sm = map(int, str(start).split(":")[:2])
        eh, em = map(int, str(end).split(":")[:2])
    except (ValueError, AttributeError):
        return 0
    diff = (eh * 60 + em) - (sh * 60 + sm)
    return diff if diff > 0 else 0


def activity_minutes(start, end, fallback_minutes=0):
    """Derive activity duration: start/end takes precedence over manual minutes."""
    between = minutes_between(start, end)
    if between > 0:
        return between
    try:
        return max(0, int(fallback_minutes or 0))
    except (ValueError, TypeError):
        return 0


def day_minutes(activities):
    """Total rendered minutes for a day = sum of its activity durations."""
    return sum(max(0, int(a.get("minutes") or 0)) for a in (activities or []))


def week_minutes(days):
    """Total rendered minutes for a week = sum of its day totals."""
    return sum(max(0, int(d.get("minutes") or 0)) for d in (days or []))


def parse_hours_to_minutes(value, default_hours=0.0):
    """Convert a decimal hours string/number to non-negative integer minutes."""
    try:
        hours = float(value)
    except (ValueError, TypeError):
        hours = float(default_hours)
    return max(0, int(round(hours * 60)))


def fmt_minutes(minutes):
    """Compact UI label: 95 -> '1h 35m', 240 -> '4h', 0 -> '0m'."""
    minutes = max(0, int(minutes or 0))
    h, m = divmod(minutes, 60)
    if h and m:
        return f"{h}h {m}m"
    if h:
        return f"{h}h"
    return f"{m}m"


def hours_label(minutes):
    """Official form label: 95 -> '1 hr 35 min', 240 -> '4 hrs', 0 -> ''."""
    minutes = int(minutes or 0)
    if minutes <= 0:
        return ""
    h, m = divmod(minutes, 60)
    parts = []
    if h:
        parts.append(f"{h} hr" if h == 1 else f"{h} hrs")
    if m:
        parts.append(f"{m} min")
    return " ".join(parts)


def compute_progress(days, required_hours=486, prior_hours=0, today=None):
    """Compute overall OJT completion progress and weekday-based finish estimate."""
    today = today or date.today()
    logged_total = week_minutes(days)
    prior_min = parse_hours_to_minutes(prior_hours, 0.0)
    total = logged_total + prior_min
    required_min = parse_hours_to_minutes(required_hours, 486.0)
    remaining = max(required_min - total, 0)
    pct = min(100.0, total / required_min * 100.0) if required_min else 0.0
    avg = (logged_total / len(days)) if days else 0.0

    finish = None
    if remaining == 0 and (days or prior_min):
        finish = days[-1]["date_obj"] if days else today
    elif avg > 0:
        need = math.ceil(remaining / avg)
        cursor = max(today, days[-1]["date_obj"])
        while need > 0:
            cursor += timedelta(days=1)
            if cursor.weekday() < 5:
                need -= 1
        finish = cursor

    return {
        "logged_total": logged_total,
        "prior_min": prior_min,
        "total": total,
        "required_min": required_min,
        "remaining": remaining,
        "pct": pct,
        "avg": avg,
        "finish": finish,
    }


# --------------------------------------------------------------------------
# Text & naming helpers
# --------------------------------------------------------------------------
def clean_items(items):
    """Strip whitespace and leading manual bullet markers to prevent double bullets."""
    out = []
    for item in items or []:
        text = str(item).strip()
        text = re.sub(r"^[\-•\*●]+\s*", "", text)
        if text:
            out.append(text)
    return out


def last_name_suffix(student_name):
    """Extract uppercase last name suffix for official export filenames."""
    parts = [p for p in re.findall(r"[A-Za-z0-9-]+", student_name or "") if p]
    return f" - {parts[-1].upper()}" if parts else ""


# --------------------------------------------------------------------------
# Validation (blocking errors vs. warnings vs. info)
# --------------------------------------------------------------------------
def validate_day(day, start_date_obj=None):
    """Validate one daily entry. Returns {'errors': [], 'warnings': [], 'info': []}."""
    errors, warnings, info = [], [], []
    if not day:
        return {"errors": ["Entry does not exist."], "warnings": [], "info": []}

    d_obj = day.get("date_obj")
    if start_date_obj and d_obj and d_obj < start_date_obj:
        errors.append(f"Date ({day.get('date')}) is before your OJT start date ({start_date_obj.isoformat()}).")

    acts = day.get("activities") or []
    if not acts:
        warnings.append("No activities recorded yet for this day.")
    else:
        zero_min = sum(1 for a in acts if not int(a.get("minutes") or 0))
        if zero_min:
            warnings.append(f"{zero_min} activit{'ies have' if zero_min > 1 else 'y has'} 0 minutes and will not add to your total hours.")
        unpolished = sum(1 for a in acts if (a.get("raw_text") or "").strip() and not (a.get("text") or "").strip())
        if unpolished:
            warnings.append(f"{unpolished} activit{'ies have' if unpolished > 1 else 'y has'} no English report text yet.")

    times = [day.get("morning_in"), day.get("morning_out"), day.get("afternoon_in"), day.get("afternoon_out")]
    if acts and not any((t or "").strip() for t in times):
        warnings.append("Attendance IN/OUT times are blank for this day (verify before printing).")
    elif acts and not all((t or "").strip() for t in times):
        warnings.append("Attendance IN/OUT times are partially filled.")

    verifiers = [v for v in (day.get("verifiers") or []) if (v.get("name") or "").strip()]
    if acts and not verifiers:
        warnings.append("No 'Verified by' person listed for this day.")

    photos = day.get("photos") or []
    ncis = day.get("ncis") or []
    info.append(f"{len(acts)} activit{'ies' if len(acts) != 1 else 'y'} · {fmt_minutes(day.get('minutes', 0))} · {len(photos)} work photo{'s' if len(photos) != 1 else ''} · {len(ncis)} NCIS screenshot{'s' if len(ncis) != 1 else ''}.")
    return {"errors": errors, "warnings": warnings, "info": info}


def validate_week(days, week_data, settings):
    """Pre-flight validation for a weekly report pack before download/submission."""
    errors, warnings, info = [], [], []
    if not days:
        errors.append("This week has no daily entries yet. Add at least one entry before downloading.")
        return {"errors": errors, "warnings": warnings, "info": info}

    if not (settings.get("student_name") or "").strip():
        errors.append("Student name is blank in Settings.")
    if not (settings.get("internship_site") or "").strip():
        warnings.append("Internship site is blank in Settings.")

    missing_times = []
    missing_verifiers = []
    unpolished_count = 0
    zero_min_count = 0
    total_photos = 0
    total_ncis = 0

    for d in days:
        day_label = d["date_obj"].strftime("%a %b %d")
        times = [d.get("morning_in"), d.get("morning_out"), d.get("afternoon_in"), d.get("afternoon_out")]
        if not any((t or "").strip() for t in times):
            missing_times.append(day_label)
        verifiers = [v for v in (d.get("verifiers") or []) if (v.get("name") or "").strip()]
        if not verifiers:
            missing_verifiers.append(day_label)
        for a in d.get("activities") or []:
            if (a.get("raw_text") or "").strip() and not (a.get("text") or "").strip():
                unpolished_count += 1
            if not int(a.get("minutes") or 0):
                zero_min_count += 1
        total_photos += len(d.get("photos") or [])
        total_ncis += len(d.get("ncis") or [])

    if missing_times:
        warnings.append(f"Blank attendance IN/OUT times on: {', '.join(missing_times)}.")
    if missing_verifiers:
        warnings.append(f"No 'Verified by' name on: {', '.join(missing_verifiers)}.")
    if unpolished_count:
        warnings.append(f"{unpolished_count} activit{'ies are' if unpolished_count != 1 else 'y is'} not yet polished into English.")
    if zero_min_count:
        warnings.append(f"{zero_min_count} activit{'ies have' if zero_min_count != 1 else 'y has'} 0 minutes logged.")
    if total_photos == 0:
        warnings.append("No work photos uploaded for this week (DOCUMENTATIONS.docx will show a placeholder note).")
    if total_ncis == 0:
        warnings.append("No NCIS attendance screenshots uploaded for this week.")

    if not clean_items(week_data.get("duties")):
        warnings.append("Weekly Progress Report 'Duties performed' is empty — click Generate with AI or type it.")
    if not (clean_items(week_data.get("problems")) or (week_data.get("problems_raw") or "").strip()):
        warnings.append("Weekly reflection (Problems / Solutions / Goals) is still empty.")
    if not (week_data.get("training") or []):
        warnings.append("Training Schedule Form has no categories yet — click Generate with AI or add categories.")

    total_m = week_minutes(days)
    info.append(f"Cross-checked total: {hours_label(total_m) or '0m'} across {len(days)} day{'s' if len(days) != 1 else ''}.")
    info.append(f"Media ready: {total_photos} work photo{'s' if total_photos != 1 else ''} and {total_ncis} NCIS screenshot{'s' if total_ncis != 1 else ''}.")
    return {"errors": errors, "warnings": warnings, "info": info}
