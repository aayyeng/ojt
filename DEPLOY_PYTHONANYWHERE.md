# Deploying OJT Journal on PythonAnywhere (Free Tier)

PythonAnywhere gives you a **persistent filesystem** even on the free tier, so your SQLite database (`data/ojt_journal.db`) and uploaded work/NCIS photos (`data/uploads/`) stay saved permanently.

---

## Step 1 — Clone your repo in PythonAnywhere Bash Console
1. Sign in at **https://www.pythonanywhere.com** and open **Consoles → Bash**.
2. Run these commands:
   ```bash
   git clone https://github.com/aayyeng/ojt.git ~/ojt
   cd ~/ojt
   python3.11 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
   *(If `python3.11` isn't available, use `python3.10` or `python3` — match the exact Python version you select in Step 2.)*

---

## Step 2 — Create the Web App
1. Go to the **Web** tab → click **Add a new web app**.
2. Choose **Manual configuration** (NOT the Flask wizard) → pick the **same Python version** you used in Step 1 (e.g. `Python 3.11`).
3. Under **Code**:
   - **Source code**: `/home/<your-username>/ojt`
   - **Working directory**: `/home/<your-username>/ojt`
4. Under **Virtualenv**:
   - Enter `/home/<your-username>/ojt/.venv`
5. Click the **WSGI configuration file** link (e.g. `/var/www/<your-username>_pythonanywhere_com_wsgi.py`), replace its entire contents with:
   ```python
   import os
   import sys

   project_home = '/home/<your-username>/ojt'
   if project_home not in sys.path:
       sys.path.insert(0, project_home)

   os.environ['OJT_CLOUD'] = '1'

   from wsgi import application  # noqa
   ```
   *(Replace `<your-username>` with your actual PythonAnywhere username.)*
6. Save the WSGI file, go back to the **Web** tab, and click the green **Reload** button.

---

## Step 3 — First-Time PIN & Moving Your Week 1 Data
1. Open `https://<your-username>.pythonanywhere.com`.
2. On first visit, you will see **First-time setup**: create a **4–8 digit PIN** to protect your OJT Journal online.
3. To transfer your existing Week 1 entries, all 20 work photos, 3 NCIS screenshots, and settings from your laptop:
   - On your laptop app (`http://127.0.0.1:5000/settings`), click **⬇ Backup (data + photos)** to download `ojt_journal_backup_YYYY-MM-DD.zip`.
   - On PythonAnywhere (`https://<your-username>.pythonanywhere.com/settings`), scroll to **📦 Restore from backup** and upload that ZIP file.
   - All your Week 1 entries, photos, NCIS screenshots, and saved verifiers appear immediately!

---

## Step 4 — Updating Later (after new pushes to GitHub)
Whenever new changes are pushed to `https://github.com/aayyeng/ojt.git`, open a PythonAnywhere Bash console and run:
```bash
cd ~/ojt && git pull origin main
```
Then click **Reload** on the **Web** tab. *(Your `data/` folder is ignored by Git, so `git pull` will never overwrite your database or photos.)*

---

## Important Note on Groq AI (Free PythonAnywhere Accounts)
PythonAnywhere free accounts restrict outbound internet access to an allowlist of API domains. If clicking **Test AI connection** shows a proxy-blocked message for `api.groq.com`, you can request PythonAnywhere to allowlist `api.groq.com` for free via **Help → Send feedback** (include link `https://console.groq.com/docs/api-reference`). Everything else (daily logging, auto-saving weekly reports, photo/NCIS uploads, smart verifiers, and 6-document Word ZIP downloads) works immediately on the free tier!
