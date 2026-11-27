"""
Weekly document generator.

Fills the six Word templates (tpl_*.docx) with one week of OJT data and
returns a ZIP file (bytes) that contains the six finished documents.

The templates keep the original layout, header, page size (8.5 x 13 in),
fonts and bullet styles. This module only replaces the content.
"""
import copy
import io
import os
import re
import zipfile

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt
from PIL import Image, ImageOps

import rules

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

TEMPLATES = {
    "daily": "tpl_daily.docx",
    "documentation": "tpl_documentation.docx",
    "learning": "tpl_learning.docx",
    "ncis": "tpl_ncis.docx",
    "training": "tpl_training.docx",
    "weekly": "tpl_weekly.docx",
}

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

# Elements that must come after <w:jc> inside <w:pPr> (schema order).
_AFTER_JC = {qn(t) for t in ("w:textDirection", "w:textAlignment", "w:textboxTightWrap",
                              "w:outlineLvl", "w:divId", "w:cnfStyle", "w:rPr",
                              "w:sectPr", "w:pPrChange")}
# Elements that may come before <w:b> inside <w:rPr>.
_BEFORE_B = {qn("w:rStyle"), qn("w:rFonts")}


# --------------------------------------------------------------------------
# Formatting helpers
# --------------------------------------------------------------------------
def long_date(d):
    """November 16, 2026"""
    return f"{d:%B} {d.day}, {d.year}"


def short_date(d):
    """11/16/2026"""
    return f"{d.month:02d}/{d.day:02d}/{d.year}"


def range_compact(a, b):
    """November 16 – 20, 2026 (handles month/year changes)."""
    if a == b:
        return long_date(a)
    if a.year != b.year:
        return f"{long_date(a)} – {long_date(b)}"
    if a.month != b.month:
        return f"{a:%B} {a.day} – {b:%B} {b.day}, {b.year}"
    return f"{a:%B} {a.day} – {b.day}, {b.year}"


def time_12h(value):
    """'17:18' -> '5:18' (same style as the sample form)."""
    if not value:
        return ""
    try:
        h, m = value.split(":")[:2]
        h = int(h)
        h12 = h % 12 or 12
        return f"{h12}:{int(m):02d}"
    except (ValueError, AttributeError):
        return str(value)


def hours_label(minutes):
    """95 -> '1 hr 35 min'"""
    return rules.hours_label(minutes)


# --------------------------------------------------------------------------
# Low-level XML helpers
# --------------------------------------------------------------------------
def _text(el):
    return "".join(t.text or "" for t in el.iter(qn("w:t")))


def _has_num(p):
    ppr = p.find(qn("w:pPr"))
    return ppr is not None and ppr.find(qn("w:numPr")) is not None


def _paras(tc):
    return tc.findall(qn("w:p"))


def _first(items, cond, default=None):
    for item in items:
        if cond(item):
            return item
    return default


def _set_jc(p, align):
    ppr = p.find(qn("w:pPr"))
    if ppr is None:
        ppr = OxmlElement("w:pPr")
        p.insert(0, ppr)
    jc = ppr.find(qn("w:jc"))
    if jc is None:
        jc = OxmlElement("w:jc")
        anchor = _first(list(ppr), lambda c: c.tag in _AFTER_JC)
        if anchor is not None:
            anchor.addprevious(jc)
        else:
            ppr.append(jc)
    jc.set(qn("w:val"), align)


def _set_flag(rpr, tag, on):
    """Set/clear bold or italic on a run properties element."""
    names = ("w:b", "w:bCs") if tag == "b" else ("w:i", "w:iCs")
    for name in names:
        for el in rpr.findall(qn(name)):
            rpr.remove(el)
    if not on:
        return
    # insert after rStyle/rFonts (and after b/bCs for italic)
    before = set(_BEFORE_B)
    if tag == "i":
        before |= {qn("w:b"), qn("w:bCs")}
    idx = 0
    for i, child in enumerate(list(rpr)):
        if child.tag in before:
            idx = i + 1
    for offset, name in enumerate(names):
        rpr.insert(idx + offset, OxmlElement(name))


def make_para(proto, text="", bold=None, italic=None, align=None):
    """Clone a prototype paragraph and give it new text (keeps its style)."""
    p = copy.deepcopy(proto)
    first_run = p.find(qn("w:r"))
    rpr = None
    if first_run is not None and first_run.find(qn("w:rPr")) is not None:
        rpr = copy.deepcopy(first_run.find(qn("w:rPr")))
    else:
        ppr = p.find(qn("w:pPr"))
        if ppr is not None and ppr.find(qn("w:rPr")) is not None:
            rpr = copy.deepcopy(ppr.find(qn("w:rPr")))
    for child in list(p):
        if child.tag != qn("w:pPr"):
            p.remove(child)
    if align:
        _set_jc(p, align)
    if text:
        if rpr is None:
            rpr = OxmlElement("w:rPr")
        # drop proofing / page-break leftovers
        for tag in ("w:noProof",):
            for el in rpr.findall(qn(tag)):
                rpr.remove(el)
        if bold is not None:
            _set_flag(rpr, "b", bold)
        if italic is not None:
            _set_flag(rpr, "i", italic)
        lines = str(text).replace("\r", "").split("\n")
        r = OxmlElement("w:r")
        r.append(rpr)
        for i, line in enumerate(lines):
            if i:
                r.append(OxmlElement("w:br"))
            t = OxmlElement("w:t")
            t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
            t.text = line
            r.append(t)
        p.append(r)
    return p


def set_cell(tc, paragraphs, blank_proto=None):
    """Replace every paragraph in a table cell."""
    for child in list(tc):
        if child.tag != qn("w:tcPr"):
            tc.remove(child)
    if not paragraphs:
        proto = blank_proto if blank_proto is not None else OxmlElement("w:p")
        paragraphs = [make_para(proto)]
    for p in paragraphs:
        tc.append(p)


def clean_items(items):
    return rules.clean_items(items)


_PH = re.compile(r"\{\{(\w+)(?:\|(\d+))?\}\}")


def fill_placeholders(doc, values):
    """Replace {{KEY}} or {{KEY|width}} placeholders in body text."""
    def repl(m):
        val = str(values.get(m.group(1), ""))
        width = int(m.group(2)) if m.group(2) else 0
        if width and len(val) < width:
            pad = width - len(val)
            val = " " * (pad // 2) + val + " " * (pad - pad // 2)
        return val
    for t in doc.element.body.iter(qn("w:t")):
        if t.text and "{{" in t.text:
            t.text = _PH.sub(repl, t.text)
            t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")


def _body_children(doc):
    return [c for c in doc.element.body.iterchildren() if c.tag != qn("w:sectPr")]


def _remove_after(doc, keep_count):
    for child in _body_children(doc)[keep_count:]:
        doc.element.body.remove(child)


def _append_body(doc, el):
    doc.element.body.find(qn("w:sectPr")).addprevious(el)


# --------------------------------------------------------------------------
# Image helpers
# --------------------------------------------------------------------------
def _open_image(path):
    img = Image.open(path)
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "L"):
        bg = Image.new("RGB", img.size, "white")
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGBA")
            bg.paste(img, mask=img.split()[-1])
            img = bg
        else:
            img = img.convert("RGB")
    return img


def _to_stream(img, max_px=1400):
    img = img.copy()
    img.thumbnail((max_px, max_px))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    buf.seek(0)
    return buf


def cropped_photo(path, box_w, box_h):
    """Center-crop a photo to the box ratio so the grid looks tidy."""
    img = _open_image(path)
    target = box_w / box_h
    w, h = img.size
    if w / h > target:
        new_w = int(h * target)
        left = (w - new_w) // 2
        img = img.crop((left, 0, left + new_w, h))
    else:
        new_h = int(w / target)
        top = (h - new_h) // 2
        img = img.crop((0, top, w, top + new_h))
    return _to_stream(img)


def fitted_image(path, max_w, max_h):
    """Keep aspect ratio; returns (stream, width_in, height_in)."""
    img = _open_image(path)
    w, h = img.size
    scale = min(max_w / w, max_h / h)
    return _to_stream(img, 2000), w * scale, h * scale


def _picture_run(doc, stream, width_in, height_in):
    inline = doc.part.new_pic_inline(stream, Inches(width_in), Inches(height_in))
    r = OxmlElement("w:r")
    drawing = OxmlElement("w:drawing")
    drawing.append(inline)
    r.append(drawing)
    return r


# --------------------------------------------------------------------------
# 1. Daily Attendance and Accomplishment Form
# --------------------------------------------------------------------------
def _run(text="", bold=False, underline=False, size_pt=None, tab=False):
    r = OxmlElement("w:r")
    rpr = OxmlElement("w:rPr")
    rfonts = OxmlElement("w:rFonts")
    for attr in ("w:ascii", "w:hAnsi", "w:cs"):
        rfonts.set(qn(attr), "Arial")
    rpr.append(rfonts)
    if bold:
        rpr.append(OxmlElement("w:b"))
        rpr.append(OxmlElement("w:bCs"))
    if underline:
        u = OxmlElement("w:u")
        u.set(qn("w:val"), "single")
        rpr.append(u)
    if size_pt is not None:
        val = str(int(round(size_pt * 2)))
        sz = OxmlElement("w:sz")
        sz.set(qn("w:val"), val)
        szCs = OxmlElement("w:szCs")
        szCs.set(qn("w:val"), val)
        rpr.append(sz)
        rpr.append(szCs)
    r.append(rpr)
    if tab:
        r.append(OxmlElement("w:tab"))
    if text:
        t = OxmlElement("w:t")
        t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        t.text = text
        r.append(t)
    return r


def _set_tabs(p, stops):
    ppr = p.find(qn("w:pPr"))
    if ppr is None:
        ppr = OxmlElement("w:pPr")
        p.insert(0, ppr)
    for old in ppr.findall(qn("w:tabs")):
        ppr.remove(old)
    tabs = OxmlElement("w:tabs")
    for val, pos in stops:
        tab = OxmlElement("w:tab")
        tab.set(qn("w:val"), val)
        tab.set(qn("w:pos"), str(pos))
        tabs.append(tab)
    anchor = _first(list(ppr), lambda c: c.tag in _AFTER_JC or c.tag == qn("w:jc"))
    if anchor is not None:
        anchor.addprevious(tabs)
    else:
        ppr.append(tabs)


def _clear_runs(p):
    for child in list(p):
        if child.tag != qn("w:pPr"):
            p.remove(child)


def _format_label_pair(p, left_label, right_label, right_pos, right_align="left"):
    _clear_runs(p)
    _set_tabs(p, [(right_align, right_pos)])
    p.append(_run(left_label))
    p.append(_run(right_label, tab=True))


def _format_underlined_pair(p, left_text, right_text, left_end, right_start, right_end,
                            left_size=None, right_size=None):
    """Put two cleanly centered, underlined fields on one single line using explicit tab stops."""
    _clear_runs(p)
    left_mid = left_end // 2
    right_mid = (right_start + right_end) // 2
    _set_tabs(p, [
        ("center", left_mid),
        ("right", left_end),
        ("left", right_start),
        ("center", right_mid),
        ("right", right_end),
    ])
    # Left underlined field: 0 .. left_end
    p.append(_run("\u00a0", underline=True))
    p.append(_run(left_text or "\u00a0", bold=True, underline=True, size_pt=left_size, tab=True))
    p.append(_run("\u00a0", underline=True, tab=True))
    # Gap (not underlined): left_end .. right_start
    p.append(_run("", underline=False, tab=True))
    # Right underlined field: right_start .. right_end
    p.append(_run("\u00a0", underline=True))
    p.append(_run(right_text or "\u00a0", bold=True, underline=True, size_pt=right_size, tab=True))
    p.append(_run("\u00a0", underline=True, tab=True))


def fill_daily(doc, wk):
    # Ensure Student Name / Internship Site and Signature / Date lines never wrap awkwardly
    children = _body_children(doc)
    site = (wk.get("site") or "").strip()
    site_size = 10.0 if len(site) > 40 else (10.5 if len(site) > 30 else None)
    sup = (wk.get("supervisor_name") or "").strip().upper()
    sup_size = 10.5 if len(sup) > 28 else None
    student = (wk.get("student_name") or "").strip().upper()
    certdate = short_date(wk["end"])

    if len(children) > 5 and children[4].tag == qn("w:p") and children[5].tag == qn("w:p"):
        _format_label_pair(children[4], "Student Name:", "Internship Site:", 4200)
        _format_underlined_pair(children[5], student, site, 3800, 4200, 9450, right_size=site_size)
    if len(children) > 15 and children[14].tag == qn("w:p") and children[15].tag == qn("w:p"):
        _format_underlined_pair(children[14], sup, certdate, 5200, 6200, 9000, left_size=sup_size)
        _format_label_pair(children[15], "Company Supervisor\u2019s Signature", "Date", 7600, right_align="center")
    if len(children) > 19 and children[18].tag == qn("w:p") and children[19].tag == qn("w:p"):
        _format_underlined_pair(children[18], student, certdate, 5200, 6200, 9000)
        _format_label_pair(children[19], "Student Intern\u2019s Signature", "Date", 7600, right_align="center")

    tbl = doc.element.body.find(qn("w:tbl"))
    rows = tbl.findall(qn("w:tr"))
    proto = rows[1].findall(qn("w:tc"))
    p_day = copy.deepcopy(_paras(proto[0])[0])
    p_time = copy.deepcopy(_paras(proto[1])[0])
    acc_paras = _paras(proto[5])
    p_acc = copy.deepcopy(_first(acc_paras, _has_num, acc_paras[0]))
    ver = _paras(proto[7])
    p_vname = copy.deepcopy(_first(ver, lambda p: _text(p).strip(), ver[0]))
    p_vtitle = copy.deepcopy(ver[1] if len(ver) > 1 else ver[0])

    by_weekday = {d["date"].weekday(): d for d in wk["days"]}
    for i in range(7):
        row = rows[i + 1]
        cells = row.findall(qn("w:tc"))
        day = by_weekday.get(i)
        # compact row height; content decides the final height
        trh = row.find(qn("w:trPr"))
        if trh is not None and trh.find(qn("w:trHeight")) is not None:
            trh.find(qn("w:trHeight")).set(qn("w:val"), "700" if day else "400")
        set_cell(cells[0], [make_para(p_day, DAY_NAMES[i], align="center")])
        times = ["morning_in", "morning_out", "afternoon_in", "afternoon_out"]
        for c, key in enumerate(times, start=1):
            val = time_12h(day.get(key)) if day else ""
            set_cell(cells[c], [make_para(p_time, val, align="center")])
        if day:
            acc = [make_para(p_acc, a["text"]) for a in day["activities"] if a.get("text")]
            set_cell(cells[5], acc, p_time)
            set_cell(cells[6], [make_para(p_time, hours_label(day["minutes"]), align="center")])
            vparas = []
            for n, v in enumerate(day.get("verifiers") or []):
                if not v.get("name"):
                    continue
                if vparas:
                    vparas.append(make_para(p_time))
                vparas.append(make_para(p_vname, v["name"], bold=True, align="center"))
                if v.get("title"):
                    vparas.append(make_para(p_vtitle, v["title"], bold=False, align="center"))
            set_cell(cells[7], vparas, p_time)
        else:
            for c in (5, 6, 7):
                set_cell(cells[c], [], p_time)

    total_cells = rows[8].findall(qn("w:tc"))
    total = sum(d["minutes"] for d in wk["days"])
    set_cell(total_cells[1], [make_para(p_time, hours_label(total), bold=True, align="center")])


# --------------------------------------------------------------------------
# 2. Documentations (picture & work)
# --------------------------------------------------------------------------
DOC_TABLE_WIDTH = 9465  # dxa (same as the template)
PHOTO_BOX = {1: (4.60, 3.10), 2: (3.05, 2.45)}


def _shade(cell, fill):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    tcPr.append(shd)


def _vcenter(cell):
    tcPr = cell._tc.get_or_add_tcPr()
    for old in tcPr.findall(qn("w:vAlign")):
        tcPr.remove(old)
    va = OxmlElement("w:vAlign")
    va.set(qn("w:val"), "center")
    tcPr.append(va)


def _fmt_para(paragraph, keep_next=False):
    pf = paragraph.paragraph_format
    pf.space_before = Pt(0)
    pf.space_after = Pt(0)
    pf.line_spacing = 1.0
    pf.keep_with_next = keep_next
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER


def _cant_split(row):
    trPr = row._tr.get_or_add_trPr()
    trPr.append(OxmlElement("w:cantSplit"))


def _photo_table(doc, day, photos):
    n = len(photos)
    cols = 1 if n == 1 else 2
    box_w, box_h = PHOTO_BOX[cols]
    chunks = [photos[i:i + cols] for i in range(0, n, cols)]
    table = doc.add_table(rows=1 + 2 * len(chunks), cols=cols)
    try:
        table.style = doc.styles["Table Grid"]
    except KeyError:
        pass
    col_w = DOC_TABLE_WIDTH // cols
    for row in table.rows:
        for cell in row.cells:
            cell.width = Inches(col_w / 1440)

    # header row with the date
    head = table.rows[0].cells[0]
    if cols > 1:
        head = head.merge(table.rows[0].cells[-1])
    _shade(head, "E2EFD9")
    p = head.paragraphs[0]
    _fmt_para(p, keep_next=True)
    run = p.add_run(long_date(day["date"]))
    run.bold = True
    run.font.name = "Arial"
    run.font.size = Pt(12)
    _cant_split(table.rows[0])

    for ci, chunk in enumerate(chunks):
        pic_row = table.rows[1 + ci * 2]
        cap_row = table.rows[2 + ci * 2]
        _cant_split(pic_row)
        _cant_split(cap_row)
        for k in range(cols):
            _vcenter(pic_row.cells[k])
            pic_p = pic_row.cells[k].paragraphs[0]
            cap_p = cap_row.cells[k].paragraphs[0]
            _fmt_para(pic_p, keep_next=True)
            _fmt_para(cap_p, keep_next=ci < len(chunks) - 1)
            if k >= len(chunk):
                continue
            photo = chunk[k]
            try:
                stream, w_in, h_in = fitted_image(photo["path"], box_w, box_h)
                pic_p._p.append(_picture_run(doc, stream, w_in, h_in))
            except Exception:  # unreadable image: keep the caption only
                pass
            cap = cap_p.add_run(photo.get("caption") or "")
            cap.font.name = "Arial"
            cap.font.size = Pt(12)
    # blank line between tables
    doc.add_paragraph()


def fill_documentation(doc, wk):
    _remove_after(doc, 1)  # keep the title only
    any_photo = False
    for day in wk["days"]:
        photos = [p for p in day.get("photos", []) if p.get("path") and os.path.exists(p["path"])]
        if photos:
            any_photo = True
            _photo_table(doc, day, photos)
    if not any_photo:
        doc.add_paragraph("No photos uploaded for this week.")


# --------------------------------------------------------------------------
# 3. Learning Outcomes
# --------------------------------------------------------------------------
def fill_learning(doc, wk):
    tbl = doc.element.body.find(qn("w:tbl"))
    row = tbl.findall(qn("w:tr"))[1]
    cells = row.findall(qn("w:tc"))
    p_date = copy.deepcopy(_paras(cells[0])[0])
    c1 = _paras(cells[1])
    p_blank = copy.deepcopy(_first(c1, lambda p: not _has_num(p), c1[0]))
    p_act = copy.deepcopy(_first(c1, _has_num, c1[-1]))
    c2 = _paras(cells[2])
    p_out = copy.deepcopy(_first(c2, _has_num, c2[0]))

    set_cell(cells[0], [make_para(p_date, range_compact(wk["start"], wk["end"]), align="center")])
    acts = [make_para(p_act, a) for a in clean_items(wk["learning_activities"])]
    set_cell(cells[1], [make_para(p_blank)] + acts, p_blank)
    outs = [make_para(p_out, o) for o in clean_items(wk["learning_outcomes"])]
    set_cell(cells[2], outs, p_blank)


# --------------------------------------------------------------------------
# 4. NCIS Attendance Monitoring
# --------------------------------------------------------------------------
def fill_ncis(doc, wk):
    children = _body_children(doc)
    # [0]=title, [1]=blank, [2]=date prototype, [3]=blank prototype
    p_date = copy.deepcopy(children[2])
    p_blank = copy.deepcopy(children[3])
    _remove_after(doc, 2)

    entries = []
    for day in wk["days"]:
        default_label = long_date(day["date"])
        for item in day.get("ncis", []):
            if isinstance(item, dict):
                path = item.get("path")
                label = (item.get("label") or "").strip() or default_label
            else:
                path = item
                label = default_label
            if path and os.path.exists(path):
                entries.append((label, path))

    if not entries:
        _append_body(doc, make_para(p_blank, "No NCIS attendance screenshots uploaded for this week."))
        return

    last_label = None
    for label, path in entries:
        try:
            stream, w, h = fitted_image(path, 6.2, 5.2)
        except Exception:
            continue
        if label != last_label:
            if last_label is not None:
                _append_body(doc, make_para(p_blank))
            _append_body(doc, make_para(p_date, label))
            last_label = label
        p = make_para(p_blank, align="center")
        p.append(_picture_run(doc, stream, w, h))
        _append_body(doc, p)
        _append_body(doc, make_para(p_blank))


# --------------------------------------------------------------------------
# 5. Training Schedule Form
# --------------------------------------------------------------------------
def fill_training(doc, wk):
    tbl = doc.element.body.find(qn("w:tbl"))
    rows = tbl.findall(qn("w:tr"))
    proto_row = copy.deepcopy(rows[1])
    for r in rows[1:]:
        tbl.remove(r)
    pc = proto_row.findall(qn("w:tc"))
    p_cat = copy.deepcopy(_paras(pc[0])[0])
    c1 = _paras(pc[1])
    p_how = copy.deepcopy(_first(c1, _has_num, c1[0]))
    p_trainer = copy.deepcopy(_paras(pc[2])[0])
    p_time = copy.deepcopy(_paras(pc[3])[0])
    c4 = _paras(pc[4])
    p_out = copy.deepcopy(_first(c4, _has_num, c4[0]))

    items = wk.get("training") or []
    for item in items:
        row = copy.deepcopy(proto_row)
        trh = row.find(qn("w:trPr"))
        if trh is not None and trh.find(qn("w:trHeight")) is not None:
            trh.remove(trh.find(qn("w:trHeight")))
        cells = row.findall(qn("w:tc"))
        set_cell(cells[0], [make_para(p_cat, item.get("category", ""), bold=True, align="center")])
        set_cell(cells[1], [make_para(p_how, h) for h in clean_items(item.get("how"))], p_time)
        tparas = []
        for name in clean_items(item.get("trainers")):
            if tparas:
                tparas.append(make_para(p_trainer))
            tparas.append(make_para(p_trainer, name, bold=True, align="center"))
        set_cell(cells[2], tparas, p_time)
        raw_tl = item.get("timeline")
        if isinstance(raw_tl, list):
            tl_items = clean_items(raw_tl)
        else:
            tl_items = clean_items(str(raw_tl or "").splitlines())
        tl_paras = [make_para(p_time, tl, bold=False, align="center") for tl in tl_items]
        set_cell(cells[3], tl_paras, p_time)
        set_cell(cells[4], [make_para(p_out, o) for o in clean_items(item.get("outputs"))], p_time)
        tbl.append(row)
    if not items:
        tbl.append(proto_row)
        for tc in proto_row.findall(qn("w:tc")):
            set_cell(tc, [], p_time)


# --------------------------------------------------------------------------
# 6. Weekly Progress Report
# --------------------------------------------------------------------------
def _question_cell(tc, items, fallback_bullet):
    paras = _paras(tc)
    heading = copy.deepcopy(paras[0])
    blank = copy.deepcopy(_first(paras[1:], lambda p: not _text(p).strip() and not _has_num(p),
                                 make_para(paras[0])))
    bullet = copy.deepcopy(_first(paras, _has_num, fallback_bullet))
    new = [heading, make_para(blank)]
    new += [make_para(bullet, item) for item in clean_items(items)]
    set_cell(tc, new)


def fill_weekly(doc, wk):
    tbl = doc.element.body.find(qn("w:tbl"))
    rows = tbl.findall(qn("w:tr"))
    first_cell = rows[0].findall(qn("w:tc"))[0]
    fallback_bullet = copy.deepcopy(_first(_paras(first_cell), _has_num, _paras(first_cell)[-1]))

    _question_cell(rows[0].findall(qn("w:tc"))[0], wk["duties"], fallback_bullet)
    _question_cell(rows[1].findall(qn("w:tc"))[0], wk["new_trainings"], fallback_bullet)

    c_left, c_right = rows[4].findall(qn("w:tc"))[:2]
    lp = _paras(c_left)
    p_prop = copy.deepcopy(_first(lp, _has_num, lp[0]))
    rp = _paras(c_right)
    p_rblank = copy.deepcopy(rp[0])
    p_acc = copy.deepcopy(_first(rp, lambda p: _text(p).strip(), rp[-1]))
    set_cell(c_left, [make_para(p_prop, x) for x in clean_items(wk["proposed"])], p_rblank)
    right = [make_para(p_rblank)] + [make_para(p_acc, x) for x in clean_items(wk["accomplishments"])]
    set_cell(c_right, right)

    _question_cell(rows[5].findall(qn("w:tc"))[0], wk["problems"], fallback_bullet)
    _question_cell(rows[6].findall(qn("w:tc"))[0], wk["solutions"], fallback_bullet)
    _question_cell(rows[7].findall(qn("w:tc"))[0], wk["goals"], fallback_bullet)


# --------------------------------------------------------------------------
# Build the ZIP
# --------------------------------------------------------------------------
FILLERS = [
    ("daily", fill_daily, "DAILY ATTENDANCE AND ACCOMPLISHMENT FORM W{n}{suffix}.docx"),
    ("documentation", fill_documentation, "DOCUMENTATIONS.docx"),
    ("learning", fill_learning, "LEARNING OUTCOMES.docx"),
    ("ncis", fill_ncis, "NCIS ATTENDANCE MONITORING.docx"),
    ("training", fill_training, "TRAINING SCHEDULE FORM.docx"),
    ("weekly", fill_weekly, "WEEKLY PROGRESS REPORT W{n}{suffix}.docx"),
]


def _last_name_suffix(student_name):
    return rules.last_name_suffix(student_name)


def build_document(kind, wk, template_dir=BASE_DIR):
    filler = {k: f for k, f, _ in FILLERS}[kind]
    doc = Document(os.path.join(template_dir, TEMPLATES[kind]))
    fill_placeholders(doc, {
        "NAME": wk["student_name"].upper(),
        "SITE": wk["site"],
        "START": long_date(wk["start"]),
        "END": long_date(wk["end"]),
        "RANGE": f"{long_date(wk['start'])} to {long_date(wk['end'])}",
        "WEEKNO": wk["number"],
        "SUPERVISOR": wk["supervisor_name"].upper(),
        "SUPERVISOR_TITLE": wk["supervisor_title"],
        "CERTDATE": short_date(wk["end"]),
    })
    filler(doc, wk)
    doc.core_properties.author = wk["student_name"]
    doc.core_properties.last_modified_by = wk["student_name"]
    doc.core_properties.title = f"Week {wk['number']}"
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def build_week_zip(wk, template_dir=BASE_DIR):
    folder = f"WEEK {wk['number']}"
    suffix = _last_name_suffix(wk.get("student_name"))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for kind, _, name in FILLERS:
            data = build_document(kind, wk, template_dir)
            zf.writestr(f"{folder}/{name.format(n=wk['number'], suffix=suffix)}", data)
    return out.getvalue()
