"""
Import Jeriel Maningas's real Week 1 OJT entries, photos, NCIS screenshots,
and Weekly Report content from `needed files/` into `data/ojt_journal.db`.

Follows the never-guess rule:
- Per-activity start/end timestamps are left blank because only daily totals
  were recorded on the manual Week 1 form; recorded daily totals (4h, 7h 30m,
  4h 30m, 6h, 7h = 29h) are preserved exactly.
- Friday's Morning/Afternoon IN-OUT times are left blank (matching the manual
  form) so the pre-flight validator flags them for review.
- Uncaptioned photos on Nov 16 keep empty captions rather than invented ones.
"""
import io
import os
import zipfile
import xml.etree.ElementTree as ET
from PIL import Image, ImageOps

import database as db
import rules

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
NEEDED_DIR = os.path.join(BASE_DIR, "needed files")

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
}


def _save_image_bytes(raw_bytes, day_date, prefix, idx, as_png=False):
    folder = os.path.join(db.UPLOAD_DIR, day_date)
    os.makedirs(folder, exist_ok=True)
    img = Image.open(io.BytesIO(raw_bytes))
    img = ImageOps.exif_transpose(img)
    if as_png:
        fname = f"{prefix}_{idx:02d}.png"
        if img.mode not in ("RGB", "RGBA", "L"):
            img = img.convert("RGBA")
        img.thumbnail((2400, 2400))
        img.save(os.path.join(folder, fname), "PNG", optimize=True)
    else:
        fname = f"{prefix}_{idx:02d}.jpg"
        if img.mode != "RGB":
            img = img.convert("RGB")
        img.thumbnail((2000, 2000))
        img.save(os.path.join(folder, fname), "JPEG", quality=88)
    return f"{day_date}/{fname}"


def _extract_doc_photos():
    """Extract embedded photos + captions per date from DOCUMENTATIONS - complete.docx."""
    path = os.path.join(NEEDED_DIR, "DOCUMENTATIONS - complete.docx")
    date_map = {
        "November 16, 2026": "2026-11-16",
        "November 17, 2026": "2026-11-17",
        "November 18, 2026": "2026-11-18",
        "November 19, 2026": "2026-11-19",
        "November 20, 2026": "2026-11-20",
    }
    caption_fixes = {
        "Encoding of.disbursement": "Encoding of disbursement.",
        "Creation of Simpe POS system with Herd": "Creation of Simple POS system with Laravel Herd.",
    }
    by_date = {d: [] for d in date_map.values()}
    if not os.path.isfile(path):
        return by_date

    with zipfile.ZipFile(path) as zf:
        rels = {
            el.get("Id"): el.get("Target")
            for el in ET.fromstring(zf.read("word/_rels/document.xml.rels"))
        }
        body = ET.fromstring(zf.read("word/document.xml")).find("w:body", NS)
        for tbl in body.findall("w:tbl", NS):
            rows = tbl.findall("w:tr", NS)
            if not rows:
                continue
            header = "".join(
                t.text or ""
                for t in rows[0].iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t")
            ).strip()
            day_date = date_map.get(header)
            if not day_date:
                continue
            r_idx = 1
            while r_idx < len(rows):
                pic_cells = rows[r_idx].findall("w:tc", NS)
                cap_cells = rows[r_idx + 1].findall("w:tc", NS) if r_idx + 1 < len(rows) else []
                # Check if next row actually contains images instead of captions (Nov 16 R3 case)
                next_has_img = any(
                    list(tc.iter("{http://schemas.openxmlformats.org/drawingml/2006/main}blip"))
                    for tc in cap_cells
                )
                if next_has_img:
                    cap_cells = []
                for ci, tc in enumerate(pic_cells):
                    blips = [
                        rels.get(b.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed"))
                        for b in tc.iter("{http://schemas.openxmlformats.org/drawingml/2006/main}blip")
                    ]
                    if not blips or not blips[0]:
                        continue
                    target = "word/" + blips[0].lstrip("/")
                    cap = ""
                    if ci < len(cap_cells):
                        cap = "".join(
                            t.text or ""
                            for t in cap_cells[ci].iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t")
                        ).strip()
                        cap = caption_fixes.get(cap, cap)
                    by_date[day_date].append((zf.read(target), cap))
                r_idx += 1 if next_has_img else 2
    return by_date


def _extract_ncis():
    """Extract embedded NCIS screenshots + labels from NCIS-ATTENDANCE-MONITORING - complete.docx."""
    path = os.path.join(NEEDED_DIR, "NCIS-ATTENDANCE-MONITORING - complete.docx")
    label_to_date = {
        "November 16, 2026": ("2026-11-16", "November 16, 2026"),
        "November 17, 2026": ("2026-11-17", "November 17, 2026"),
        "November 18-20, 2026": ("2026-11-18", "November 18–20, 2026"),
    }
    out = {}
    if not os.path.isfile(path):
        return out

    with zipfile.ZipFile(path) as zf:
        rels = {
            el.get("Id"): el.get("Target")
            for el in ET.fromstring(zf.read("word/_rels/document.xml.rels"))
        }
        body = ET.fromstring(zf.read("word/document.xml")).find("w:body", NS)
        current_key = None
        for p in body.findall("w:p", NS):
            txt = "".join(
                t.text or ""
                for t in p.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t")
            ).strip()
            if txt in label_to_date:
                current_key = label_to_date[txt]
                continue
            blips = [
                rels.get(b.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed"))
                for b in p.iter("{http://schemas.openxmlformats.org/drawingml/2006/main}blip")
            ]
            if current_key and blips and blips[0]:
                day_date, clean_label = current_key
                target = "word/" + blips[0].lstrip("/")
                out.setdefault(day_date, []).append((zf.read(target), clean_label))
    return out


WEEK1_DAYS = [
    {
        "date": "2026-11-16",
        "morning_in": "08:00", "morning_out": "12:00",
        "afternoon_in": "13:00", "afternoon_out": "17:00",
        "verifiers": [
            {"name": "Luis D. Solmayor", "title": "Accounting Supervisor"},
            {"name": "Nikki Dela Cruz", "title": ""},
        ],
        "activities": [
            {
                "minutes": 120,
                "raw": "Encoding of statement of cash and check disbursement- 10.06.2026",
                "text": "Encoded the statement of cash and check disbursement (10.06.2026).",
                "caption": "Encoding statements of cash disbursement.",
            },
            {
                "minutes": 120,
                "raw": "Orientation for current systems used in the company",
                "text": "Attended orientation on the current systems used in the company.",
                "caption": "Orientation for existing system used in the company.",
            },
        ],
    },
    {
        "date": "2026-11-17",
        "morning_in": "08:00", "morning_out": "12:00",
        "afternoon_in": "13:00", "afternoon_out": "17:00",
        "verifiers": [
            {"name": "Jerwin Dominick A. Bernabe", "title": "IT Supervisor"},
            {"name": "Luis D. Solmayor", "title": "Accounting Supervisor"},
        ],
        "activities": [
            {
                "minutes": 225,
                "raw": "Developing simple pos using laravel herd.",
                "text": "Developed a simple POS web system using Laravel Herd.",
                "caption": "Creation of Simple POS system with Laravel Herd.",
            },
            {
                "minutes": 225,
                "raw": "Encoding of statement of cash and check disbursement",
                "text": "Encoded statements of cash and check disbursement.",
                "caption": "Encoding of statement of cash and check disbursement.",
            },
        ],
    },
    {
        "date": "2026-11-18",
        "morning_in": "08:00", "morning_out": "12:00",
        "afternoon_in": "13:00", "afternoon_out": "17:00",
        "verifiers": [
            {"name": "Luis D. Solmayor", "title": "Accounting Supervisor"},
        ],
        "activities": [
            {
                "minutes": 135,
                "raw": "Encoding of statement of cash and check disbursement.",
                "text": "Encoded statements of cash and check disbursement.",
                "caption": "Encoding of cash and check disbursement.",
            },
            {
                "minutes": 135,
                "raw": "Diagnosed laptops and listed all the issues.",
                "text": "Diagnosed defective laptops and listed all identified issues.",
                "caption": "Diagnosing laptops and listing issues.",
            },
        ],
    },
    {
        "date": "2026-11-19",
        "morning_in": "08:00", "morning_out": "12:00",
        "afternoon_in": "13:00", "afternoon_out": "17:00",
        "verifiers": [
            {"name": "Jerry Apostol Jr.", "title": ""},
            {"name": "Luis D. Solmayor", "title": "Accounting Supervisor"},
        ],
        "activities": [
            {
                "minutes": 120,
                "raw": "Laptop rediagnosing and reporting",
                "text": "Re-diagnosed defective laptops and prepared diagnostic reports.",
                "caption": "Run diagnostics on defective laptops and creating a report.",
            },
            {
                "minutes": 120,
                "raw": "Laptop diagnostic and dismantling",
                "text": "Performed laptop diagnostics and hardware dismantling.",
                "caption": "Laptop diagnostics and dismantling.",
            },
            {
                "minutes": 120,
                "raw": "Encoding of statement of cash and check disbursement",
                "text": "Encoded statements of cash and check disbursement.",
                "caption": "Encoding of disbursement.",
            },
        ],
    },
    {
        "date": "2026-11-20",
        # Never-guess rule: Friday attendance IN/OUT was blank in the original Week 1 form
        "morning_in": "", "morning_out": "",
        "afternoon_in": "", "afternoon_out": "",
        "verifiers": [
            {"name": "Luis D. Solmayor", "title": "Accounting Supervisor"},
        ],
        "activities": [
            {
                "minutes": 140,
                "raw": "Encoding of summary of luquidation",
                "text": "Encoded the summary of liquidation.",
                "caption": "Encoding of liquidation summary.",
            },
            {
                "minutes": 140,
                "raw": "Installation of epson l5290 printer driver",
                "text": "Installed and configured the Epson L5290 printer driver via IP address.",
                "caption": "Installation of Epson L5290 printer driver.",
            },
            {
                "minutes": 140,
                "raw": "Encoding of statement of cash and check disbursement",
                "text": "Encoded statements of cash and check disbursement.",
                "caption": "Encoding of disbursement statements.",
            },
        ],
    },
]

WEEK1_REPORT = {
    "status": "ready",
    "problems_raw": "Only to few understanding of encoding of receipts, and small amount of tools needed for diagnosing and dismantling",
    "solutions_raw": "Having tools provided for us, learn to adapt and ask for supervisions",
    "goals_raw": "do more IT related things that can help me learn",
    "problems": [
        "Limited initial familiarity with encoding receipts into disbursement and liquidation statements.",
        "Limited tools available for diagnosing and dismantling defective laptops.",
    ],
    "solutions": [
        "Coordinated with staff to have the necessary tools provided.",
        "Adapted quickly to the workflow and asked supervisors for guidance whenever needed.",
    ],
    "goals": [
        "Take on more IT-related tasks that help expand my technical skills and practical experience.",
    ],
    "duties": [
        "Encoded statements of cash and check disbursement.",
        "Attended orientation on the current systems used in the company.",
        "Developed a simple POS web system using Laravel Herd.",
        "Diagnosed defective laptops, listed identified issues, and prepared diagnostic reports.",
        "Performed laptop re-diagnosis and hardware dismantling.",
        "Encoded the summary of liquidation.",
        "Installed and configured the Epson L5290 printer driver.",
    ],
    "new_trainings": [
        "I applied my knowledge and experience in diagnosing defective laptops.",
        "I learned how to configure a laptop-to-printer connection via IP address.",
        "I learned how to use Laravel Herd to build a simple POS web system.",
    ],
    "proposed": [
        "Troubleshooting of defective laptop devices",
        "Creating a simple POS web system using Laravel Herd",
        "Encoding of cash and check disbursement statements and liquidation summaries",
        "Printer driver installation and IP configuration",
    ],
    "accomplishments": [
        "This week I completed my daily encoding and documentation of cash and check disbursement statements and liquidation summaries. I also learned how to use Laravel Herd to build a simple POS web system, installed and configured the Epson L5290 printer driver via IP address, and applied my hardware skills in diagnosing, dismantling, and reporting issues on defective laptops.",
    ],
    "learning_activities": [
        "Encoding cash and check disbursement statements.",
        "Encoding liquidation forms.",
        "Diagnosing and listing laptop issues.",
        "Creating diagnostic reports.",
        "Connecting a laptop to a printer via IP address and installing the Epson L5290 printer driver.",
        "Creating a simple POS system using Laravel Herd.",
    ],
    "learning_outcomes": [
        "I learned how to document disbursement and liquidation information accurately from receipts, improving my documentation and adaptability skills.",
        "I learned how to apply hardware troubleshooting knowledge in diagnosing and dismantling laptop issues.",
        "I learned how to use Laravel Herd to streamline local web development.",
        "I learned how to establish a network connection between a laptop and a printer and install and configure printer drivers.",
    ],
    "training": [
        {
            "category": "Data Encoding",
            "how": [
                "Encoding statements of cash and check disbursement from receipts.",
                "Encoding summary of liquidation forms.",
            ],
            "trainers": ["Luis D. Solmayor"],
            "timeline": "",
            "outputs": ["Accurate and updated cash/check disbursement and liquidation records."],
        },
        {
            "category": "Troubleshooting",
            "how": [
                "Diagnosing and re-diagnosing defective laptops.",
                "Dismantling hardware components and documenting issues.",
                "Connecting laptop to printer via IP address and installing the Epson L5290 driver.",
            ],
            "trainers": ["Jerwin Dominick A. Bernabe", "Jerry Apostol Jr."],
            "timeline": "",
            "outputs": [
                "Complete laptop diagnostic report listing hardware and software issues.",
                "Properly configured Epson L5290 network printer.",
            ],
        },
        {
            "category": "Web Development",
            "how": [
                "Developing a simple POS web system using Laravel Herd.",
            ],
            "trainers": ["Jerwin Dominick A. Bernabe"],
            "timeline": "",
            "outputs": ["Working simple POS web prototype running on Laravel Herd."],
        },
    ],
}


def run_import():
    db.init_db()
    photos_by_date = _extract_doc_photos()
    ncis_by_date = _extract_ncis()

    imported_days = 0
    imported_photos = 0
    imported_ncis = 0

    for d in WEEK1_DAYS:
        existing = db.get_day(d["date"])
        if existing:
            db.delete_day(d["date"])
        day_id = db.upsert_day(None, {
            "date": d["date"],
            "morning_in": d["morning_in"],
            "morning_out": d["morning_out"],
            "afternoon_in": d["afternoon_in"],
            "afternoon_out": d["afternoon_out"],
            "verifiers": d["verifiers"],
            "notes": "",
        })
        db.remember_verifiers(d["verifiers"])
        act_items = [
            {
                "key": f"k{idx}",
                "start": "",
                "end": "",
                "minutes": a["minutes"],
                "raw": a["raw"],
                "text": a["text"],
                "caption": a["caption"],
            }
            for idx, a in enumerate(d["activities"])
        ]
        keys, _ = db.save_activities(day_id, act_items)
        first_act_id = keys.get("k0")

        for idx, (img_bytes, caption) in enumerate(photos_by_date.get(d["date"], []), start=1):
            rel = _save_image_bytes(img_bytes, d["date"], "w1_photo", idx, as_png=False)
            # Attach photo to matching activity if caption hints at it, else first activity
            act_id = first_act_id
            cap_l = caption.lower()
            for a_idx, a in enumerate(d["activities"]):
                a_txt = (a["text"] + " " + a["raw"]).lower()
                if ("pos" in cap_l and "pos" in a_txt) or ("printer" in cap_l and "printer" in a_txt) or (
                    "orientation" in cap_l and "orientation" in a_txt
                ) or (("laptop" in cap_l or "diagnostic" in cap_l or "dismantl" in cap_l) and "laptop" in a_txt):
                    act_id = keys.get(f"k{a_idx}", first_act_id)
                    break
            db.add_photo(day_id, rel, "work", act_id, caption=caption)
            imported_photos += 1

        for idx, (img_bytes, label) in enumerate(ncis_by_date.get(d["date"], []), start=1):
            rel = _save_image_bytes(img_bytes, d["date"], "w1_ncis", idx, as_png=True)
            db.add_photo(day_id, rel, "ncis", None, caption=label)
            imported_ncis += 1

        imported_days += 1

    db.save_week_data(1, WEEK1_REPORT)
    db.add_audit(
        "week",
        "1",
        "Imported Week 1 from finalized reference documents",
        actor=db.get_settings().get("student_name", "Jeriel Maningas"),
        remark="Cross-checked total: 29 hrs (manual form had 28 hrs). Friday IN/OUT left blank per source doc.",
    )
    total_m = rules.week_minutes(db.list_days())
    print(f"Imported {imported_days} days, {imported_photos} work photos, {imported_ncis} NCIS screenshots.")
    print(f"Verified Week 1 total: {rules.hours_label(total_m)} ({total_m} min).")


if __name__ == "__main__":
    run_import()
