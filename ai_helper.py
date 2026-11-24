"""Groq AI helper (OpenAI-compatible chat completions API)."""
import json
import os
import re

import requests

GROQ_URL = os.environ.get("OJT_GROQ_URL", "https://api.groq.com/openai/v1/chat/completions")
FALLBACK_MODEL = "openai/gpt-oss-20b"


class AIError(Exception):
    pass


STYLE_RULES = (
    "Write in simple, clear, student-friendly English that sounds like a real BSIT intern, "
    "not overly formal or flowery. The notes may be written in Taglish, Tagalog or English; "
    "always answer in English and fix spelling or casing typos (e.g. POS, Laravel Herd, IP address, "
    "Epson L5290, CA). Use ONLY the facts given. Never invent tasks, numbers, names, "
    "software, equipment or results. Keep every number, quantity, name and brand that is given."
)


def _extract_json(text):
    text = (text or "").strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    match = re.search(r"\{.*\}", text, re.S)
    if match:
        try:
            return json.loads(match.group(0))
        except ValueError:
            pass
    raise AIError("The AI returned an unexpected answer. Please try again.")


def _post(api_key, model, messages, json_mode, extras):
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.3,
        "max_completion_tokens": 4096,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    if extras and model.startswith("openai/gpt-oss"):
        payload["reasoning_effort"] = "low"
    return requests.post(GROQ_URL, json=payload, timeout=90,
                         headers={"Authorization": f"Bearer {api_key}",
                                  "Content-Type": "application/json"})


def chat_json(settings, system, user):
    api_key = (settings.get("groq_api_key") or "").strip()
    if not api_key:
        raise AIError("No Groq API key yet. Open Settings and paste your key from console.groq.com.")
    model = (settings.get("groq_model") or "").strip() or "openai/gpt-oss-120b"
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]

    attempts = [(model, True, True), (model, False, False)]
    if model != FALLBACK_MODEL:
        attempts.append((FALLBACK_MODEL, True, True))
    last_error = "Unknown error."
    for mdl, json_mode, extras in attempts:
        try:
            r = _post(api_key, mdl, messages, json_mode, extras)
        except requests.exceptions.ConnectionError:
            raise AIError("Cannot reach Groq. Please check your internet connection.")
        except requests.exceptions.Timeout:
            raise AIError("Groq took too long to answer. Please try again.")
        if r.status_code == 200:
            content = r.json()["choices"][0]["message"].get("content") or ""
            return _extract_json(content)
        try:
            detail = r.json().get("error", {}).get("message", r.text)
        except ValueError:
            detail = r.text
        if r.status_code == 401:
            raise AIError("Your Groq API key is invalid. Please check it in Settings.")
        if r.status_code == 429:
            raise AIError("Groq free limit reached for now. Wait a minute and try again.")
        last_error = f"Groq error ({r.status_code}): {detail[:300]}"
    raise AIError(last_error + " You can also try another model in Settings.")


# --------------------------------------------------------------------------
# Tasks
# --------------------------------------------------------------------------
def polish_activities(settings, items):
    """items: list of rough notes. Returns list of {text, caption}."""
    system = (
        "You help an OJT (on-the-job training) intern write a Daily Attendance and "
        "Accomplishment Form. " + STYLE_RULES + "\n\n"
        "For each note return:\n"
        "- text: the accomplishment in past tense, starting with a past-tense verb "
        "(e.g. 'Installed ...', 'Encoded ...'), usually one sentence, ending with a period.\n"
        "- caption: a short photo caption (max 10 words) in this style: "
        "'Stamping of enrolled on the COR papers.' or 'Installing of printer driver.' "
        "It must end with a period.\n\n"
        'Answer only with JSON: {"items": [{"text": "...", "caption": "..."}]} '
        "in the same order as the notes."
    )
    numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(items))
    data = _extract_items(chat_json(settings, system, "Notes:\n" + numbered))
    out = []
    for i, original in enumerate(items):
        item = data[i] if i < len(data) and isinstance(data[i], dict) else {}
        out.append({"text": str(item.get("text") or original).strip(),
                    "caption": str(item.get("caption") or "").strip()})
    return out


def _extract_items(data):
    if isinstance(data, dict):
        for key in ("items", "activities", "results"):
            if isinstance(data.get(key), list):
                return data[key]
    if isinstance(data, list):
        return data
    return []


def polish_reflection(settings, problems, solutions, goals):
    system = (
        "You help an OJT intern answer three questions of a Weekly Progress Report: "
        "problems encountered, how they solved them, and one or two goals for next week. "
        + STYLE_RULES + " Write in first person where natural. Split the notes into clear "
        "bullet items (one idea per item). Do not add problems, solutions or goals that "
        "are not in the notes. If a section has no notes, return an empty list.\n\n"
        'Answer only with JSON: {"problems": [], "solutions": [], "goals": []}'
    )
    user = (f"PROBLEMS NOTES:\n{problems or '(none)'}\n\n"
            f"SOLUTIONS NOTES:\n{solutions or '(none)'}\n\n"
            f"GOALS NOTES:\n{goals or '(none)'}")
    data = chat_json(settings, system, user)
    return {k: _str_list(data.get(k)) for k in ("problems", "solutions", "goals")}


def generate_week(settings, week_number, date_label, days, trainers):
    """days: list of {date, activities:[text]}"""
    system = (
        "You help an OJT intern (BSIT student) prepare weekly OJT documents from the daily "
        "accomplishments of one week. " + STYLE_RULES + "\n\n"
        "Return JSON with these keys:\n"
        "- duties: 4-10 bullet items for 'Duties Performed this week' (past tense, group "
        "similar tasks, no duplicates).\n"
        "- new_trainings: 2-4 items for 'What new training/s took place this week?' "
        "(first person, e.g. 'I learned how to ...').\n"
        "- proposed: 3-6 short items for 'Proposed Activity/ies' (short noun or gerund phrases "
        "that match the training schedule categories).\n"
        "- accomplishments: 1-3 short paragraphs (first person) describing the major "
        "accomplishments and the tasks involved.\n"
        "- learning_activities: 4-8 short gerund phrases summarizing the activities "
        "(e.g. 'Installing printer drivers.').\n"
        "- learning_outcomes: 2-4 items (first person) about what was learned.\n"
        "- training: list of objects for the Training Schedule Form. Each object: "
        '{"category": "...", "how": ["..."], "trainers": ["..."], "timeline": "", '
        '"outputs": ["..."]}. Prefer these categories: Computer Operation, Multimedia, '
        "Troubleshooting, Networking, Web Development, Programming, Hardware Maintenance, "
        "Data Encoding, Documentation or Clerical Work. Only include categories that the activities support. 'how' = how "
        "the activities were performed (gerund phrases). 'outputs' = expected outputs "
        "(e.g. 'Properly set-up and functioning workstation.'). 'trainers' must ONLY use "
        "names from the trainer list; if the list is empty, use an empty list. "
        "Leave 'timeline' as an empty string."
    )
    lines = [f"WEEK {week_number} ({date_label})", f"Trainer list: {', '.join(trainers) or '(none)'}", ""]
    for d in days:
        lines.append(f"{d['date']}:")
        lines += [f"- {a}" for a in d["activities"]] or ["- (no activities)"]
    data = chat_json(settings, system, "\n".join(lines))
    result = {k: _str_list(data.get(k)) for k in
              ("duties", "new_trainings", "proposed", "accomplishments",
               "learning_activities", "learning_outcomes")}
    training = []
    for t in data.get("training") or []:
        if not isinstance(t, dict):
            continue
        training.append({
            "category": str(t.get("category") or "").strip(),
            "how": _str_list(t.get("how")),
            "trainers": [x for x in _str_list(t.get("trainers")) if x in trainers] or list(trainers[:1]),
            "timeline": str(t.get("timeline") or "").strip(),
            "outputs": _str_list(t.get("outputs") or t.get("expected_output")),
        })
    result["training"] = training
    return result


def test_connection(settings):
    data = chat_json(settings, 'Answer only with JSON: {"ok": true}', "Say ok.")
    return bool(data)


def _str_list(value):
    if isinstance(value, str):
        value = [v for v in value.split("\n")]
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in value if str(v).strip()]
