#!/usr/bin/env python3
"""Ham Radio Website — with login, session management, and admin user panel."""

import os
import cgi
import json
import uuid
import shutil
import hashlib
import secrets
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────
BASE_DIR    = Path(__file__).parent
UPLOAD_DIR  = BASE_DIR / "uploads"
USERS_FILE  = BASE_DIR / "users.json"
UPLOAD_DIR.mkdir(exist_ok=True)

PORT = 8081

# ── In-memory session store  {token: username} ─────────────────────────────
SESSIONS = {}

# ── User helpers ───────────────────────────────────────────────────────────
def hash_pw(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def load_users() -> dict:
    if USERS_FILE.exists():
        with open(USERS_FILE) as f:
            return json.load(f)
    # Default admin account
    users = {"admin": {"password": hash_pw("admin123"), "role": "admin",
                        "first_name": "Admin", "last_name": "", "call_sign": ""}}
    save_users(users)
    return users

def lookup_callsign_acma(call_sign: str) -> dict:
    """
    Look up an Australian amateur radio call sign via the ACMA Amateur Radio
    Callsign Registry API (backend.acma.gov.au/arcs/api/CallsignRegistry).
    Returns the licence class (Foundation / Standard / Advanced) for assigned calls.
    """
    import urllib.request
    import urllib.parse
    import json as _json
    import re

    cs = call_sign.strip().upper()

    # ── Validate VK format ─────────────────────────────────────────────
    VK_STATES = {
        "0": "Antarctic Territory",
        "1": "Australian Capital Territory",
        "2": "New South Wales",
        "3": "Victoria",
        "4": "Queensland",
        "5": "South Australia",
        "6": "Western Australia",
        "7": "Tasmania",
        "8": "Northern Territory",
        "9": "External Territories",
    }
    # API location codes used by backend.acma.gov.au
    VK_API_LOCATION = {
        "0": "Antarctic", "1": "ACT", "2": "NSW", "3": "VIC",
        "4": "QLD", "5": "SA", "6": "WA", "7": "TAS", "8": "NT",
        "9": "External",
    }
    SUFFIX_TYPE = {2: "TwoLetter", 3: "ThreeLetter", 4: "FourLetter"}

    m = re.match(r'^VK([0-9])([A-Z]{1,4})$', cs)
    if not m:
        return {"ok": False, "message": f"'{cs}' does not match Australian VK call sign format (e.g. VK2ABC)."}

    state_code = m.group(1)
    suffix     = m.group(2)
    state      = VK_STATES.get(state_code, "Unknown region")
    location   = VK_API_LOCATION.get(state_code, "")
    cs_type    = SUFFIX_TYPE.get(len(suffix), "")

    acma_page_url = "https://www.acma.gov.au/are-you-looking-amateur-call-sign"

    base = {
        "ok": True,
        "call_sign": cs,
        "state": state,
        "acma_url": acma_page_url,
    }

    if not location or not cs_type:
        return {**base, "found": False,
                "message": f"Cannot determine API location/type for '{cs}'."}

    # ── Query ACMA Amateur Radio Callsign Registry API ─────────────────
    params = urllib.parse.urlencode({
        "availability": "Assigned",
        "prefix":       "VK",
        "location":     location,
        "type":         cs_type,
        "search":       suffix,
    })
    api_url = f"https://backend.acma.gov.au/arcs/api/CallsignRegistry?{params}"
    try:
        req = urllib.request.Request(api_url, headers={
            "Accept": "application/json, text/plain",
            "User-Agent": "Mozilla/5.0",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = _json.loads(resp.read().decode("utf-8"))

        # Find exact match
        match = next((r for r in data if r.get("callsignName") == cs), None)
        if match:
            licence_class = match.get("reservedTo", "Unknown")
            return {**base, "found": True,
                    "licence_class": licence_class,
                    "location": match.get("location", location),
                    "type": match.get("type", cs_type)}

        # Not found as Assigned — call sign may be available or unregistered
        return {**base, "found": False,
                "message": f"'{cs}' is not listed as an assigned call sign in the ACMA registry."}

    except Exception as e:
        return {**base, "found": None,
                "message": f"ACMA registry unreachable ({type(e).__name__}). "
                           "Check manually at the ACMA link above."}

def get_profile(username: str) -> dict:
    users = load_users()
    u = users.get(username, {})
    return {
        "first_name": u.get("first_name", ""),
        "last_name":  u.get("last_name", ""),
        "call_sign":  u.get("call_sign", ""),
    }

def save_users(users: dict):
    with open(USERS_FILE, "w") as f:
        json.dump(users, f, indent=2)

def check_login(username: str, password: str) -> bool:
    users = load_users()
    u = users.get(username)
    return u is not None and u["password"] == hash_pw(password)

def get_role(username: str) -> str:
    users = load_users()
    return users.get(username, {}).get("role", "user")

# ── Session helpers ────────────────────────────────────────────────────────
def create_session(username: str) -> str:
    token = secrets.token_hex(32)
    SESSIONS[token] = username
    return token

def get_session_user(cookie_header: str) -> str | None:
    if not cookie_header:
        return None
    for part in cookie_header.split(";"):
        k, _, v = part.strip().partition("=")
        if k == "session":
            return SESSIONS.get(v.strip())
    return None

def parse_cookie_token(cookie_header: str) -> str | None:
    if not cookie_header:
        return None
    for part in cookie_header.split(";"):
        k, _, v = part.strip().partition("=")
        if k == "session":
            return v.strip()
    return None

# ══════════════════════════════════════════════════════════════════════════
# HTML PAGES
# ══════════════════════════════════════════════════════════════════════════

BASE_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
  background: #0a0f1a;
  color: #c8d8e8;
  min-height: 100vh;
}
header {
  background: linear-gradient(135deg, #0d1b2a 0%, #1a3a5c 50%, #0d2238 100%);
  border-bottom: 3px solid #2a7fbf;
  padding: 18px 32px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  box-shadow: 0 4px 20px rgba(42,127,191,0.4);
}
.logo-area { display: flex; align-items: center; gap: 16px; }
.antenna-icon { font-size: 42px; filter: drop-shadow(0 0 8px #2a7fbf); }
header h1 {
  font-size: 2.4rem; font-weight: 800; color: #5bc8f5;
  text-shadow: 0 0 18px rgba(91,200,245,0.7);
  letter-spacing: 3px; text-transform: uppercase;
}
header h1 span { color: #ff9f1c; }
.header-right { display: flex; align-items: center; gap: 16px; }
.clock-box {
  text-align: right; background: rgba(0,0,0,0.4);
  border: 1px solid #2a7fbf; border-radius: 10px; padding: 10px 20px;
}
#clock {
  font-size: 2rem; font-weight: 700; color: #39ff14;
  font-family: 'Courier New', monospace; letter-spacing: 3px;
  text-shadow: 0 0 10px #39ff14;
}
#clock-label { font-size: 0.7rem; color: #7ab3d0; letter-spacing: 2px; margin-top: 2px; }
.nav-links { display: flex; gap: 10px; }
.nav-btn {
  padding: 8px 16px; border-radius: 7px; border: 1px solid #2a7fbf;
  background: rgba(42,127,191,0.15); color: #5bc8f5;
  text-decoration: none; font-size: 0.85rem; letter-spacing: 1px;
  cursor: pointer; transition: background 0.2s;
}
.nav-btn:hover { background: #2a7fbf; color: #fff; }
.nav-btn.danger { border-color: #c0392b; color: #e74c3c; background: rgba(192,57,43,0.1); }
.nav-btn.danger:hover { background: #c0392b; color: #fff; }
.card {
  background: linear-gradient(160deg, #0d1b2a, #112233);
  border: 1px solid #1e4a6e; border-radius: 14px;
  padding: 24px; box-shadow: 0 4px 24px rgba(0,0,0,0.5);
}
.card h2 {
  font-size: 1.1rem; color: #5bc8f5; letter-spacing: 2px;
  text-transform: uppercase; margin-bottom: 20px;
  padding-bottom: 10px; border-bottom: 1px solid #1e4a6e;
}
"""

# ── LOGIN PAGE ─────────────────────────────────────────────────────────────
def login_page(error=""):
    err_html = f'<p class="form-error">{error}</p>' if error else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ham Radio — Login</title>
<style>
{BASE_CSS}
body {{ display:flex; flex-direction:column; min-height:100vh; }}
.login-wrap {{
  flex:1; display:flex; align-items:center; justify-content:center; padding:40px 16px;
}}
.login-box {{
  width:100%; max-width:400px; background:linear-gradient(160deg,#0d1b2a,#112233);
  border:1px solid #1e4a6e; border-radius:16px; padding:40px 36px;
  box-shadow:0 8px 40px rgba(0,0,0,0.6);
}}
.login-box h2 {{
  color:#5bc8f5; font-size:1.4rem; letter-spacing:3px;
  text-transform:uppercase; text-align:center; margin-bottom:28px;
}}
.form-group {{ margin-bottom:18px; }}
.form-group label {{ display:block; font-size:0.8rem; color:#7ab3d0; letter-spacing:2px; margin-bottom:6px; }}
.form-group input {{
  width:100%; padding:11px 14px; background:#071018; border:1px solid #1e4a6e;
  border-radius:8px; color:#c8d8e8; font-size:0.95rem; outline:none;
  transition:border-color 0.2s;
}}
.form-group input:focus {{ border-color:#2a7fbf; }}
.form-error {{ color:#e74c3c; font-size:0.85rem; text-align:center; margin-bottom:14px; }}
.btn-submit {{
  width:100%; padding:13px; background:linear-gradient(135deg,#2a7fbf,#1a5c8f);
  border:none; border-radius:8px; color:#fff; font-size:1rem; font-weight:600;
  cursor:pointer; letter-spacing:1px; margin-top:6px; transition:opacity 0.2s;
}}
.btn-submit:hover {{ opacity:0.88; }}
.login-footer {{ text-align:center; margin-top:18px; font-size:0.78rem; color:#4a6a80; }}
</style>
</head>
<body>
<header>
  <div class="logo-area">
    <div class="antenna-icon">📡</div>
    <h1>Ham <span>Radio</span></h1>
  </div>
</header>
<div class="login-wrap">
  <div class="login-box">
    <h2>🔐 Sign In</h2>
    {err_html}
    <form method="POST" action="/login">
      <div class="form-group">
        <label>USERNAME</label>
        <input type="text" name="username" autofocus autocomplete="username" required>
      </div>
      <div class="form-group">
        <label>PASSWORD</label>
        <input type="password" name="password" autocomplete="current-password" required>
      </div>
      <button class="btn-submit" type="submit">Login</button>
    </form>
    <p class="login-footer">Ham Radio Network &mdash; Authorized users only</p>
  </div>
</div>
</body>
</html>"""

# ── ADMIN PAGE ─────────────────────────────────────────────────────────────
def admin_page(current_user, message="", msg_type="ok"):
    users = load_users()
    rows = ""
    for uname, udata in users.items():
        role_badge = "🛡️ admin" if udata["role"] == "admin" else "👤 user"
        full_name  = f"{udata.get('first_name','')} {udata.get('last_name','')}".strip() or "—"
        call_sign  = udata.get("call_sign", "") or "—"
        del_btn = ""
        if uname != current_user:
            del_btn = f"""
            <form method="POST" action="/admin/delete" style="display:inline">
              <input type="hidden" name="username" value="{uname}">
              <button class="tbl-btn danger" type="submit"
                onclick="return confirm('Delete user {uname}?')">Delete</button>
            </form>"""
        toggle_role = "user" if udata["role"] == "admin" else "admin"
        toggle_label = "→ user" if udata["role"] == "admin" else "→ admin"
        rows += f"""
        <tr>
          <td>{uname}{"&nbsp;<span style='color:#ff9f1c;font-size:.7rem'>YOU</span>" if uname==current_user else ""}</td>
          <td>{full_name}</td>
          <td style="font-family:monospace;color:#ff9f1c">{call_sign}</td>
          <td>{role_badge}</td>
          <td>
            <form method="POST" action="/admin/role" style="display:inline">
              <input type="hidden" name="username" value="{uname}">
              <input type="hidden" name="role" value="{toggle_role}">
              <button class="tbl-btn" type="submit">{toggle_label}</button>
            </form>
            {del_btn}
          </td>
        </tr>"""

    msg_html = ""
    if message:
        color = "#39ff14" if msg_type == "ok" else "#e74c3c"
        msg_html = f'<p style="color:{color};margin-bottom:18px;font-size:.9rem">{message}</p>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ham Radio — Admin</title>
<style>
{BASE_CSS}
main {{ max-width:900px; margin:0 auto; padding:32px; display:flex; flex-direction:column; gap:28px; }}
.form-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:14px; }}
@media(max-width:580px) {{ .form-grid {{ grid-template-columns:1fr; }} }}
.form-group {{ display:flex; flex-direction:column; gap:6px; }}
.form-group label {{ font-size:.78rem; color:#7ab3d0; letter-spacing:2px; }}
.form-group input, .form-group select {{
  padding:10px 13px; background:#071018; border:1px solid #1e4a6e;
  border-radius:7px; color:#c8d8e8; font-size:.92rem; outline:none;
}}
.form-group input:focus, .form-group select:focus {{ border-color:#2a7fbf; }}
.btn-primary {{
  padding:11px 28px; background:linear-gradient(135deg,#2a7fbf,#1a5c8f);
  border:none; border-radius:7px; color:#fff; font-size:.9rem; font-weight:600;
  cursor:pointer; letter-spacing:1px; margin-top:8px; transition:opacity .2s;
}}
.btn-primary:hover {{ opacity:.85; }}
table {{ width:100%; border-collapse:collapse; }}
thead th {{
  text-align:left; padding:10px 14px; font-size:.75rem; color:#7ab3d0;
  letter-spacing:2px; border-bottom:2px solid #1e4a6e;
}}
tbody td {{ padding:12px 14px; border-bottom:1px solid #112233; font-size:.88rem; }}
tbody tr:hover td {{ background:rgba(42,127,191,.07); }}
.tbl-btn {{
  padding:5px 13px; border-radius:5px; border:1px solid #2a7fbf;
  background:rgba(42,127,191,.12); color:#5bc8f5; cursor:pointer;
  font-size:.78rem; margin-right:6px; transition:background .2s;
}}
.tbl-btn:hover {{ background:#2a7fbf; color:#fff; }}
.tbl-btn.danger {{ border-color:#c0392b; color:#e74c3c; background:rgba(192,57,43,.1); }}
.tbl-btn.danger:hover {{ background:#c0392b; color:#fff; }}
</style>
</head>
<body>
<header>
  <div class="logo-area">
    <div class="antenna-icon">📡</div>
    <h1>Ham <span>Radio</span></h1>
  </div>
  <div class="header-right">
    <div class="nav-links">
      <a class="nav-btn" href="/">🏠 Main</a>
      <a class="nav-btn danger" href="/logout">⏻ Logout</a>
    </div>
  </div>
</header>

<main>
  <div class="card">
    <h2>⚙️ Admin Panel — Logged in as {current_user}</h2>
    {msg_html}

    <h3 style="color:#ff9f1c;font-size:.9rem;letter-spacing:2px;margin-bottom:14px">ADD NEW USER</h3>
    <form method="POST" action="/admin/add">
      <div class="form-grid">
        <div class="form-group">
          <label>USERNAME</label>
          <input type="text" name="username" required autocomplete="off">
        </div>
        <div class="form-group">
          <label>CALL SIGN (e.g. VK2ABC)</label>
          <input type="text" name="call_sign" autocomplete="off" placeholder="VK2ABC" style="text-transform:uppercase">
        </div>
        <div class="form-group">
          <label>FIRST NAME</label>
          <input type="text" name="first_name" autocomplete="off">
        </div>
        <div class="form-group">
          <label>LAST NAME</label>
          <input type="text" name="last_name" autocomplete="off">
        </div>
        <div class="form-group">
          <label>PASSWORD</label>
          <input type="password" name="password" required autocomplete="new-password">
        </div>
        <div class="form-group">
          <label>CONFIRM PASSWORD</label>
          <input type="password" name="password2" required autocomplete="new-password">
        </div>
        <div class="form-group">
          <label>ROLE</label>
          <select name="role">
            <option value="user">👤 User</option>
            <option value="admin">🛡️ Admin</option>
          </select>
        </div>
      </div>
      <button class="btn-primary" type="submit">➕ Add User</button>
    </form>
  </div>

  <div class="card">
    <h2>👥 User Accounts ({len(users)})</h2>
    <table>
      <thead><tr><th>USERNAME</th><th>FULL NAME</th><th>CALL SIGN</th><th>ROLE</th><th>ACTIONS</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </div>

  <div class="card">
    <h2>🔑 Change Password</h2>
    <form method="POST" action="/admin/chpw">
      <div class="form-grid">
        <div class="form-group">
          <label>USERNAME</label>
          <select name="username">
            {"".join(f'<option value="{u}">{u}</option>' for u in users)}
          </select>
        </div>
        <div class="form-group">
          <label>NEW PASSWORD</label>
          <input type="password" name="password" required autocomplete="new-password">
        </div>
      </div>
      <button class="btn-primary" type="submit">🔄 Update Password</button>
    </form>
  </div>
</main>
</body>
</html>"""

# ── MAIN PAGE ──────────────────────────────────────────────────────────────
def main_page(current_user):
    is_admin = get_role(current_user) == "admin"
    admin_link = '<a class="nav-btn" href="/admin">⚙️ Admin</a>' if is_admin else ""
    profile = get_profile(current_user)
    display_name = f"{profile['first_name']} {profile['last_name']}".strip() or current_user
    call_sign    = profile["call_sign"] or ""
    cs_html = f'&nbsp;<span style="color:#ff9f1c;font-family:monospace;font-weight:700">{call_sign}</span>' if call_sign else ""
    prof_first = profile["first_name"]
    prof_last  = profile["last_name"]
    prof_cs    = profile["call_sign"]
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Ham Radio</title>
<style>
{BASE_CSS}
main {{
  display:grid; grid-template-columns:1fr 1fr;
  gap:28px; padding:32px; max-width:1200px; margin:0 auto;
}}
@media(max-width:768px) {{ main {{ grid-template-columns:1fr; }} }}
/* Calendar */
.cal-nav {{ display:flex; align-items:center; justify-content:space-between; margin-bottom:14px; }}
.cal-nav button {{
  background:#1a3a5c; border:1px solid #2a7fbf; color:#5bc8f5;
  border-radius:6px; padding:4px 12px; cursor:pointer; font-size:1rem; transition:background .2s;
}}
.cal-nav button:hover {{ background:#2a7fbf; color:#fff; }}
#cal-month-label {{ font-weight:700; color:#ff9f1c; font-size:1.05rem; letter-spacing:1px; }}
#calendar-grid {{ width:100%; border-collapse:collapse; }}
#calendar-grid th {{ color:#7ab3d0; font-size:.75rem; letter-spacing:1px; padding:6px 0; text-align:center; }}
#calendar-grid td {{
  text-align:center; padding:7px 4px; border-radius:6px;
  cursor:pointer; font-size:.9rem; transition:background .15s;
}}
#calendar-grid td:hover:not(.empty) {{ background:#1a3a5c; }}
#calendar-grid td.today {{
  background:#2a7fbf; color:#fff; font-weight:700;
  border-radius:50%; box-shadow:0 0 10px rgba(42,127,191,.6);
}}
#calendar-grid td.selected {{ background:#ff9f1c; color:#0a0f1a; font-weight:700; border-radius:50%; }}
#calendar-grid td.empty {{ cursor:default; }}
#selected-date {{ margin-top:14px; font-size:.85rem; color:#ff9f1c; text-align:center; min-height:1.2em; }}
/* Upload */
.drop-zone {{
  border:2px dashed #2a7fbf; border-radius:10px; padding:30px 20px;
  text-align:center; cursor:pointer; transition:border-color .2s,background .2s;
  margin-bottom:16px; position:relative;
}}
.drop-zone:hover, .drop-zone.dragover {{ border-color:#5bc8f5; background:rgba(42,127,191,.08); }}
.drop-zone input[type="file"] {{ position:absolute; inset:0; opacity:0; cursor:pointer; width:100%; height:100%; }}
.drop-zone .dz-icon {{ font-size:2.2rem; margin-bottom:8px; }}
.drop-zone p {{ color:#7ab3d0; font-size:.9rem; }}
.drop-zone p strong {{ color:#5bc8f5; }}
#upload-btn {{
  width:100%; padding:12px;
  background:linear-gradient(135deg,#2a7fbf,#1a5c8f);
  border:none; border-radius:8px; color:#fff; font-size:1rem;
  font-weight:600; cursor:pointer; letter-spacing:1px; transition:opacity .2s,box-shadow .2s;
}}
#upload-btn:hover {{ opacity:.88; box-shadow:0 0 14px rgba(42,127,191,.6); }}
#upload-btn:disabled {{ opacity:.4; cursor:not-allowed; }}
#upload-status {{ margin-top:12px; font-size:.85rem; min-height:1.2em; text-align:center; }}
.status-ok  {{ color:#39ff14; }}
.status-err {{ color:#ff4444; }}
#file-list {{ list-style:none; }}
#file-list li {{
  display:flex; align-items:center; gap:10px; padding:8px 10px;
  border-radius:6px; font-size:.85rem; border-bottom:1px solid #1a3a5c; transition:background .15s;
}}
#file-list li:last-child {{ border-bottom:none; }}
#file-list li:hover {{ background:#112233; }}
.file-icon {{ font-size:1.1rem; }}
.file-name {{ flex:1; color:#c8d8e8; word-break:break-all; }}
.file-link {{
  color:#5bc8f5; text-decoration:none; font-size:.75rem;
  border:1px solid #1e4a6e; border-radius:4px; padding:2px 8px; white-space:nowrap;
}}
.file-link:hover {{ background:#1a3a5c; }}
.no-files {{ color:#4a6a80; font-size:.85rem; text-align:center; padding:16px 0; }}
#progress-wrap {{
  height:6px; background:#1a3a5c; border-radius:3px;
  margin-top:10px; overflow:hidden; display:none;
}}
#progress-bar {{
  height:100%; width:0%;
  background:linear-gradient(90deg,#2a7fbf,#39ff14);
  transition:width .2s; border-radius:3px;
}}
.user-badge {{
  background:rgba(0,0,0,.35); border:1px solid #1e4a6e;
  border-radius:8px; padding:6px 14px; font-size:.8rem; color:#7ab3d0;
}}
.user-badge strong {{ color:#5bc8f5; }}
/* Profile form */
.profile-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:14px; }}
@media(max-width:600px) {{ .profile-grid {{ grid-template-columns:1fr; }} }}
.pf-group {{ display:flex; flex-direction:column; gap:6px; }}
.pf-group label {{ font-size:.78rem; color:#7ab3d0; letter-spacing:2px; }}
.pf-group input {{
  padding:10px 13px; background:#071018; border:1px solid #1e4a6e;
  border-radius:7px; color:#c8d8e8; font-size:.92rem; outline:none;
}}
.pf-group input:focus {{ border-color:#2a7fbf; }}
.pf-btn {{
  padding:10px 26px; background:linear-gradient(135deg,#2a7fbf,#1a5c8f);
  border:none; border-radius:7px; color:#fff; font-size:.88rem; font-weight:600;
  cursor:pointer; letter-spacing:1px; margin-top:10px; transition:opacity .2s;
}}
.pf-btn:hover {{ opacity:.85; }}
/* ACMA result */
.cs-result {{
  display:flex; flex-wrap:wrap; gap:10px; align-items:center;
  background:rgba(42,127,191,.1); border:1px solid #2a7fbf;
  border-radius:8px; padding:10px 14px;
}}
.cs-badge {{
  font-family:monospace; font-size:1.1rem; font-weight:700;
  color:#ff9f1c; letter-spacing:2px;
}}
.cs-field {{ font-size:.82rem; color:#c8d8e8; }}
.cs-field b {{ color:#7ab3d0; }}
/* Footer */
footer {{
  margin-top:10px; padding:28px 32px;
  border-top:1px solid #1a3a5c;
  background:linear-gradient(0deg,#050d18,#0a0f1a);
}}
.footer-inner {{
  max-width:1200px; margin:0 auto;
  display:flex; flex-wrap:wrap; align-items:center; justify-content:space-between; gap:20px;
}}
.footer-label {{ font-size:.75rem; color:#4a6a80; letter-spacing:2px; margin-bottom:12px; }}
.footer-links {{ display:flex; flex-wrap:wrap; gap:12px; }}
.footer-link {{
  display:flex; align-items:center; gap:8px;
  padding:10px 18px; border-radius:8px;
  border:1px solid #1e4a6e; background:rgba(42,127,191,.08);
  color:#5bc8f5; text-decoration:none; font-size:.85rem;
  transition:border-color .2s, background .2s;
}}
.footer-link:hover {{ border-color:#2a7fbf; background:rgba(42,127,191,.18); color:#fff; }}
.footer-link .fl-icon {{ font-size:1.2rem; }}
.footer-link .fl-text {{ display:flex; flex-direction:column; }}
.footer-link .fl-title {{ font-weight:600; font-size:.85rem; }}
.footer-link .fl-sub {{ font-size:.72rem; color:#7ab3d0; margin-top:1px; }}
.footer-copy {{ font-size:.72rem; color:#2a4a5e; text-align:right; }}
</style>
</head>
<body>
<header>
  <div class="logo-area">
    <div class="antenna-icon">📡</div>
    <h1>Ham <span>Radio</span></h1>
  </div>
  <div class="header-right">
    <div class="clock-box">
      <div id="clock">00:00:00</div>
      <div id="clock-label">LOCAL TIME</div>
    </div>
    <div class="nav-links">
      {admin_link}
      <span class="user-badge">👤 <strong>{display_name}</strong>{cs_html}</span>
      <a class="nav-btn danger" href="/logout">⏻ Logout</a>
    </div>
  </div>
</header>

<main>
  <!-- CALENDAR -->
  <div class="card">
    <h2>📅 Calendar</h2>
    <div class="cal-nav">
      <button id="prev-month">&#8249;</button>
      <span id="cal-month-label"></span>
      <button id="next-month">&#8250;</button>
    </div>
    <table id="calendar-grid">
      <thead>
        <tr><th>Su</th><th>Mo</th><th>Tu</th><th>We</th><th>Th</th><th>Fr</th><th>Sa</th></tr>
      </thead>
      <tbody id="cal-body"></tbody>
    </table>
    <div id="selected-date"></div>
  </div>

  <!-- FILE UPLOAD -->
  <div class="card">
    <h2>📂 File Upload</h2>
    <div class="drop-zone" id="drop-zone">
      <input type="file" id="file-input" multiple>
      <div class="dz-icon">⬆️</div>
      <p><strong>Click to browse</strong> or drag &amp; drop files here</p>
    </div>
    <button id="upload-btn" disabled>Upload Files</button>
    <div id="progress-wrap"><div id="progress-bar"></div></div>
    <div id="upload-status"></div>

    <h2 style="margin-top:24px;">🗂️ Uploaded Files</h2>
    <ul id="file-list"><li class="no-files">No files uploaded yet.</li></ul>
  </div>
</main>

<!-- PROFILE SECTION -->
<div style="max-width:1200px;margin:0 auto;padding:0 32px 32px">
  <div class="card" id="profile-section">
    <h2>👤 My Profile</h2>
    <div id="profile-msg" style="font-size:.88rem;min-height:1.2em;margin-bottom:10px"></div>
    <form id="profile-form">
      <div class="profile-grid">
        <div class="pf-group">
          <label>FIRST NAME</label>
          <input type="text" name="first_name" value="{prof_first}" autocomplete="given-name">
        </div>
        <div class="pf-group">
          <label>LAST NAME</label>
          <input type="text" name="last_name" value="{prof_last}" autocomplete="family-name">
        </div>
        <div class="pf-group">
          <label>CALL SIGN (Australian, e.g. VK2ABC)</label>
          <div style="display:flex;gap:8px;align-items:center">
            <input type="text" name="call_sign" value="{prof_cs}"
                   placeholder="VK2ABC" autocomplete="off"
                   style="text-transform:uppercase;font-family:monospace;font-size:1rem;letter-spacing:2px;flex:1">
            <button type="button" id="cs-lookup-btn" class="pf-btn" style="margin-top:0;white-space:nowrap">🔍 Lookup ACMA</button>
          </div>
          <div id="cs-lookup-result" style="margin-top:8px;font-size:.85rem;min-height:1.2em"></div>
        </div>
      </div>
      <button class="pf-btn" type="submit">💾 Save Profile</button>
    </form>
  </div>
</div>

<!-- FOOTER -->
<footer>
  <div class="footer-inner">
    <div>
      <p class="footer-label">🔗 HAM RADIO RESOURCES</p>
      <div class="footer-links">
        <a class="footer-link" href="https://www.wia.org.au" target="_blank" rel="noopener">
          <span class="fl-icon">📻</span>
          <span class="fl-text">
            <span class="fl-title">Wireless Institute of Australia</span>
            <span class="fl-sub">wia.org.au — Peak body for amateur radio in Australia</span>
          </span>
        </a>
        <a class="footer-link" href="https://www.acma.gov.au/amateur-radio-licence" target="_blank" rel="noopener">
          <span class="fl-icon">🏛️</span>
          <span class="fl-text">
            <span class="fl-title">ACMA Amateur Radio Regulations</span>
            <span class="fl-sub">acma.gov.au — Australian government licensing &amp; regulations</span>
          </span>
        </a>
        <a class="footer-link" href="https://www.arrl.org/arrl-handbook" target="_blank" rel="noopener">
          <span class="fl-icon">📖</span>
          <span class="fl-text">
            <span class="fl-title">ARRL Handbook</span>
            <span class="fl-sub">arrl.org — The definitive ham radio technical reference</span>
          </span>
        </a>
      </div>
    </div>
    <div class="footer-copy">Ham Radio Network<br>73 de {current_user}</div>
  </div>
</footer>

<script>
// Profile form (AJAX)
document.getElementById('profile-form').addEventListener('submit', function(e) {{
  e.preventDefault();
  const fd = new FormData(this);
  const body = new URLSearchParams(fd).toString();
  fetch('/profile', {{method:'POST', headers:{{'Content-Type':'application/x-www-form-urlencoded'}}, body}})
    .then(r=>r.json()).then(d=>{{
      const el = document.getElementById('profile-msg');
      if(d.ok) {{
        el.style.color='#39ff14'; el.textContent='✓ '+d.message;
        // Update call sign in header badge
        const csEl = document.querySelector('.user-badge span[style*="ff9f1c"]');
        const cs = fd.get('call_sign').trim().toUpperCase();
        if(csEl) {{ csEl.textContent = cs || ''; }}
        else if(cs) {{
          const badge = document.querySelector('.user-badge');
          const sp = document.createElement('span');
          sp.style='color:#ff9f1c;font-family:monospace;font-weight:700';
          sp.textContent='\u00a0'+cs; badge.appendChild(sp);
        }}
        // Update display name
        const fn=fd.get('first_name').trim(), ln=fd.get('last_name').trim();
        const dn = (fn+' '+ln).trim() || '{current_user}';
        document.querySelector('.user-badge strong').textContent=dn;
      }} else {{ el.style.color='#e74c3c'; el.textContent='✗ '+d.message; }}
    }}).catch(()=>{{ document.getElementById('profile-msg').textContent='✗ Error saving profile'; }});
}});
// Force call sign uppercase while typing
document.querySelector('input[name="call_sign"]').addEventListener('input',function(){{this.value=this.value.toUpperCase();}});

// ── ACMA call sign lookup ──────────────────────────────────────────────
const lookupBtn = document.getElementById('cs-lookup-btn');
const lookupResult = document.getElementById('cs-lookup-result');

lookupBtn && lookupBtn.addEventListener('click', function() {{
  const cs = document.querySelector('input[name="call_sign"]').value.trim().toUpperCase();
  if (!cs) {{ lookupResult.innerHTML='<span style="color:#e74c3c">Enter a call sign first.</span>'; return; }}
  lookupBtn.disabled = true;
  lookupBtn.textContent = '⏳ Checking…';
  lookupResult.innerHTML = '';
  fetch('/callsign_lookup?cs=' + encodeURIComponent(cs))
    .then(r => r.json())
    .then(d => {{
      if (!d.ok) {{
        lookupResult.innerHTML = '<span style="color:#e74c3c">⚠ ' + escHtml(d.message || 'Invalid call sign format') + '</span>';
        return;
      }}
      const acmaLink = d.acma_url
        ? `<a href="${{escHtml(d.acma_url)}}" target="_blank" rel="noopener" class="file-link" style="font-size:.8rem">🔗 ACMA Amateur Radio Call Sign Registry</a>`
        : '';
      if (d.found === true) {{
        const licClass = d.licence_class || '';
        const licColour = licClass === 'Advanced' ? '#39ff14' : licClass === 'Standard' ? '#f39c12' : licClass === 'Foundation' ? '#3498db' : '#ccc';
        lookupResult.innerHTML =
          '<div class="cs-result">' +
          '<span class="cs-badge">' + escHtml(d.call_sign) + '</span>' +
          '<span class="cs-field"><b>Status:</b> <span style="color:#39ff14">✓ Assigned — ACMA registry</span></span>' +
          (licClass ? '<span class="cs-field"><b>Licence class:</b> <span style="color:' + licColour + ';font-weight:bold">' + escHtml(licClass) + '</span></span>' : '') +
          '<span class="cs-field"><b>State/Region:</b> ' + escHtml(d.state||'') + '</span>' +
          acmaLink +
          '</div>';
      }} else if (d.found === false) {{
        lookupResult.innerHTML =
          '<div class="cs-result" style="border-color:#c0392b;background:rgba(192,57,43,.1)">' +
          '<span class="cs-badge" style="color:#e74c3c">' + escHtml(d.call_sign) + '</span>' +
          '<span class="cs-field" style="color:#e74c3c">✗ Not found in ACMA register</span>' +
          '<span class="cs-field"><b>State region:</b> ' + escHtml(d.state||'') + '</span>' +
          acmaLink +
          '</div>';
      }} else {{
        // found === null → ACMA unreachable, show format info
        lookupResult.innerHTML =
          '<div class="cs-result" style="border-color:#ff9f1c;background:rgba(255,159,28,.08)">' +
          '<span class="cs-badge">' + escHtml(d.call_sign) + '</span>' +
          '<span class="cs-field" style="color:#ff9f1c">⚠ ACMA database temporarily unavailable</span>' +
          '<span class="cs-field"><b>State region:</b> ' + escHtml(d.state||'') + '</span>' +
          '<span class="cs-field" style="color:#7ab3d0;font-style:italic">' + escHtml(d.message||'') + '</span>' +
          acmaLink +
          '</div>';
      }}
    }})
    .catch(() => {{ lookupResult.innerHTML = '<span style="color:#e74c3c">⚠ Network error during lookup.</span>'; }})
    .finally(() => {{ lookupBtn.disabled=false; lookupBtn.textContent='🔍 Lookup ACMA'; }});
}});

// Clock
function updateClock() {{
  const n=new Date(),h=String(n.getHours()).padStart(2,'0'),
        m=String(n.getMinutes()).padStart(2,'0'),s=String(n.getSeconds()).padStart(2,'0');
  document.getElementById('clock').textContent=h+':'+m+':'+s;
}}
updateClock(); setInterval(updateClock,1000);

// Calendar
const today=new Date(); let viewYear=today.getFullYear(),viewMonth=today.getMonth(),selectedDate=null;
const MONTHS=['January','February','March','April','May','June','July','August','September','October','November','December'];
function renderCalendar(){{
  document.getElementById('cal-month-label').textContent=MONTHS[viewMonth]+' '+viewYear;
  const body=document.getElementById('cal-body'); body.innerHTML='';
  const firstDay=new Date(viewYear,viewMonth,1).getDay(), daysIn=new Date(viewYear,viewMonth+1,0).getDate();
  let row=document.createElement('tr');
  for(let i=0;i<firstDay;i++){{const td=document.createElement('td');td.className='empty';row.appendChild(td);}}
  for(let d=1;d<=daysIn;d++){{
    if(row.children.length===7){{body.appendChild(row);row=document.createElement('tr');}}
    const td=document.createElement('td'); td.textContent=d;
    const isToday=(d===today.getDate()&&viewMonth===today.getMonth()&&viewYear===today.getFullYear());
    const dt=viewYear+'-'+String(viewMonth+1).padStart(2,'0')+'-'+String(d).padStart(2,'0');
    if(isToday)td.classList.add('today');
    if(selectedDate===dt)td.classList.add('selected');
    td.addEventListener('click',()=>{{selectedDate=dt;document.getElementById('selected-date').textContent='Selected: '+MONTHS[viewMonth]+' '+d+', '+viewYear;renderCalendar();}});
    row.appendChild(td);
  }}
  while(row.children.length<7){{const td=document.createElement('td');td.className='empty';row.appendChild(td);}}
  body.appendChild(row);
}}
document.getElementById('prev-month').addEventListener('click',()=>{{viewMonth--;if(viewMonth<0){{viewMonth=11;viewYear--;}}renderCalendar();}});
document.getElementById('next-month').addEventListener('click',()=>{{viewMonth++;if(viewMonth>11){{viewMonth=0;viewYear++;}}renderCalendar();}});
renderCalendar();

// Upload
const fileInput=document.getElementById('file-input'),uploadBtn=document.getElementById('upload-btn'),
      dropZone=document.getElementById('drop-zone'),statusEl=document.getElementById('upload-status'),
      progressWrap=document.getElementById('progress-wrap'),progressBar=document.getElementById('progress-bar');
fileInput.addEventListener('change',()=>{{uploadBtn.disabled=fileInput.files.length===0;}});
dropZone.addEventListener('dragover',e=>{{e.preventDefault();dropZone.classList.add('dragover');}});
dropZone.addEventListener('dragleave',()=>dropZone.classList.remove('dragover'));
dropZone.addEventListener('drop',e=>{{e.preventDefault();dropZone.classList.remove('dragover');fileInput.files=e.dataTransfer.files;uploadBtn.disabled=fileInput.files.length===0;}});
uploadBtn.addEventListener('click',()=>{{
  const files=fileInput.files; if(!files.length)return;
  const fd=new FormData(); for(const f of files)fd.append('files',f);
  uploadBtn.disabled=true; progressWrap.style.display='block'; progressBar.style.width='0%';
  statusEl.textContent=''; statusEl.className='';
  const xhr=new XMLHttpRequest(); xhr.open('POST','/upload');
  xhr.upload.addEventListener('progress',e=>{{if(e.lengthComputable)progressBar.style.width=(e.loaded/e.total*100)+'%';}});
  xhr.addEventListener('load',()=>{{
    progressBar.style.width='100%';
    try{{const r=JSON.parse(xhr.responseText);
      if(r.ok){{statusEl.textContent='✓ '+r.message;statusEl.className='status-ok';fileInput.value='';loadFiles();}}
      else{{statusEl.textContent='✗ '+r.message;statusEl.className='status-err';}}
    }}catch{{statusEl.textContent='✗ Server error';statusEl.className='status-err';}}
    uploadBtn.disabled=false;
    setTimeout(()=>{{progressWrap.style.display='none';progressBar.style.width='0%';}},1200);
  }});
  xhr.addEventListener('error',()=>{{statusEl.textContent='✗ Upload failed';statusEl.className='status-err';uploadBtn.disabled=false;progressWrap.style.display='none';}});
  xhr.send(fd);
}});

function fileIcon(name){{
  const ext=name.split('.').pop().toLowerCase();
  const map={{pdf:'📄',png:'🖼️',jpg:'🖼️',jpeg:'🖼️',gif:'🖼️',svg:'🖼️',webp:'🖼️',mp3:'🎵',wav:'🎵',ogg:'🎵',flac:'🎵',mp4:'🎬',avi:'🎬',mkv:'🎬',mov:'🎬',zip:'🗜️',tar:'🗜️',gz:'🗜️',rar:'🗜️',txt:'📝',log:'📝',md:'📝',py:'🐍',js:'📜',ts:'📜',html:'🌐',css:'🎨'}};
  return map[ext]||'📁';
}}
function escHtml(s){{return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}}
function loadFiles(){{
  fetch('/files').then(r=>r.json()).then(data=>{{
    const list=document.getElementById('file-list');
    if(!data.files||!data.files.length){{list.innerHTML='<li class="no-files">No files uploaded yet.</li>';return;}}
    list.innerHTML=data.files.map(f=>`<li><span class="file-icon">${{fileIcon(f)}}</span><span class="file-name">${{escHtml(f)}}</span><a class="file-link" href="/download/${{encodeURIComponent(f)}}" download>⬇ Download</a></li>`).join('');
  }}).catch(()=>{{}});
}}
loadFiles();
</script>
</body>
</html>"""


# ══════════════════════════════════════════════════════════════════════════
# HTTP HANDLER
# ══════════════════════════════════════════════════════════════════════════

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[{self.address_string()}] {fmt % args}")

    # ── helpers ──────────────────────────────────────────────────────────
    def send_html(self, code, html):
        body = html.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def redirect(self, location):
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def redirect_with_cookie(self, location, token):
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Set-Cookie", f"session={token}; HttpOnly; Path=/; SameSite=Strict")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def current_user(self):
        return get_session_user(self.headers.get("Cookie", ""))

    def require_login(self):
        """Returns username if logged in, otherwise redirects and returns None."""
        user = self.current_user()
        if not user:
            self.redirect("/login")
        return user

    def require_admin(self):
        user = self.require_login()
        if user and get_role(user) != "admin":
            self.send_html(403, "<h1 style='color:#e74c3c;font-family:monospace;padding:40px'>403 — Admins only</h1>")
            return None
        return user

    def read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(length)

    def parse_form(self):
        """Parse application/x-www-form-urlencoded body."""
        body = self.read_body().decode()
        data = {}
        for pair in body.split("&"):
            if "=" in pair:
                k, _, v = pair.partition("=")
                from urllib.parse import unquote_plus
                data[unquote_plus(k)] = unquote_plus(v)
        return data

    # ── GET ───────────────────────────────────────────────────────────────
    def do_GET(self):
        path = urlparse(self.path).path

        if path in ("/", "/index.html"):
            user = self.require_login()
            if user:
                self.send_html(200, main_page(user))

        elif path == "/login":
            if self.current_user():
                self.redirect("/")
            else:
                self.send_html(200, login_page())

        elif path == "/logout":
            token = parse_cookie_token(self.headers.get("Cookie", ""))
            if token and token in SESSIONS:
                del SESSIONS[token]
            self.send_response(302)
            self.send_header("Location", "/login")
            self.send_header("Set-Cookie", "session=; HttpOnly; Path=/; Max-Age=0")
            self.send_header("Content-Length", "0")
            self.end_headers()

        elif path == "/admin":
            user = self.require_admin()
            if user:
                self.send_html(200, admin_page(user))

        elif path == "/callsign_lookup":
            if not self.require_login():
                return
            qs = parse_qs(urlparse(self.path).query)
            cs = qs.get("cs", [""])[0].strip().upper()
            if not cs:
                self.send_json(400, {"ok": False, "message": "No call sign provided"})
                return
            result = lookup_callsign_acma(cs)
            self.send_json(200, result)

        elif path == "/files":
            if not self.require_login():
                return
            files = sorted(f.name for f in UPLOAD_DIR.iterdir() if f.is_file())
            self.send_json(200, {"files": files})

        elif path.startswith("/download/"):
            if not self.require_login():
                return
            filename = path[len("/download/"):]
            filepath = UPLOAD_DIR / Path(filename).name
            if not filepath.exists() or not filepath.is_file():
                self.send_json(404, {"ok": False, "message": "File not found"})
                return
            with open(filepath, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Disposition", f'attachment; filename="{filepath.name}"')
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        else:
            self.send_json(404, {"ok": False, "message": "Not found"})

    # ── POST ──────────────────────────────────────────────────────────────
    def do_POST(self):
        path = urlparse(self.path).path

        # ── Login ──
        if path == "/login":
            form = self.parse_form()
            username = form.get("username", "").strip()
            password = form.get("password", "")
            if check_login(username, password):
                token = create_session(username)
                self.redirect_with_cookie("/", token)
            else:
                self.send_html(200, login_page("Invalid username or password."))
            return

        # ── File upload ──
        if path == "/upload":
            if not self.require_login():
                return
            content_type = self.headers.get("Content-Type", "")
            if "multipart/form-data" not in content_type:
                self.send_json(400, {"ok": False, "message": "Expected multipart/form-data"})
                return
            import io
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            env = {
                "REQUEST_METHOD": "POST",
                "CONTENT_TYPE": content_type,
                "CONTENT_LENGTH": str(length),
            }
            form = cgi.FieldStorage(fp=io.BytesIO(body), headers=self.headers, environ=env)
            files_field = form.get("files")
            if files_field is None:
                self.send_json(400, {"ok": False, "message": "No files field"})
                return
            items = files_field if isinstance(files_field, list) else [files_field]
            saved = []
            for item in items:
                if item.filename:
                    safe_name = Path(item.filename).name
                    dest = UPLOAD_DIR / safe_name
                    with open(dest, "wb") as f:
                        shutil.copyfileobj(item.file, f)
                    saved.append(safe_name)
            if saved:
                self.send_json(200, {"ok": True, "message": f"Uploaded {len(saved)} file(s): {', '.join(saved)}"})
            else:
                self.send_json(400, {"ok": False, "message": "No valid files received"})
            return

        # ── Admin: add user ──
        if path == "/admin/add":
            admin = self.require_admin()
            if not admin:
                return
            form = self.parse_form()
            uname = form.get("username", "").strip()
            pw    = form.get("password", "")
            pw2   = form.get("password2", "")
            role  = form.get("role", "user")
            if not uname:
                self.send_html(200, admin_page(admin, "Username cannot be empty.", "err"))
                return
            if pw != pw2:
                self.send_html(200, admin_page(admin, "Passwords do not match.", "err"))
                return
            if len(pw) < 4:
                self.send_html(200, admin_page(admin, "Password must be at least 4 characters.", "err"))
                return
            users = load_users()
            if uname in users:
                self.send_html(200, admin_page(admin, f"User '{uname}' already exists.", "err"))
                return
            users[uname] = {
                "password":   hash_pw(pw),
                "role":       role,
                "first_name": form.get("first_name", "").strip(),
                "last_name":  form.get("last_name", "").strip(),
                "call_sign":  form.get("call_sign", "").strip().upper(),
            }
            save_users(users)
            self.send_html(200, admin_page(admin, f"User '{uname}' created successfully."))
            return

        # ── Admin: delete user ──
        if path == "/admin/delete":
            admin = self.require_admin()
            if not admin:
                return
            form = self.parse_form()
            uname = form.get("username", "").strip()
            if uname == admin:
                self.send_html(200, admin_page(admin, "You cannot delete your own account.", "err"))
                return
            users = load_users()
            if uname not in users:
                self.send_html(200, admin_page(admin, f"User '{uname}' not found.", "err"))
                return
            del users[uname]
            save_users(users)
            # Evict any active session for deleted user
            for tok, u in list(SESSIONS.items()):
                if u == uname:
                    del SESSIONS[tok]
            self.send_html(200, admin_page(admin, f"User '{uname}' deleted."))
            return

        # ── Admin: change role ──
        if path == "/admin/role":
            admin = self.require_admin()
            if not admin:
                return
            form = self.parse_form()
            uname = form.get("username", "").strip()
            role  = form.get("role", "user")
            users = load_users()
            if uname not in users:
                self.send_html(200, admin_page(admin, f"User '{uname}' not found.", "err"))
                return
            # Prevent demoting yourself
            if uname == admin and role != "admin":
                self.send_html(200, admin_page(admin, "You cannot demote your own account.", "err"))
                return
            users[uname]["role"] = role
            save_users(users)
            self.send_html(200, admin_page(admin, f"Role for '{uname}' updated to {role}."))
            return

        # ── Admin: change password ──
        if path == "/admin/chpw":
            admin = self.require_admin()
            if not admin:
                return
            form = self.parse_form()
            uname = form.get("username", "").strip()
            pw    = form.get("password", "")
            if len(pw) < 4:
                self.send_html(200, admin_page(admin, "Password must be at least 4 characters.", "err"))
                return
            users = load_users()
            if uname not in users:
                self.send_html(200, admin_page(admin, f"User '{uname}' not found.", "err"))
                return
            users[uname]["password"] = hash_pw(pw)
            save_users(users)
            self.send_html(200, admin_page(admin, f"Password for '{uname}' updated."))
            return

        # ── Profile update (any logged-in user) ──
        if path == "/profile":
            user = self.require_login()
            if not user:
                return
            form = self.parse_form()
            users = load_users()
            if user not in users:
                self.send_json(400, {"ok": False, "message": "User not found"})
                return
            users[user]["first_name"] = form.get("first_name", "").strip()
            users[user]["last_name"]  = form.get("last_name", "").strip()
            users[user]["call_sign"]  = form.get("call_sign", "").strip().upper()
            save_users(users)
            self.send_json(200, {"ok": True, "message": "Profile updated."})
            return

        self.send_json(404, {"ok": False, "message": "Not found"})


if __name__ == "__main__":
    load_users()  # ensure default admin exists
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Ham Radio site running at http://0.0.0.0:{PORT}")
    print(f"Default admin login — username: admin  password: admin123")
    print(f"Users stored at: {USERS_FILE}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
