#!/usr/bin/env python3
"""Ham Radio Website - runs on port 8081"""

import os
import cgi
import json
import shutil
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from pathlib import Path

UPLOAD_DIR = Path(__file__).parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
PORT = 8081

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Ham Radio</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    background: #0a0f1a;
    color: #c8d8e8;
    min-height: 100vh;
  }

  /* ── HEADER ── */
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

  .antenna-icon {
    font-size: 42px;
    filter: drop-shadow(0 0 8px #2a7fbf);
  }

  header h1 {
    font-size: 2.4rem;
    font-weight: 800;
    color: #5bc8f5;
    text-shadow: 0 0 18px rgba(91,200,245,0.7);
    letter-spacing: 3px;
    text-transform: uppercase;
  }

  header h1 span { color: #ff9f1c; }

  .clock-box {
    text-align: right;
    background: rgba(0,0,0,0.4);
    border: 1px solid #2a7fbf;
    border-radius: 10px;
    padding: 10px 20px;
  }

  #clock {
    font-size: 2rem;
    font-weight: 700;
    color: #39ff14;
    font-family: 'Courier New', monospace;
    letter-spacing: 3px;
    text-shadow: 0 0 10px #39ff14;
  }

  #clock-label { font-size: 0.7rem; color: #7ab3d0; letter-spacing: 2px; margin-top: 2px; }

  /* ── MAIN LAYOUT ── */
  main {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 28px;
    padding: 32px;
    max-width: 1200px;
    margin: 0 auto;
  }

  @media (max-width: 768px) { main { grid-template-columns: 1fr; } }

  .card {
    background: linear-gradient(160deg, #0d1b2a, #112233);
    border: 1px solid #1e4a6e;
    border-radius: 14px;
    padding: 24px;
    box-shadow: 0 4px 24px rgba(0,0,0,0.5);
  }

  .card h2 {
    font-size: 1.1rem;
    color: #5bc8f5;
    letter-spacing: 2px;
    text-transform: uppercase;
    margin-bottom: 20px;
    padding-bottom: 10px;
    border-bottom: 1px solid #1e4a6e;
  }

  /* ── CALENDAR ── */
  .cal-nav {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 14px;
  }

  .cal-nav button {
    background: #1a3a5c;
    border: 1px solid #2a7fbf;
    color: #5bc8f5;
    border-radius: 6px;
    padding: 4px 12px;
    cursor: pointer;
    font-size: 1rem;
    transition: background 0.2s;
  }

  .cal-nav button:hover { background: #2a7fbf; color: #fff; }

  #cal-month-label {
    font-weight: 700;
    color: #ff9f1c;
    font-size: 1.05rem;
    letter-spacing: 1px;
  }

  #calendar-grid {
    width: 100%;
    border-collapse: collapse;
  }

  #calendar-grid th {
    color: #7ab3d0;
    font-size: 0.75rem;
    letter-spacing: 1px;
    padding: 6px 0;
    text-align: center;
  }

  #calendar-grid td {
    text-align: center;
    padding: 7px 4px;
    border-radius: 6px;
    cursor: pointer;
    font-size: 0.9rem;
    transition: background 0.15s;
  }

  #calendar-grid td:hover:not(.empty) { background: #1a3a5c; }

  #calendar-grid td.today {
    background: #2a7fbf;
    color: #fff;
    font-weight: 700;
    border-radius: 50%;
    box-shadow: 0 0 10px rgba(42,127,191,0.6);
  }

  #calendar-grid td.selected {
    background: #ff9f1c;
    color: #0a0f1a;
    font-weight: 700;
    border-radius: 50%;
  }

  #calendar-grid td.empty { cursor: default; }

  #selected-date {
    margin-top: 14px;
    font-size: 0.85rem;
    color: #ff9f1c;
    text-align: center;
    min-height: 1.2em;
  }

  /* ── UPLOAD ── */
  .drop-zone {
    border: 2px dashed #2a7fbf;
    border-radius: 10px;
    padding: 30px 20px;
    text-align: center;
    cursor: pointer;
    transition: border-color 0.2s, background 0.2s;
    margin-bottom: 16px;
    position: relative;
  }

  .drop-zone:hover, .drop-zone.dragover {
    border-color: #5bc8f5;
    background: rgba(42,127,191,0.08);
  }

  .drop-zone input[type="file"] {
    position: absolute; inset: 0; opacity: 0; cursor: pointer; width: 100%; height: 100%;
  }

  .drop-zone .dz-icon { font-size: 2.2rem; margin-bottom: 8px; }
  .drop-zone p { color: #7ab3d0; font-size: 0.9rem; }
  .drop-zone p strong { color: #5bc8f5; }

  #upload-btn {
    width: 100%;
    padding: 12px;
    background: linear-gradient(135deg, #2a7fbf, #1a5c8f);
    border: none;
    border-radius: 8px;
    color: #fff;
    font-size: 1rem;
    font-weight: 600;
    cursor: pointer;
    letter-spacing: 1px;
    transition: opacity 0.2s, box-shadow 0.2s;
  }

  #upload-btn:hover { opacity: 0.88; box-shadow: 0 0 14px rgba(42,127,191,0.6); }
  #upload-btn:disabled { opacity: 0.4; cursor: not-allowed; }

  #upload-status {
    margin-top: 12px;
    font-size: 0.85rem;
    min-height: 1.2em;
    text-align: center;
  }

  .status-ok  { color: #39ff14; }
  .status-err { color: #ff4444; }

  /* ── FILE LIST ── */
  #file-list { list-style: none; }

  #file-list li {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px 10px;
    border-radius: 6px;
    font-size: 0.85rem;
    border-bottom: 1px solid #1a3a5c;
    transition: background 0.15s;
  }

  #file-list li:last-child { border-bottom: none; }
  #file-list li:hover { background: #112233; }

  .file-icon { font-size: 1.1rem; }

  .file-name {
    flex: 1;
    color: #c8d8e8;
    word-break: break-all;
  }

  .file-link {
    color: #5bc8f5;
    text-decoration: none;
    font-size: 0.75rem;
    border: 1px solid #1e4a6e;
    border-radius: 4px;
    padding: 2px 8px;
    white-space: nowrap;
  }

  .file-link:hover { background: #1a3a5c; }

  .no-files { color: #4a6a80; font-size: 0.85rem; text-align: center; padding: 16px 0; }

  /* ── PROGRESS BAR ── */
  #progress-wrap {
    height: 6px;
    background: #1a3a5c;
    border-radius: 3px;
    margin-top: 10px;
    overflow: hidden;
    display: none;
  }

  #progress-bar {
    height: 100%;
    width: 0%;
    background: linear-gradient(90deg, #2a7fbf, #39ff14);
    transition: width 0.2s;
    border-radius: 3px;
  }
</style>
</head>
<body>

<header>
  <div class="logo-area">
    <div class="antenna-icon">📡</div>
    <h1>Ham <span>Radio</span></h1>
  </div>
  <div class="clock-box">
    <div id="clock">00:00:00</div>
    <div id="clock-label">LOCAL TIME</div>
  </div>
</header>

<main>

  <!-- ── CALENDAR CARD ── -->
  <div class="card">
    <h2>📅 Calendar</h2>
    <div class="cal-nav">
      <button id="prev-month">&#8249;</button>
      <span id="cal-month-label"></span>
      <button id="next-month">&#8250;</button>
    </div>
    <table id="calendar-grid">
      <thead>
        <tr>
          <th>Su</th><th>Mo</th><th>Tu</th><th>We</th>
          <th>Th</th><th>Fr</th><th>Sa</th>
        </tr>
      </thead>
      <tbody id="cal-body"></tbody>
    </table>
    <div id="selected-date"></div>
  </div>

  <!-- ── UPLOAD CARD ── -->
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

<script>
// ── CLOCK ──
function updateClock() {
  const now = new Date();
  const h = String(now.getHours()).padStart(2,'0');
  const m = String(now.getMinutes()).padStart(2,'0');
  const s = String(now.getSeconds()).padStart(2,'0');
  document.getElementById('clock').textContent = h + ':' + m + ':' + s;
}
updateClock();
setInterval(updateClock, 1000);

// ── CALENDAR ──
const today = new Date();
let viewYear  = today.getFullYear();
let viewMonth = today.getMonth();
let selectedDate = null;

const MONTHS = ['January','February','March','April','May','June',
                'July','August','September','October','November','December'];

function renderCalendar() {
  const label = document.getElementById('cal-month-label');
  const body  = document.getElementById('cal-body');
  label.textContent = MONTHS[viewMonth] + ' ' + viewYear;
  body.innerHTML = '';

  const firstDay = new Date(viewYear, viewMonth, 1).getDay();
  const daysIn   = new Date(viewYear, viewMonth + 1, 0).getDate();

  let row = document.createElement('tr');
  for (let i = 0; i < firstDay; i++) {
    const td = document.createElement('td');
    td.className = 'empty';
    row.appendChild(td);
  }

  for (let d = 1; d <= daysIn; d++) {
    if (row.children.length === 7) {
      body.appendChild(row);
      row = document.createElement('tr');
    }
    const td = document.createElement('td');
    td.textContent = d;
    const isToday = (d === today.getDate() && viewMonth === today.getMonth() && viewYear === today.getFullYear());
    const thisDt  = viewYear + '-' + String(viewMonth+1).padStart(2,'0') + '-' + String(d).padStart(2,'0');
    if (isToday) td.classList.add('today');
    if (selectedDate === thisDt) td.classList.add('selected');
    td.addEventListener('click', () => {
      selectedDate = thisDt;
      document.getElementById('selected-date').textContent = 'Selected: ' + MONTHS[viewMonth] + ' ' + d + ', ' + viewYear;
      renderCalendar();
    });
    row.appendChild(td);
  }
  while (row.children.length < 7) {
    const td = document.createElement('td'); td.className = 'empty'; row.appendChild(td);
  }
  body.appendChild(row);
}

document.getElementById('prev-month').addEventListener('click', () => {
  viewMonth--; if (viewMonth < 0) { viewMonth = 11; viewYear--; } renderCalendar();
});
document.getElementById('next-month').addEventListener('click', () => {
  viewMonth++; if (viewMonth > 11) { viewMonth = 0; viewYear++; } renderCalendar();
});

renderCalendar();

// ── FILE UPLOAD ──
const fileInput  = document.getElementById('file-input');
const uploadBtn  = document.getElementById('upload-btn');
const dropZone   = document.getElementById('drop-zone');
const statusEl   = document.getElementById('upload-status');
const progressWrap = document.getElementById('progress-wrap');
const progressBar  = document.getElementById('progress-bar');

fileInput.addEventListener('change', () => {
  uploadBtn.disabled = fileInput.files.length === 0;
});

dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('dragover'); });
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
dropZone.addEventListener('drop', e => {
  e.preventDefault();
  dropZone.classList.remove('dragover');
  fileInput.files = e.dataTransfer.files;
  uploadBtn.disabled = fileInput.files.length === 0;
});

uploadBtn.addEventListener('click', () => {
  const files = fileInput.files;
  if (!files.length) return;

  const formData = new FormData();
  for (const f of files) formData.append('files', f);

  uploadBtn.disabled = true;
  progressWrap.style.display = 'block';
  progressBar.style.width = '0%';
  statusEl.textContent = '';
  statusEl.className = '';

  const xhr = new XMLHttpRequest();
  xhr.open('POST', '/upload');

  xhr.upload.addEventListener('progress', e => {
    if (e.lengthComputable) {
      progressBar.style.width = (e.loaded / e.total * 100) + '%';
    }
  });

  xhr.addEventListener('load', () => {
    progressBar.style.width = '100%';
    try {
      const res = JSON.parse(xhr.responseText);
      if (res.ok) {
        statusEl.textContent = '✓ ' + res.message;
        statusEl.className = 'status-ok';
        fileInput.value = '';
        loadFiles();
      } else {
        statusEl.textContent = '✗ ' + res.message;
        statusEl.className = 'status-err';
      }
    } catch {
      statusEl.textContent = '✗ Unexpected server error';
      statusEl.className = 'status-err';
    }
    uploadBtn.disabled = false;
    setTimeout(() => { progressWrap.style.display = 'none'; progressBar.style.width = '0%'; }, 1200);
  });

  xhr.addEventListener('error', () => {
    statusEl.textContent = '✗ Upload failed';
    statusEl.className = 'status-err';
    uploadBtn.disabled = false;
    progressWrap.style.display = 'none';
  });

  xhr.send(formData);
});

// ── FILE LIST ──
function fileIcon(name) {
  const ext = name.split('.').pop().toLowerCase();
  const map = {
    pdf:'📄', png:'🖼️', jpg:'🖼️', jpeg:'🖼️', gif:'🖼️', svg:'🖼️', webp:'🖼️',
    mp3:'🎵', wav:'🎵', ogg:'🎵', flac:'🎵',
    mp4:'🎬', avi:'🎬', mkv:'🎬', mov:'🎬',
    zip:'🗜️', tar:'🗜️', gz:'🗜️', rar:'🗜️',
    txt:'📝', log:'📝', md:'📝',
    py:'🐍', js:'📜', ts:'📜', html:'🌐', css:'🎨',
  };
  return map[ext] || '📁';
}

function loadFiles() {
  fetch('/files')
    .then(r => r.json())
    .then(data => {
      const list = document.getElementById('file-list');
      if (!data.files || data.files.length === 0) {
        list.innerHTML = '<li class="no-files">No files uploaded yet.</li>';
        return;
      }
      list.innerHTML = data.files.map(f => `
        <li>
          <span class="file-icon">${fileIcon(f)}</span>
          <span class="file-name">${escHtml(f)}</span>
          <a class="file-link" href="/download/${encodeURIComponent(f)}" download>⬇ Download</a>
        </li>
      `).join('');
    })
    .catch(() => {});
}

function escHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

loadFiles();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[{self.address_string()}] {fmt % args}")

    def send_json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "/index.html":
            body = HTML.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        elif path == "/files":
            files = sorted(f.name for f in UPLOAD_DIR.iterdir() if f.is_file())
            self.send_json(200, {"files": files})

        elif path.startswith("/download/"):
            filename = path[len("/download/"):]
            # Basic path-traversal protection
            filepath = UPLOAD_DIR / Path(filename).name
            if not filepath.exists() or not filepath.is_file():
                self.send_json(404, {"ok": False, "message": "File not found"})
                return
            mime = "application/octet-stream"
            with open(filepath, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Disposition", f'attachment; filename="{filepath.name}"')
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        else:
            self.send_json(404, {"ok": False, "message": "Not found"})

    def do_POST(self):
        if self.path != "/upload":
            self.send_json(404, {"ok": False, "message": "Not found"})
            return

        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            self.send_json(400, {"ok": False, "message": "Expected multipart/form-data"})
            return

        # Parse multipart manually using cgi module
        env = {
            "REQUEST_METHOD": "POST",
            "CONTENT_TYPE": content_type,
            "CONTENT_LENGTH": self.headers.get("Content-Length", "0"),
        }
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        import io
        form = cgi.FieldStorage(
            fp=io.BytesIO(body),
            headers=self.headers,
            environ=env
        )

        saved = []
        files_field = form["files"] if "files" in form else None
        if files_field is None:
            self.send_json(400, {"ok": False, "message": "No files field in form"})
            return

        items = files_field if isinstance(files_field, list) else [files_field]
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


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Ham Radio site running at http://0.0.0.0:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
