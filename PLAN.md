# OJT Journal — System Design & Handoff Plan

## 1. Background & Current Manual Process
BSIT interns at **Aljay Agro-Industrial Solutions, Inc.** (College of Information Technology) must submit a weekly 6-document OJT pack every Friday:
1. `DAILY ATTENDANCE AND ACCOMPLISHMENT FORM W{n} - {LASTNAME}.docx`
2. `DOCUMENTATIONS.docx` (Picture & Work)
3. `LEARNING OUTCOMES.docx`
4. `NCIS ATTENDANCE MONITORING.docx`
5. `TRAINING SCHEDULE FORM.docx`
6. `WEEKLY PROGRESS REPORT W{n} - {LASTNAME}.docx`

### Manual workflow (before automation)
- **Inputs typed by the intern**: Daily Morning/Afternoon IN–OUT times, activity notes (often written in rough English or Taglish), duration per task, "Verified by" staff names & positions (different staff on different days), work photos + captions, NCIS attendance screenshots (sometimes grouped across multiple days), and weekly reflection (problems, solutions, goals).
- **Values looked up / repeated**: Student name (`Jeriel Maningas`), internship site (`Aljay Agro-Industrial Solutions, Inc.`), company supervisor (`Jerwin Dominick A. Bernabe`, `IT Supervisor`), date ranges, certification date, and recurring verifiers (`Luis D. Solmayor`, `Jerwin Dominick A. Bernabe`, `Nikki Dela Cruz`, `Jerry Apostol Jr.`).
- **People & order**: Intern records daily tasks & photos -> Staff/supervisors sign daily "Verified by" -> Intern compiles 6 Word docs at week's end -> Company supervisor signs certification & "Noted by" -> Intern submits to OJT coordinator.

### Measured data-quality audit (real Week 1 documents in `needed files/`)
Auditing the 5 finalized Week 1 `.docx` files (`Nov 16–20, 2026`) uncovered **11 concrete manual errors**:
- **1 arithmetic error**: Daily hours (`4h + 7h 30m + 4h 30m + 6h + 7h`) sum to **`29 hrs`**, but the manual sheet totaled **`28 hrs`** (1 hour lost!).
- **1 missing attendance row**: Friday (`Nov 20`) had all 4 Morning/Afternoon IN–OUT cells blank.
- **2 uncaptioned photos**: `Nov 16` row 3 had 2 embedded work photos with no caption row underneath.
- **4 spelling / casing errors**: `luquidation`, `chech`, `Simpe`, `Jerwin dominick a. Bernabe` / `IT supervisor`.
- **2 copy-paste / formatting errors**: Duplicate concatenated duty text (`ENCODED STATEMENTS OF CASH AND CHECK DISBURSEMENT...`) in Weekly Progress Report and double bullets (`• - ...`) in Proposed Activities.
- **1 outdated company name**: `Aljay Bioscience, Inc.` left in the template instead of `Aljay Agro-Industrial Solutions, Inc.`.

---

## 2. Business Rules & Exact Formulas (`rules.py`)
All calculations and validations live in ONE shared module ([rules.py](rules.py)) used by `database.py`, `app.py`, `docgen.py`, `import_week1.py`, and tests:

- **Activity duration (minutes)**:
  - If valid `start_time` and `end_time` (`HH:MM`) with `end > start`: `minutes = (end_h * 60 + end_m) - (start_h * 60 + start_m)`
  - Else: `minutes = max(0, int(manual_minutes))`
- **Day total (minutes)**: `day_minutes = sum(activity.minutes for activity in day.activities)`. (Attendance IN/OUT is for the attendance columns only; rendered hours strictly come from activity durations.)
- **Week total (minutes)**: `week_minutes = sum(day.minutes for day in week_days)`
- **OJT progress**:
  - `total_minutes = sum(all_days.minutes) + round(prior_hours * 60)`
  - `required_minutes = round(required_hours * 60)` (default `486 * 60 = 29,160 min`)
  - `remaining_minutes = max(required_minutes - total_minutes, 0)`
  - `pct = min(100.0, total_minutes / required_minutes * 100)`
  - `avg_per_day = logged_total / count(days)` (if `days > 0`)
  - `estimated_finish`: advance weekday-by-weekday (`Mon–Fri`) from `max(today, last_logged_date)` by `ceil(remaining_minutes / avg_per_day)` weekdays.
- **Week numbering**:
  - `week_monday = start_date - timedelta(days=start_date.weekday())`
  - `week_number(d) = (d - week_monday).days // 7 + 1`
  - `week_range(n) = (week_monday + (n-1)*7 days, monday + 6 days)`
- **Formatting**:
  - UI compact format: `fmt_minutes(270) -> "4h 30m"`, `fmt_minutes(240) -> "4h"`
  - Official form format: `hours_label(270) -> "4 hrs 30 min"`, `hours_label(60) -> "1 hr"`
  - Bullet cleanup: strip leading `[-•*●]\s*` to prevent double bullets.
  - Export filename suffix: uppercase last token of `student_name` (e.g., ` - MANINGAS`).

---

## 3. Data Dictionary
| Entity | Field | Type | Notes |
|---|---|---|---|
| `settings` | `student_name` | TEXT | Full name (uppercased automatically in official docs) |
| `settings` | `internship_site` | TEXT | Company name in business/title case (`Aljay Agro-Industrial Solutions, Inc.`) |
| `settings` | `start_date` | TEXT (`YYYY-MM-DD`) | First day of OJT (`2026-11-16`) |
| `settings` | `required_hours` | TEXT (float) | Required total OJT hours (`486`) |
| `settings` | `prior_hours` | TEXT (float) | Optional hours completed outside the app (`0`) |
| `settings` | `supervisor_name`, `supervisor_title` | TEXT | Certification & "Noted by" signatory |
| `settings` | `saved_verifiers` | JSON list | `[{name, title, keywords}]` smart type-to-fill directory |
| `settings` | `default_verifiers` | JSON list | Optional auto-added verifiers on new days |
| `settings` | `groq_api_key`, `groq_model` | TEXT | Local-only Groq API credentials |
| `settings` | `phone_access`, `phone_pin` | TEXT | Optional LAN WiFi phone access guard |
| `days` | `date`, `morning_in/out`, `afternoon_in/out`, `verifiers` | TEXT / JSON | One row per unique date |
| `activities` | `day_id`, `position`, `start_time`, `end_time`, `minutes`, `raw_text`, `text`, `caption` | INT / TEXT | Ordered tasks for a day |
| `photos` | `day_id`, `activity_id`, `kind` (`work`\|`ncis`), `filename`, `caption` | INT / TEXT | For `ncis`, `caption` stores optional custom date range label (e.g. `November 18–20, 2026`) |
| `weeks` | `number`, `data` (JSON) | INT / JSON | Weekly report content + `status` (`draft`, `ready`, `submitted`, `approved`) |
| `audit_log` | `entity`, `entity_id`, `action`, `actor`, `remark`, `created_at` | TEXT | Immutable history of saves, exports, status changes, and reopens |

---

## 4. Roles, Workflow & Controls
- **Roles**:
  - **Student Intern** (`Jeriel Maningas`): Creates daily entries, captures/uploads photos & NCIS screenshots, runs AI polishing, reviews pre-flight warnings, exports ZIP, updates weekly status.
  - **Daily Verifiers** (e.g., `Luis D. Solmayor`, `Jerwin Dominick A. Bernabe`, `Nikki Dela Cruz`, `Jerry Apostol Jr.`): Recorded per day via smart keyword auto-fill; physically sign printed Daily Attendance form.
  - **Company Supervisor** (`Jerwin Dominick A. Bernabe`, `IT Supervisor`): Signs certification on Daily Attendance and "Noted by" on Weekly Progress Report.
- **Weekly Pack Lifecycle**:
  - `Draft` -> `Ready to Submit` -> `Submitted` *(locked)* -> `Approved` *(locked)*
  - **Locking**: While a week is `Submitted` or `Approved`, editing or deleting its daily entries or weekly report text is blocked (`POST` rejected with error flash; UI Save button disabled). Exporting the ZIP remains allowed.
  - **Reopen with Remark**: Returning a `Submitted` or `Approved` week back to `Draft` requires a non-empty `remark` explaining why, recorded permanently in `audit_log`.

---

## 5. Features by Phase
- **Phase 1 (Implemented — Core + Real-Process Upgrades)**:
  - Local Flask + SQLite app, single-click `run.bat` with self-healing `.venv`.
  - Smart type-to-fill Verifiers directory (keyword autocomplete + quick-add chips + auto-learning new names).
  - Uncropped aspect-ratio-preserving `DOCUMENTATIONS.docx` (2-column grid for 2+ photos, vertically centered).
  - Multi-day / grouped NCIS screenshot labels (`November 18–20, 2026`) with automatic skipping of empty NCIS days.
  - Clean single-line tab-stopped headers & signature lines on `DAILY ATTENDANCE` for long company/supervisor names.
  - Shared `rules.py` formulas, blocking vs. warning pre-flight checklist, week locking + reopen-with-remark + audit trail.
  - Real Week 1 import (`import_week1.py`) with all 5 days, 20 work photos, and 3 NCIS screenshots.
  - Optional iPhone/LAN WiFi photo upload with PIN + QR code.
- **Phase 2 (Future / Optional)**:
  - Direct PDF export alongside `.docx` (requires LibreOffice or Microsoft Word COM automation).
  - Multi-week cumulative report / DTR summary export at OJT completion.

---

## 6. Data Model (SQLite)
Tables in `data/ojt_journal.db`: `settings`, `days`, `activities` (`ON DELETE CASCADE`), `photos` (`ON DELETE CASCADE` / `SET NULL`), `weeks`, `audit_log`. Foreign keys enforced via `PRAGMA foreign_keys = ON`.

---

## 7. API & Route List
| Method & Path | Purpose |
|---|---|
| `GET /` | Dashboard (hours progress, weekly packs + statuses, recent entries) |
| `GET /entry` | Redirect to today's (or start date's) daily entry |
| `GET/POST /entry/<YYYY-MM-DD>` | View/create/edit daily entry, activities, verifiers, work photos, NCIS screenshots + labels |
| `POST /entry/<YYYY-MM-DD>/delete` | Delete a daily entry (blocked if week is locked) |
| `GET /days` | Chronological list of all entries grouped by week |
| `GET/POST /week/<n>` | View/edit weekly report, pre-flight checklist, audit trail, download `WEEK <n>.zip` |
| `POST /week/<n>/status` | Transition week status (`draft`, `ready`, `submitted`, `approved`); requires `remark` to reopen |
| `GET/POST /settings` | Manage OJT details, prior hours, supervisor, saved verifiers directory, AI key/model, phone PIN |
| `GET /backup` | Download full ZIP backup of `data/` (SQLite DB + all uploaded photos) |
| `GET/POST /phone-login` | PIN authentication for non-localhost devices on the same WiFi |
| `POST /api/polish` | Groq AI: polish rough/Taglish activity notes into English + photo captions |
| `POST /api/reflection` | Groq AI: polish weekly reflection notes into bullet lists |
| `POST /api/week/<n>/generate` | Groq AI: draft weekly report + learning outcomes + training schedule from daily entries |
| `POST /api/test-ai` | Verify Groq API key and model connectivity |

---

## 8. Screen List
1. **Dashboard** (`dashboard.html`): Progress bar (`logged + prior / required`), days attended, daily average, estimated finish date, weekly status list, recent 5 entries.
2. **Daily Entry** (`entry.html`): Date & IN/OUT grid, activity cards with live duration calculation + AI polish + photo uploader, Smart Type-to-Fill Verifiers + quick-add chips, NCIS uploader with optional multi-day date label, day validation warnings.
3. **All Entries** (`days.html`): Jump-to-date picker and grouped weekly tables.
4. **Weekly Report** (`week.html`): Status badge & lock/reopen bar, Pre-flight Validation card (Blocking Errors / Warnings / Cross-check Info), week days overview, reflection & AI report editors, Training Schedule category cards, Download ZIP bar, Audit Trail.
5. **Settings** (`settings.html`): Student/site/prior hours, Supervisor, Saved Verifiers directory (with shortcut keywords), optional Default Verifiers, default attendance times, Groq AI settings, Phone Access + QR code, Backup button.
6. **Phone Login** (`phone_login.html`): PIN pad for LAN phone access.

---

## 9. Capture & AI Automation Approach (and Honest Limits)
- **Fast path**: Log rough Taglish/English notes and photos right from your phone on the same WiFi or laptop; type a 1-word keyword (`luis`, `it`, `nikki`, `jerry`) to auto-fill verifiers; click **Polish with AI** to fix spelling/casing typos and draft weekly sections.
- **Honest limits (human review still required)**:
  - The intern must review AI-polished text before saving to confirm no technical detail was phrased inaccurately.
  - Printed forms still require physical wet signatures from verifiers and the company supervisor.
  - Attendance IN/OUT times are not read automatically from NCIS screenshots via OCR; the intern enters or checks them (and the pre-flight validator flags blank times).

---

## 10. Validation Rules
- **Blocking Errors** (prevent ZIP export and submission/approval):
  - Week has 0 logged entries.
  - `student_name` is empty in Settings.
  - Entry date is invalid, duplicate, or before `start_date`.
  - Editing/deleting an entry or weekly report while its week is `Submitted` or `Approved`.
  - Reopening a locked week without providing a `remark`.
- **Warnings** (non-blocking — highlighted clearly on Daily Entry & Weekly Pre-flight Check):
  - Blank or partially filled Morning/Afternoon IN–OUT times on a logged day (e.g., Week 1 Friday).
  - Activity with `0` minutes logged.
  - Activity with rough notes not yet polished into English.
  - Missing `Verified by` name on a logged day.
  - Blank `internship_site` or `supervisor_name` in Settings.
  - Missing work photos, missing NCIS screenshots, or incomplete Weekly Progress / Training Schedule sections.
- **Info**:
  - Arithmetic cross-checked week total (`hours_label`) and day count.
  - Media count (`work photos` and `NCIS screenshots`).

---

## 11. Acceptance Tests & Expected Numbers
1. **Week 1 Arithmetic Cross-Check**: Importing `Nov 16–20, 2026` (`4h + 7h 30m + 4h 30m + 6h + 7h`) yields **`1740 minutes` = `29 hrs`** (fixing the manual sheet's `28 hrs`), `5` days attended, `5h 48m` average/day, `6.0%` of `486h`, `457h` remaining.
2. **Never-Guess Validation**: Week 1 Friday has blank IN/OUT times -> `validate_week()` returns `0` blocking errors and includes a warning naming `Fri Nov 20`.
3. **Smart Verifier Auto-Fill**: Typing `"luis"` or `"acct"` resolves to `Luis D. Solmayor` / `Accounting Supervisor`; typing `"it"` or `"jerwin"` resolves to `Jerwin Dominick A. Bernabe` / `IT Supervisor`; saving a new verifier auto-adds it to `saved_verifiers`.
4. **Workflow Lock & Reopen**: Marking Week 1 `Submitted` blocks `POST /entry/2026-11-20` and `POST /week/1` (save), still allows `POST /week/1` (`action=download`), rejects reopening with an empty remark, and unlocks when reopened with a non-empty remark (logged in `audit_log`).
5. **Document Generation**: `WEEK 1.zip` contains 6 valid `.docx` files; `DAILY ATTENDANCE` renders `JERIEL MANINGAS` and `Aljay Agro-Industrial Solutions, Inc.` on a single underlined tab-stopped line; `DOCUMENTATIONS.docx` preserves original aspect ratios for all 20 Week 1 photos in a 2-column grid; `NCIS ATTENDANCE MONITORING.docx` outputs `November 16, 2026`, `November 17, 2026`, and `November 18–20, 2026` with zero empty headings for Nov 19–20.

---

## 12. Assumptions & Open Questions
- **Assumptions**:
  - Week 1 per-activity start/end clock times were not recorded on the manual sheet, so daily totals were split evenly across each day's recorded activities with blank `start_time`/`end_time`.
  - `required_hours` stays `486` and work schedule stays Monday–Friday.
  - Existing saved Groq API key and phone PIN in `data/ojt_journal.db` are preserved.
- **Open questions**:
  - What were Friday `Nov 20`'s exact Morning/Afternoon IN–OUT times? (Currently flagged by the pre-flight warning so you can fill them in.)
  - Do `Nikki Dela Cruz` and `Jerry Apostol Jr.` have official job titles to add to the Saved Verifiers directory?
  - Did you already submit Week 1 with `28 hrs` signed, or should you keep the accurate `29 hrs` in your tracker?

---

## 13. What NOT to Build Yet
- Do NOT build multi-user authentication / cloud hosting (this is a single-intern local tool with optional LAN phone access).
- Do NOT build OCR for NCIS screenshots unless manual entry becomes a real bottleneck (error-prone and heavy dependencies).
- Do NOT build automated email submission to school portals (school submission formats and portals vary).
