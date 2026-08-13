#!/usr/bin/env python3
"""
Δ Τ Δ - Brotherhood Portal (Combined App)
Points system + Budget system with shared login.
Local:   pip install flask psycopg2-binary && python app.py
Railway: set DATABASE_URL env var

Routes:
  /          
  /points    
  /budget    
  /dailies
"""


"""
Push Notes: 
- Fixed XSS vulnerability (thanks Lance) -- we assume people with officer/admin/moderator roles don't make XSS attempts though, only block custom points 
-Removed import calls in function definitions

"""
from functools import wraps
from flask import Flask, request, jsonify, session, redirect, Response
from werkzeug.security import check_password_hash, generate_password_hash
from html import escape as html_escape
from dotenv import load_dotenv
import hashlib
import json
import os
import re
import datetime
import bleach
import urllib.error
import urllib.request

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))

# Postgres when DATABASE_URL is set (Railway), SQLite locally as fallback
DATABASE_URL = os.environ.get('DATABASE_URL')

if DATABASE_URL:
    import psycopg2
    import psycopg2.extras
    PH = '%s'  # Postgres placeholder
else:
    import sqlite3
    PH = '?'   # SQLite placeholder

app = Flask(__name__)
# Stable key locally so sessions survive reload. Railway should set SECRET_KEY.
app.secret_key = os.environ.get(
    'SECRET_KEY',
    'dev-only-not-for-production' if not DATABASE_URL else os.urandom(24),
)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SQLITE_PATH = os.path.join(BASE_DIR, 'brotherhood_system.db')

# ============================================================================
# DATABASE
# ============================================================================

def get_db():
    if DATABASE_URL:
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = False
        return conn
    else:
        conn = sqlite3.connect(SQLITE_PATH)
        conn.row_factory = sqlite3.Row
        return conn

def fetchone(conn, sql, params=()):
    """Unified fetchone that always returns a dict-like row."""
    sql = sql.replace('?', PH)

    if DATABASE_URL:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql, params)
        return cur.fetchone()
    else:
        return conn.execute(sql, params).fetchone()

def fetchall(conn, sql, params=()):
    """Unified fetchall that always returns a list of dict-like rows."""
    sql = sql.replace('?', PH)
    if DATABASE_URL:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]
    else:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]

def execute(conn, sql, params=()):
    """Unified execute."""
    sql = sql.replace('?', PH)
    if DATABASE_URL:
        cur = conn.cursor()
        cur.execute(sql, params)
        return cur
    else:
        return conn.execute(sql, params)

def init_db():
    conn = get_db()
    if DATABASE_URL:
        # Postgres: use SERIAL instead of AUTOINCREMENT, TRUE/FALSE for booleans
        execute(conn, '''CREATE TABLE IF NOT EXISTS users (
            user_id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            role TEXT NOT NULL,
            brotherhood_points INTEGER DEFAULT 0,
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        execute(conn, '''CREATE TABLE IF NOT EXISTS transactions (
            transaction_id SERIAL PRIMARY KEY,
            member_id INTEGER NOT NULL REFERENCES users(user_id),
            points INTEGER NOT NULL,
            description TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            reviewed_by TEXT,
            reviewed_at TIMESTAMP,
            rejection_reason TEXT
        )''')
        execute(conn, '''CREATE TABLE IF NOT EXISTS point_actions (
            action_id SERIAL PRIMARY KEY,
            label TEXT NOT NULL,
            points INTEGER NOT NULL,
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        execute(conn, '''CREATE TABLE IF NOT EXISTS audit_log (
            log_id SERIAL PRIMARY KEY,
            action TEXT NOT NULL,
            user_id INTEGER,
            details TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        execute(conn, '''CREATE TABLE IF NOT EXISTS daily_tasks (
            task_id SERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            category TEXT NOT NULL,
            point_value INTEGER DEFAULT 0,
            is_active BOOLEAN DEFAULT TRUE,
            created_by INTEGER REFERENCES users(user_id),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        execute(conn, '''CREATE TABLE IF NOT EXISTS daily_assignments (
            assignment_id SERIAL PRIMARY KEY,
            task_id INTEGER NOT NULL REFERENCES daily_tasks(task_id),
            member_id INTEGER NOT NULL REFERENCES users(user_id),
            week_start DATE NOT NULL,
            due_date DATE NOT NULL,
            status TEXT DEFAULT 'pending',
            completed_at TIMESTAMP,
            approved_by INTEGER REFERENCES users(user_id),
            approved_at TIMESTAMP,
            notes TEXT DEFAULT ''
        )''')
        execute(conn, '''CREATE TABLE IF NOT EXISTS rotation_template (
            rotation_id SERIAL PRIMARY KEY,
            task_id INTEGER NOT NULL REFERENCES daily_tasks(task_id),
            day_of_week INTEGER NOT NULL,
            member_id INTEGER NOT NULL REFERENCES users(user_id),
            UNIQUE(task_id, day_of_week)
        )''')
    else:
        execute(conn, '''CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            role TEXT NOT NULL,
            brotherhood_points INTEGER DEFAULT 0,
            is_active BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        execute(conn, '''CREATE TABLE IF NOT EXISTS transactions (
            transaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
            member_id INTEGER NOT NULL,
            points INTEGER NOT NULL,
            description TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            reviewed_by TEXT,
            reviewed_at TIMESTAMP,
            rejection_reason TEXT,
            FOREIGN KEY (member_id) REFERENCES users(user_id)
        )''')
        execute(conn, '''CREATE TABLE IF NOT EXISTS point_actions (
            action_id INTEGER PRIMARY KEY AUTOINCREMENT,
            label TEXT NOT NULL,
            points INTEGER NOT NULL,
            is_active BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        execute(conn, '''CREATE TABLE IF NOT EXISTS audit_log (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL,
            user_id INTEGER,
            details TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        execute(conn, '''CREATE TABLE IF NOT EXISTS daily_tasks (
            task_id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            category TEXT NOT NULL,
            point_value INTEGER DEFAULT 0,
            is_active BOOLEAN DEFAULT 1,
            created_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        execute(conn, '''CREATE TABLE IF NOT EXISTS daily_assignments (
            assignment_id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            member_id INTEGER NOT NULL,
            week_start DATE NOT NULL,
            due_date DATE NOT NULL,
            status TEXT DEFAULT 'pending',
            completed_at TIMESTAMP,
            approved_by INTEGER,
            approved_at TIMESTAMP,
            notes TEXT DEFAULT ''
        )''')
        execute(conn, '''CREATE TABLE IF NOT EXISTS rotation_template (
            rotation_id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            day_of_week INTEGER NOT NULL,
            member_id INTEGER NOT NULL,
            UNIQUE(task_id, day_of_week)
        )''')

    # Budget-specific tables
    if DATABASE_URL:
        execute(conn, '''CREATE TABLE IF NOT EXISTS budget_departments (
            dept_id SERIAL PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            description TEXT DEFAULT '',
            is_active BOOLEAN DEFAULT TRUE,
            created_by INTEGER REFERENCES users(user_id),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        execute(conn, '''CREATE TABLE IF NOT EXISTS budget_items (
            item_id SERIAL PRIMARY KEY,
            dept_id INTEGER NOT NULL REFERENCES budget_departments(dept_id),
            name TEXT NOT NULL,
            allocated NUMERIC(12,2) NOT NULL DEFAULT 0,
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        execute(conn, '''CREATE TABLE IF NOT EXISTS budget_requests (
            request_id SERIAL PRIMARY KEY,
            item_id INTEGER NOT NULL REFERENCES budget_items(item_id),
            submitted_by INTEGER NOT NULL REFERENCES users(user_id),
            amount NUMERIC(12,2) NOT NULL,
            description TEXT NOT NULL,
            vendor TEXT DEFAULT '',
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            reviewed_by INTEGER REFERENCES users(user_id),
            reviewed_at TIMESTAMP,
            rejection_reason TEXT
        )''')
    else:
        execute(conn, '''CREATE TABLE IF NOT EXISTS budget_departments (
            dept_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            description TEXT DEFAULT '',
            is_active BOOLEAN DEFAULT 1,
            created_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (created_by) REFERENCES users(user_id)
        )''')
        execute(conn, '''CREATE TABLE IF NOT EXISTS budget_items (
            item_id INTEGER PRIMARY KEY AUTOINCREMENT,
            dept_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            allocated REAL NOT NULL DEFAULT 0,
            is_active BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (dept_id) REFERENCES budget_departments(dept_id)
        )''')
        execute(conn, '''CREATE TABLE IF NOT EXISTS budget_requests (
            request_id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER NOT NULL,
            submitted_by INTEGER NOT NULL,
            amount REAL NOT NULL,
            description TEXT NOT NULL,
            vendor TEXT DEFAULT '',
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            reviewed_by INTEGER,
            reviewed_at TIMESTAMP,
            rejection_reason TEXT,
            FOREIGN KEY (item_id) REFERENCES budget_items(item_id),
            FOREIGN KEY (submitted_by) REFERENCES users(user_id),
            FOREIGN KEY (reviewed_by) REFERENCES users(user_id)
        )''')

    execute(conn, '''CREATE TABLE IF NOT EXISTS org_settings (
        id INTEGER PRIMARY KEY,
        letters TEXT NOT NULL,
        org_name TEXT NOT NULL,
        tagline TEXT NOT NULL,
        footer TEXT NOT NULL DEFAULT 'ΔΤΔ — Est. 1858',
        primary_color TEXT NOT NULL,
        accent_color TEXT NOT NULL,
        bg_color TEXT NOT NULL,
        text_color TEXT NOT NULL,
        configured INTEGER NOT NULL DEFAULT 0
    )''')
    try:
        execute(conn, "ALTER TABLE org_settings ADD COLUMN footer TEXT NOT NULL DEFAULT 'ΔΤΔ — Est. 1858'")
        conn.commit()
    except Exception:
        if DATABASE_URL:
            conn.rollback()

    conn.commit()
    # Seed default admin if no users exist
    row = fetchone(conn, "SELECT COUNT(*) as cnt FROM users")
    cnt = row['cnt'] if row else 0
    was_fresh = cnt == 0
    if cnt == 0:
        pw = hash_pw("admin123")
        execute(conn, "INSERT INTO users (username, password_hash, email, role) VALUES (?,?,?,?)",
                ("admin", pw, "admin@brotherhood.com", "admin"))
        conn.commit()
    if not fetchone(conn, "SELECT id FROM org_settings WHERE id=1"):
        d = DEFAULT_THEME
        # Existing deploys keep the Delts look and skip the wizard.
        configured = 0 if was_fresh else 1
        execute(conn, '''INSERT INTO org_settings
            (id, letters, org_name, tagline, footer, primary_color, accent_color, bg_color, text_color, configured)
            VALUES (?,?,?,?,?,?,?,?,?,?)''',
            (1, d['letters'], d['org_name'], d['tagline'], d['footer'],
             d['primary_color'], d['accent_color'], d['bg_color'], d['text_color'], configured))
        conn.commit()
    conn.close()

def hash_pw(pw):
    return generate_password_hash(str(pw or ''))

def check_pw(pw, stored):
    if not stored:
        return False
    stored = str(stored)
    if stored.startswith(('pbkdf2:', 'scrypt:', 'argon2:')):
        return check_password_hash(stored, pw or '')
    return hashlib.sha256((pw or '').encode()).hexdigest() == stored

def is_legacy_hash(stored):
    return bool(stored) and not str(stored).startswith(('pbkdf2:', 'scrypt:', 'argon2:'))

def sanitize_text(value, default=''):
    if value is None:
        return default
    return bleach.clean(str(value), tags=[], attributes={}, strip=True).strip()

DEFAULT_THEME = {
    'letters': 'ΔΤΔ',
    'org_name': 'Delta Tau Delta',
    'tagline': 'Brotherhood Management Portal',
    'footer': 'ΔΤΔ — Est. 1858',
    'primary_color': '#3D0C45',
    'accent_color': '#C9A84C',
    'bg_color': '#0D0910',
    'text_color': '#F0E8D0',
}
HEX_COLOR = re.compile(r'^#[0-9A-Fa-f]{6}$')
EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
BUG_REPO_RE = re.compile(r'^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')

def _settings_from_row(row):
    if row is None:
        d = dict(DEFAULT_THEME)
        d['configured'] = 0
        return d
    footer = DEFAULT_THEME['footer']
    try:
        footer = row['footer'] or DEFAULT_THEME['footer']
    except (KeyError, IndexError):
        pass
    return {
        'letters': row['letters'],
        'org_name': row['org_name'],
        'tagline': row['tagline'],
        'footer': footer,
        'primary_color': row['primary_color'],
        'accent_color': row['accent_color'],
        'bg_color': row['bg_color'],
        'text_color': row['text_color'],
        'configured': int(row['configured'] or 0),
    }

def get_org_settings():
    conn = get_db()
    row = fetchone(conn, "SELECT * FROM org_settings WHERE id=1")
    conn.close()
    return _settings_from_row(row)

def _is_configured():
    return bool(get_org_settings()['configured'])

def _norm_hex(value):
    return (value or '').strip().upper()

def _is_default_palette(s):
    return (
        _norm_hex(s['primary_color']) == '#3D0C45'
        and _norm_hex(s['accent_color']) == '#C9A84C'
        and _norm_hex(s['bg_color']) == '#0D0910'
        and _norm_hex(s['text_color']) == '#F0E8D0'
    )

def _theme_css(s):
    letters = json.dumps(s['letters'] or '', ensure_ascii=False)
    if _is_default_palette(s):
        derived = (
            '  --purple-mid:#5C1F6B;\n'
            '  --purple-light:#7B3094;\n'
            '  --gold-bright:#E8C96A;\n'
            '  --gold-dim:#8A7235;\n'
            '  --dark-2:#150D1A;\n'
            '  --dark-3:#1E1227;\n'
            '  --dark-4:#261630;\n'
            '  --surface:#1A0F21;\n'
            '  --surface-2:#231428;\n'
            '  --border:rgba(201,168,76,0.18);\n'
            '  --border-strong:rgba(201,168,76,0.38);\n'
            '  --text-dim:#9A8E7A;\n'
            '  --text-muted:#5C5248;\n'
        )
    else:
        derived = (
            '  --purple-mid:color-mix(in srgb,var(--purple) 75%,white);\n'
            '  --purple-light:color-mix(in srgb,var(--purple) 55%,white);\n'
            '  --gold-bright:color-mix(in srgb,var(--gold) 82%,white);\n'
            '  --gold-dim:color-mix(in srgb,var(--gold) 70%,black);\n'
            '  --dark-2:color-mix(in srgb,var(--dark) 88%,var(--purple));\n'
            '  --dark-3:color-mix(in srgb,var(--dark) 78%,var(--purple));\n'
            '  --dark-4:color-mix(in srgb,var(--dark) 70%,var(--purple));\n'
            '  --surface:color-mix(in srgb,var(--dark) 85%,var(--purple));\n'
            '  --surface-2:color-mix(in srgb,var(--dark) 80%,var(--purple));\n'
            '  --border:color-mix(in srgb,var(--gold) 18%,transparent);\n'
            '  --border-strong:color-mix(in srgb,var(--gold) 38%,transparent);\n'
            '  --text-dim:color-mix(in srgb,var(--text) 62%,var(--dark));\n'
            '  --text-muted:color-mix(in srgb,var(--text) 38%,var(--dark));\n'
        )
    return (
        ':root{\n'
        f'  --purple:{s["primary_color"]};\n'
        f'  --gold:{s["accent_color"]};\n'
        f'  --dark:{s["bg_color"]};\n'
        f'  --text:{s["text_color"]};\n'
        f'{derived}'
        f'  --brand-letters:{letters};\n'
        '}\n'
    )

def _clean_brand_text(value, max_len):
    text = sanitize_text(value)
    text = ''.join(c for c in text if c not in '`"\\$')
    return text[:max_len].strip()

def _parse_hex_color(value, field):
    color = sanitize_text(value).strip()
    if not HEX_COLOR.match(color):
        return None, field
    return color, None

def setup_gate(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not _is_configured():
            return redirect('/setup')
        return f(*args, **kwargs)
    return decorated

def _bug_reports_enabled():
    token = (os.environ.get('GITHUB_TOKEN') or '').strip()
    repo = (os.environ.get('GITHUB_BUG_REPO') or '').strip()
    return bool(token) and bool(BUG_REPO_RE.match(repo))

def _github_create_issue(title, body):
    repo = (os.environ.get('GITHUB_BUG_REPO') or '').strip()
    token = (os.environ.get('GITHUB_TOKEN') or '').strip()
    payload = json.dumps({'title': title, 'body': body}).encode()
    req = urllib.request.Request(
        f'https://api.github.com/repos/{repo}/issues',
        data=payload,
        method='POST',
    )
    req.add_header('Authorization', f'Bearer {token}')
    req.add_header('Accept', 'application/vnd.github+json')
    req.add_header('Content-Type', 'application/json')
    req.add_header('User-Agent', 'DeltApp')
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())

def log_audit(user_id, action, details=""):
    try:
        conn = get_db()
        execute(conn, "INSERT INTO audit_log (user_id, action, details) VALUES (?,?,?)", (user_id, action, details))
        conn.commit()
        conn.close()
    except: pass

def is_integrity_error(e):
    if DATABASE_URL:
        return isinstance(e, psycopg2.errors.UniqueViolation)
    else:
        return isinstance(e, sqlite3.IntegrityError)


def ser(rows):
    """Make datetime fields JSON-serialisable."""
    for r in rows:
        for k, v in r.items():
            if isinstance(v, (datetime.datetime, datetime.date)):
                r[k] = v.isoformat()
    return rows


# ============================================================================
# SHARED AUTH DECORATORS
# ============================================================================

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('role') != 'admin':
            return jsonify({'error': 'Forbidden'}), 403
        return f(*args, **kwargs)
    return decorated

def moderator_required(f):
    
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('role') not in ('admin', 'moderator'):
            return jsonify({'error': 'Forbidden'}), 403
        return f(*args, **kwargs)
    return decorated

# Alias for budget app compatibility
mod_required = moderator_required

def officer_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('role') not in ('admin', 'moderator', 'officer'):
            return jsonify({'error': 'Forbidden'}), 403
        return f(*args, **kwargs)
    return decorated

# ============================================================================
# SHARED AUTH ROUTES  (one login serves both apps)
# ============================================================================

@app.route('/api/login', methods=['POST'])
@app.route('/points/api/login', methods=['POST'])
@app.route('/budget/api/login', methods=['POST'])
def api_login():
    data = request.json or {}
    pw = data.get('password', '')
    conn = get_db()
    user = fetchone(conn, "SELECT * FROM users WHERE username=? AND is_active=true", (data.get('username'),))
    if not (user and check_pw(pw, user['password_hash'])):
        conn.close()
        return jsonify({'error': 'Invalid credentials'}), 401
    if is_legacy_hash(user['password_hash']):
        execute(conn, "UPDATE users SET password_hash=? WHERE user_id=?", (hash_pw(pw), user['user_id']))
        conn.commit()
    conn.close()
    session['user_id'] = user['user_id']
    session['username'] = user['username']
    session['role'] = user['role']
    log_audit(user['user_id'], 'LOGIN', f"User {user['username']} logged in")
    return jsonify({'success': True, 'role': user['role'], 'username': user['username']})

@app.route('/api/logout', methods=['POST'])
@app.route('/points/api/logout', methods=['POST'])
@app.route('/budget/api/logout', methods=['POST'])
def api_logout():
    log_audit(session.get('user_id'), 'LOGOUT', f"User {session.get('username')} logged out")
    session.clear()
    return jsonify({'success': True})

@app.route('/api/me')
@app.route('/points/api/me')
@app.route('/budget/api/me')
def api_me():
    if 'user_id' not in session:
        return jsonify({'authenticated': False, 'bug_reports': False})
    conn = get_db()
    user = fetchone(conn, "SELECT user_id, username, email, role, brotherhood_points FROM users WHERE user_id=?", (session['user_id'],))
    conn.close()
    if user:
        return jsonify({
            'authenticated': True,
            **dict(user),
            'bug_reports': _bug_reports_enabled(),
        })
    return jsonify({'authenticated': False, 'bug_reports': False})

@app.route('/api/bugs', methods=['POST'])
@login_required
def api_bugs_create():
    if not _bug_reports_enabled():
        return jsonify({'error': 'Bug reports are not configured'}), 404
    data = request.json or {}
    name = sanitize_text(data.get('name'), '')[:80]
    email = sanitize_text(data.get('email'), '')[:120]
    issue = sanitize_text(data.get('issue'), '')[:4000]
    if not name or not email or not issue:
        return jsonify({'error': 'Name, email, and issue are required'}), 400
    if not EMAIL_RE.match(email):
        return jsonify({'error': 'Invalid email'}), 400
    account = sanitize_text(session.get('username'), '')
    role = sanitize_text(session.get('role'), '')
    page = sanitize_text(data.get('page') or request.headers.get('Referer'), '')[:200]
    title = issue.split('\n', 1)[0][:72] or f'Bug from {name}'
    body = (
        f'**Name:** {name}\n'
        f'**Email:** {email}\n'
        f'**Account:** {account} ({role})\n'
        f'**Page:** {page}\n\n'
        f'{issue}'
    )
    try:
        _github_create_issue(title, body)
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors='replace')[:400]
        print(f'GitHub issue create failed: {e.code} {detail}')
        if e.code == 404:
            return jsonify({'error': 'GitHub repo not found. Create the private repo and give the token access to it.'}), 502
        if e.code in (401, 403):
            return jsonify({'error': 'GitHub token cannot create issues on that repo.'}), 502
        return jsonify({'error': 'Could not file the report'}), 502
    except urllib.error.URLError as e:
        print(f'GitHub issue create failed: {e}')
        return jsonify({'error': 'Could not reach GitHub'}), 502
    log_audit(session.get('user_id'), 'bug_report', title)
    return jsonify({'success': True})

@app.route('/bug-report.js')
def bug_report_js():
    path = os.path.join(BASE_DIR, 'bug-report.js')
    with open(path) as f:
        return Response(f.read(), mimetype='application/javascript', headers={'Cache-Control': 'no-cache'})

@app.route('/points/api/users', methods=['GET'])
@app.route('/budget/api/users', methods=['GET'])
@login_required
@admin_required
def api_get_users():
    conn = get_db()
    users = fetchall(conn, "SELECT user_id, username, email, role, brotherhood_points, is_active, created_at FROM users ORDER BY brotherhood_points DESC")
    conn.close()
    return jsonify(ser(users))

@app.route('/points/api/members', methods=['GET'])
@login_required
def api_get_members():
    conn = get_db()
    users = fetchall(conn, "SELECT user_id, username, is_active FROM users WHERE is_active=true ORDER BY username")
    conn.close()
    return jsonify(users)

@app.route('/points/api/leaderboard', methods=['GET'])
@login_required
def api_leaderboard():
    conn = get_db()
    users = fetchall(conn, "SELECT user_id, username, brotherhood_points, is_active FROM users WHERE is_active=true ORDER BY brotherhood_points DESC")
    conn.close()
    return jsonify(users)

# ============================================================================
# POINTS API ROUTES
# ============================================================================

# ============================================================================
# API ROUTES
# ============================================================================


@app.route('/points/api/users', methods=['POST'])
@login_required
@admin_required
def api_create_user():
    data = request.json
    try:
        conn = get_db()
        execute(conn, "INSERT INTO users (username, password_hash, email, role) VALUES (?,?,?,?)",
                (data['username'], hash_pw(data['password']), data['email'], data['role']))
        conn.commit()
        conn.close()
        log_audit(session['user_id'], 'CREATE_USER', f"Created user {data['username']}")
        return jsonify({'success': True})
    except Exception as e:
        if is_integrity_error(e):
            return jsonify({'error': 'Username or email already exists'}), 400
        raise


@app.route('/points/api/users/<int:uid>', methods=['PUT'])
@login_required
@admin_required
def api_update_user(uid):
    data = request.json or {}
    fields, vals = [], []
    for f in ('username', 'email', 'role'):
        if f in data:
            fields.append(f"{f}=?")
            vals.append(data[f])
    if 'is_active' in data:
        fields.append("is_active=?")
        # Normalise to Python bool so psycopg2 sends true/false, not 1/0
        vals.append(bool(int(data['is_active'])))
    if 'password' in data and data['password']:
        fields.append("password_hash=?")
        vals.append(hash_pw(data['password']))
    if not fields:
        return jsonify({'error': 'No fields to update'}), 400
    vals.append(uid)
    try:
        conn = get_db()
        execute(conn, "UPDATE users SET " + ', '.join(f + '=?' for f in [x.split('=')[0] for x in fields]) + " WHERE user_id=?", vals)
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        if is_integrity_error(e):
            return jsonify({'error': 'Username or email already exists'}), 400
        return jsonify({'error': str(e)}), 500

@app.route('/points/api/users/<int:uid>', methods=['DELETE'])
@login_required
@admin_required
def api_delete_user(uid):
    conn = get_db()
    execute(conn, "UPDATE users SET is_active=false WHERE user_id=?", (uid,))
    conn.commit()
    conn.close()
    log_audit(session['user_id'], 'DELETE_USER', f"Deactivated user {uid}")
    return jsonify({'success': True})

# Transactions
@app.route('/points/api/transactions', methods=['GET'])
@login_required
def api_get_transactions():
    conn = get_db()
    role = session.get('role')
    if role in ('admin', 'moderator'):
        rows = fetchall(conn, '''SELECT t.transaction_id, t.member_id, u.username as member_name, t.points,
            t.description, t.status, t.created_at, t.reviewed_by, t.reviewed_at, t.rejection_reason
            FROM transactions t JOIN users u ON t.member_id=u.user_id ORDER BY t.created_at DESC''')
    else:
        rows = fetchall(conn, '''SELECT t.transaction_id, t.member_id, u.username as member_name, t.points,
            t.description, t.status, t.created_at, t.reviewed_by, t.reviewed_at, t.rejection_reason
            FROM transactions t JOIN users u ON t.member_id=u.user_id WHERE t.member_id=? ORDER BY t.created_at DESC''',
            (session['user_id'],))
    conn.close()
    # Ensure datetime fields are JSON-serializable strings
    for r in rows:
        for k in ('created_at', 'reviewed_at'):
            if r.get(k) and not isinstance(r[k], str):
                r[k] = r[k].isoformat()
    return jsonify(rows)

@app.route('/points/api/transactions/pending', methods=['GET'])
@login_required
@moderator_required
def api_pending_transactions():
    conn = get_db()
    rows = fetchall(conn, '''SELECT t.transaction_id, t.member_id, u.username as member_name, t.points,
        t.description, t.status, t.created_at, t.reviewed_by, t.reviewed_at, t.rejection_reason
        FROM transactions t JOIN users u ON t.member_id=u.user_id WHERE t.status='pending' ORDER BY t.created_at ASC''')
    conn.close()
    for r in rows:
        for k in ('created_at', 'reviewed_at'):
            if r.get(k) and not isinstance(r[k], str):
                r[k] = r[k].isoformat()
    return jsonify(rows)

@app.route('/points/api/transactions', methods=['POST'])
@login_required
def api_submit_transaction():
    data = request.json
    desc = sanitize_text(data.get('description', ''))
    if not desc:
        return jsonify({'error': 'Description is required'}), 400
    # Allow submitting on behalf of another member (any logged-in user can do this)
    target_member_id = data.get('member_id', session['user_id'])
    conn = get_db()
    # Verify target member exists
    target = fetchone(conn, "SELECT user_id FROM users WHERE user_id=? AND is_active=true", (target_member_id,))
    if not target:
        conn.close()
        return jsonify({'error': 'Member not found'}), 404
    execute(conn, "INSERT INTO transactions (member_id, points, description) VALUES (?,?,?)",
            (target_member_id, data['points'], desc))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

# Point Actions
@app.route('/points/api/actions', methods=['GET'])
@login_required
def api_get_actions():
    conn = get_db()
    actions = fetchall(conn, "SELECT * FROM point_actions WHERE is_active=true ORDER BY points DESC")
    conn.close()
    return jsonify(actions)

@app.route('/points/api/actions/all', methods=['GET'])
@login_required
@admin_required
def api_get_all_actions():
    conn = get_db()
    actions = fetchall(conn, "SELECT * FROM point_actions ORDER BY created_at DESC")
    conn.close()
    return jsonify(actions)

@app.route('/points/api/actions', methods=['POST'])
@login_required
@admin_required
def api_create_action():
    data = request.json
    label = sanitize_text(data.get('label'))
    points = data.get('points')
    if not label:
        return jsonify({'error': 'Label is required'}), 400
    try:
        points = int(points)
    except (TypeError, ValueError):
        return jsonify({'error': 'Points must be a number'}), 400
    conn = get_db()
    execute(conn, "INSERT INTO point_actions (label, points) VALUES (?,?)", (label, points))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/points/api/actions/<int:aid>', methods=['PUT'])
@login_required
@admin_required
def api_update_action(aid):
    data = request.json
    label = sanitize_text(data.get('label'))
    points = data.get('points')
    is_active = data.get('is_active')
    fields, vals = [], []
    if label:
        fields.append("label=?"); vals.append(label)
    if points is not None:
        try: fields.append("points=?"); vals.append(int(points))
        except: pass
    if is_active is not None:
        fields.append("is_active=?"); vals.append(bool(is_active))
    if not fields:
        return jsonify({'error': 'Nothing to update'}), 400
    vals.append(aid)
    conn = get_db()
    execute(conn, f"UPDATE point_actions SET {', '.join(fields)} WHERE action_id=?", vals)
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/points/api/actions/<int:aid>', methods=['DELETE'])
@login_required
@admin_required
def api_delete_action(aid):
    conn = get_db()
    execute(conn, "UPDATE point_actions SET is_active=false WHERE action_id=?", (aid,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/points/api/transactions/<int:tid>/approve', methods=['POST'])
@login_required
@moderator_required
def api_approve(tid):
    conn = get_db()
    row = fetchone(conn, "SELECT member_id, points FROM transactions WHERE transaction_id=? AND status='pending'", (tid,))
    if not row:
        conn.close()
        return jsonify({'error': 'Not found or already reviewed'}), 404
    cur = execute(conn, "UPDATE transactions SET status='approved', reviewed_by=?, reviewed_at=CURRENT_TIMESTAMP WHERE transaction_id=? AND status='pending'",
            (session['username'], tid))
    if cur.rowcount != 1:
        conn.rollback()
        conn.close()
        return jsonify({'error': 'Not found or already reviewed'}), 404
    execute(conn, "UPDATE users SET brotherhood_points=brotherhood_points+? WHERE user_id=?", (row['points'], row['member_id']))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/points/api/transactions/<int:tid>/reject', methods=['POST'])
@login_required
@moderator_required
def api_reject(tid):
    data = request.json or {}
    conn = get_db()
    row = fetchone(conn, "SELECT transaction_id FROM transactions WHERE transaction_id=? AND status='pending'", (tid,))
    if not row:
        conn.close()
        return jsonify({'error': 'Not found or already reviewed'}), 404
    execute(conn, "UPDATE transactions SET status='rejected', reviewed_by=?, reviewed_at=CURRENT_TIMESTAMP, rejection_reason=? WHERE transaction_id=? AND status='pending'",
            (session['username'], sanitize_text(data.get('reason', '')), tid))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


# ============================================================================
# BUDGET API ROUTES
# ============================================================================

# ============================================================================
# DEPARTMENTS
# ============================================================================

@app.route('/budget/api/departments', methods=['GET'])
@login_required
@officer_required
def api_get_depts():
    conn = get_db()
    depts = fetchall(conn, '''
        SELECT d.dept_id, d.name, d.description, d.is_active, d.created_at,
               COALESCE(SUM(i.allocated), 0) as total_allocated
        FROM budget_departments d
        LEFT JOIN budget_items i ON i.dept_id = d.dept_id AND i.is_active = true
        GROUP BY d.dept_id, d.name, d.description, d.is_active, d.created_at
        ORDER BY d.name
    ''')
    conn.close()
    return jsonify(ser(depts))

@app.route('/budget/api/departments', methods=['POST'])
@login_required
@admin_required
def api_create_dept():
    data = request.json or {}
    name = sanitize_text(data.get('name'))
    if not name:
        return jsonify({'error': 'Name is required'}), 400
    conn = get_db()
    try:
        execute(conn, "INSERT INTO budget_departments (name, description, created_by) VALUES (?,?,?)",
                (name, sanitize_text(data.get('description', '')), session['user_id']))
        conn.commit()
    except Exception as e:
        conn.close()
        return jsonify({'error': 'Department name already exists'}), 400
    conn.close()
    return jsonify({'success': True})

@app.route('/budget/api/departments/<int:did>', methods=['PUT'])
@login_required
@admin_required
def api_update_dept(did):
    data = request.json or {}
    fields, vals = [], []
    for f in ('name', 'description', 'is_active'):
        if f in data:
            val = sanitize_text(data[f]) if f in ('name', 'description') else data[f]
            fields.append(f"{f}=?"); vals.append(val)
    if not fields:
        return jsonify({'error': 'Nothing to update'}), 400
    vals.append(did)
    conn = get_db()
    execute(conn, f"UPDATE budget_departments SET {', '.join(fields)} WHERE dept_id=?", vals)
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/budget/api/departments/<int:did>', methods=['DELETE'])
@login_required
@admin_required
def api_delete_dept(did):
    conn = get_db()
    execute(conn, "UPDATE budget_departments SET is_active=false WHERE dept_id=?", (did,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

# ============================================================================
# BUDGET ITEMS
# ============================================================================

@app.route('/budget/api/departments/<int:did>/items', methods=['GET'])
@login_required
@officer_required
def api_get_items(did):
    conn = get_db()
    items = fetchall(conn, '''
        SELECT i.item_id, i.dept_id, i.name, i.allocated, i.is_active, i.created_at,
               COALESCE(SUM(CASE WHEN r.status = 'approved' THEN r.amount ELSE 0 END), 0) as spent,
               COALESCE(SUM(CASE WHEN r.status = 'pending'  THEN r.amount ELSE 0 END), 0) as pending_amount
        FROM budget_items i
        LEFT JOIN budget_requests r ON r.item_id = i.item_id
        WHERE i.dept_id = ? AND i.is_active = true
        GROUP BY i.item_id, i.dept_id, i.name, i.allocated, i.is_active, i.created_at
        ORDER BY i.name
    ''', (did,))
    conn.close()
    return jsonify(ser(items))

@app.route('/budget/api/departments/<int:did>/items', methods=['POST'])
@login_required
@admin_required
def api_create_item(did):
    data = request.json or {}
    name = sanitize_text(data.get('name'))
    try:
        allocated = float(data.get('allocated', 0))
    except:
        return jsonify({'error': 'Invalid amount'}), 400
    if not name:
        return jsonify({'error': 'Name is required'}), 400
    conn = get_db()
    execute(conn, "INSERT INTO budget_items (dept_id, name, allocated) VALUES (?,?,?)", (did, name, allocated))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/budget/api/items/<int:iid>', methods=['PUT'])
@login_required
@admin_required
def api_update_item(iid):
    data = request.json or {}
    fields, vals = [], []
    if 'name' in data:
        fields.append("name=?"); vals.append(sanitize_text(data['name']))
    if 'allocated' in data:
        try: fields.append("allocated=?"); vals.append(float(data['allocated']))
        except: pass
    if 'is_active' in data:
        fields.append("is_active=?"); vals.append(data['is_active'])
    if not fields:
        return jsonify({'error': 'Nothing to update'}), 400
    vals.append(iid)
    conn = get_db()
    execute(conn, f"UPDATE budget_items SET {', '.join(fields)} WHERE item_id=?", vals)
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/budget/api/items/<int:iid>', methods=['DELETE'])
@login_required
@admin_required
def api_delete_item(iid):
    conn = get_db()
    execute(conn, "UPDATE budget_items SET is_active=false WHERE item_id=?", (iid,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

# ============================================================================
# BUDGET REQUESTS
# ============================================================================

@app.route('/budget/api/requests', methods=['GET'])
@login_required
@officer_required
def api_get_requests():
    conn = get_db()
    role = session.get('role')
    if role in ('admin', 'moderator'):
        rows = fetchall(conn, '''
            SELECT r.request_id, r.item_id, i.name as item_name, i.dept_id,
                   d.name as dept_name, r.submitted_by,
                   u.username as submitter_name, r.amount, r.description,
                   r.vendor, r.status, r.created_at, r.reviewed_at,
                   r.rejection_reason,
                   ru.username as reviewer_name
            FROM budget_requests r
            JOIN budget_items i ON r.item_id = i.item_id
            JOIN budget_departments d ON i.dept_id = d.dept_id
            JOIN users u ON r.submitted_by = u.user_id
            LEFT JOIN users ru ON r.reviewed_by = ru.user_id
            ORDER BY r.created_at DESC
        ''')
    else:
        rows = fetchall(conn, '''
            SELECT r.request_id, r.item_id, i.name as item_name, i.dept_id,
                   d.name as dept_name, r.submitted_by,
                   u.username as submitter_name, r.amount, r.description,
                   r.vendor, r.status, r.created_at, r.reviewed_at,
                   r.rejection_reason,
                   ru.username as reviewer_name
            FROM budget_requests r
            JOIN budget_items i ON r.item_id = i.item_id
            JOIN budget_departments d ON i.dept_id = d.dept_id
            JOIN users u ON r.submitted_by = u.user_id
            LEFT JOIN users ru ON r.reviewed_by = ru.user_id
            WHERE r.submitted_by = ?
            ORDER BY r.created_at DESC
        ''', (session['user_id'],))
    conn.close()
    return jsonify(ser(rows))

@app.route('/budget/api/requests/pending', methods=['GET'])
@login_required
@officer_required
def api_pending_requests():
    conn = get_db()
    rows = fetchall(conn, '''
        SELECT r.request_id, r.item_id, i.name as item_name, i.dept_id,
               d.name as dept_name, r.submitted_by,
               u.username as submitter_name, r.amount, r.description,
               r.vendor, r.status, r.created_at,
               i.allocated,
               COALESCE(SUM(CASE WHEN r2.status='approved' THEN r2.amount ELSE 0 END),0) as item_spent
        FROM budget_requests r
        JOIN budget_items i ON r.item_id = i.item_id
        JOIN budget_departments d ON i.dept_id = d.dept_id
        JOIN users u ON r.submitted_by = u.user_id
        LEFT JOIN budget_requests r2 ON r2.item_id = r.item_id
        WHERE r.status = 'pending'
        GROUP BY r.request_id, r.item_id, i.name, i.dept_id, d.name,
                 r.submitted_by, u.username, r.amount, r.description,
                 r.vendor, r.status, r.created_at, i.allocated
        ORDER BY r.created_at ASC
    ''')
    conn.close()
    return jsonify(ser(rows))

@app.route('/budget/api/departments/<int:did>/requests', methods=['GET'])
@login_required
@officer_required
def api_dept_requests(did):
    conn = get_db()
    rows = fetchall(conn, '''
        SELECT r.request_id, r.item_id, i.name as item_name,
               u.username as submitter_name, r.amount, r.description,
               r.vendor, r.status, r.created_at, r.reviewed_at,
               r.rejection_reason, ru.username as reviewer_name
        FROM budget_requests r
        JOIN budget_items i ON r.item_id = i.item_id
        JOIN users u ON r.submitted_by = u.user_id
        LEFT JOIN users ru ON r.reviewed_by = ru.user_id
        WHERE i.dept_id = ?
        ORDER BY r.created_at DESC
    ''', (did,))
    conn.close()
    return jsonify(ser(rows))

@app.route('/budget/api/requests', methods=['POST'])
@login_required
@officer_required
def api_submit_request():
    data = request.json or {}
    item_id = data.get('item_id')
    description = sanitize_text(data.get('description'))
    vendor = sanitize_text(data.get('vendor'))
    try:
        amount = float(data.get('amount', 0))
    except:
        return jsonify({'error': 'Invalid amount'}), 400
    if not item_id or not description or amount <= 0:
        return jsonify({'error': 'item_id, description and a positive amount are required'}), 400
    conn = get_db()
    item = fetchone(conn, "SELECT item_id FROM budget_items WHERE item_id=? AND is_active=true", (item_id,))
    if not item:
        conn.close()
        return jsonify({'error': 'Budget item not found'}), 404
    execute(conn, "INSERT INTO budget_requests (item_id, submitted_by, amount, description, vendor) VALUES (?,?,?,?,?)",
            (item_id, session['user_id'], amount, description, vendor))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/budget/api/requests/<int:rid>/approve', methods=['POST'])
@login_required
@admin_required
def api_approve_request(rid):
    conn = get_db()
    req = fetchone(conn, "SELECT * FROM budget_requests WHERE request_id=? AND status='pending'", (rid,))
    if not req:
        conn.close()
        return jsonify({'error': 'Request not found or already reviewed'}), 404
    execute(conn, '''UPDATE budget_requests
        SET status='approved', reviewed_by=?, reviewed_at=CURRENT_TIMESTAMP
        WHERE request_id=?''', (session['user_id'], rid))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/budget/api/requests/<int:rid>/reject', methods=['POST'])
@login_required
@admin_required
def api_reject_request(rid):
    data = request.json or {}
    reason = sanitize_text(data.get('reason'))
    if not reason:
        return jsonify({'error': 'Reason is required'}), 400
    conn = get_db()
    execute(conn, '''UPDATE budget_requests
        SET status='rejected', reviewed_by=?, reviewed_at=CURRENT_TIMESTAMP, rejection_reason=?
        WHERE request_id=?''', (session['user_id'], reason, rid))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/budget/api/requests/<int:rid>/delete', methods=['POST'])
@login_required
@admin_required
def api_delete_request(rid):
    conn = get_db()
    req = fetchone(conn, "SELECT * FROM budget_requests WHERE request_id=? AND status='approved'", (rid,))
    if not req:
        conn.close()
        return jsonify({'error': 'Request not found or not approved'}), 404
    execute(conn, "DELETE FROM budget_requests WHERE request_id=?", (rid,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

# ============================================================================
# SUMMARY ENDPOINT  (overview cards)
# ============================================================================

@app.route('/budget/api/summary')
@login_required
@officer_required
def api_summary():
    conn = get_db()
    total_budget = fetchone(conn, "SELECT COALESCE(SUM(allocated),0) as v FROM budget_items WHERE is_active=true")
    total_spent  = fetchone(conn, "SELECT COALESCE(SUM(amount),0) as v FROM budget_requests WHERE status='approved'")
    total_pending_count = fetchone(conn, "SELECT COUNT(*) as v FROM budget_requests WHERE status='pending'")
    dept_count   = fetchone(conn, "SELECT COUNT(*) as v FROM budget_departments WHERE is_active=true")
    conn.close()
    return jsonify({
        'total_budget':  float(total_budget['v'] if total_budget else 0),
        'total_spent':   float(total_spent['v']  if total_spent  else 0),
        'pending_count': int(total_pending_count['v'] if total_pending_count else 0),
        'dept_count':    int(dept_count['v'] if dept_count else 0),
    })


# ============================================================================
# CHAPTER STYLE
# ============================================================================

@app.route('/theme.css')
def theme_css():
    css = _theme_css(get_org_settings())
    return Response(css, mimetype='text/css', headers={'Cache-Control': 'no-cache'})

@app.route('/api/theme', methods=['GET'])
def api_theme_get():
    s = get_org_settings()
    return jsonify({
        'letters': s['letters'],
        'org_name': s['org_name'],
        'tagline': s['tagline'],
        'footer': s['footer'],
        'primary_color': s['primary_color'],
        'accent_color': s['accent_color'],
        'bg_color': s['bg_color'],
        'text_color': s['text_color'],
        'configured': bool(s['configured']),
    })

@app.route('/api/theme', methods=['POST'])
def api_theme_save():
    existing = get_org_settings()
    if existing['configured'] and session.get('role') != 'admin':
        return jsonify({'error': 'Forbidden'}), 403
    data = request.json or {}
    letters = _clean_brand_text(data.get('letters', ''), 32)
    org_name = _clean_brand_text(data.get('org_name', ''), 80)
    tagline = _clean_brand_text(data.get('tagline', ''), 120)
    footer = _clean_brand_text(data.get('footer', ''), 120)
    if not footer:
        footer = DEFAULT_THEME['footer']
    if not letters or not org_name or not tagline:
        return jsonify({'error': 'Letters, org name, and tagline are required'}), 400
    colors = {}
    for key in ('primary_color', 'accent_color', 'bg_color', 'text_color'):
        color, bad = _parse_hex_color(data.get(key, ''), key)
        if bad:
            return jsonify({'error': f'Invalid {bad}'}), 400
        colors[key] = color
    conn = get_db()
    if fetchone(conn, "SELECT id FROM org_settings WHERE id=1"):
        execute(conn, '''UPDATE org_settings SET
            letters=?, org_name=?, tagline=?, footer=?,
            primary_color=?, accent_color=?, bg_color=?, text_color=?,
            configured=1 WHERE id=1''',
            (letters, org_name, tagline, footer,
             colors['primary_color'], colors['accent_color'],
             colors['bg_color'], colors['text_color']))
    else:
        execute(conn, '''INSERT INTO org_settings
            (id, letters, org_name, tagline, footer, primary_color, accent_color, bg_color, text_color, configured)
            VALUES (?,?,?,?,?,?,?,?,?,1)''',
            (1, letters, org_name, tagline, footer,
             colors['primary_color'], colors['accent_color'],
             colors['bg_color'], colors['text_color']))
    conn.commit()
    conn.close()
    log_audit(session.get('user_id'), 'update_theme', org_name)
    return jsonify({'success': True})

@app.route('/setup')
def setup_page():
    if _is_configured() and session.get('role') != 'admin':
        return redirect('/')
    return _read_html('setup.html')


# ============================================================================
# PAGE ROUTES
# ============================================================================


def _read_html(name):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), name)
    with open(path) as f:
        html_text = f.read()
    s = get_org_settings()
    return (
        html_text
        .replace('__BRAND_LETTERS__', html_escape(s['letters']))
        .replace('__BRAND_NAME__', html_escape(s['org_name']))
        .replace('__BRAND_TAGLINE__', html_escape(s['tagline']))
        .replace('__BRAND_FOOTER__', html_escape(s['footer']))
    )

@app.route('/')
@setup_gate
def index():
    return _read_html('landing.html')

@app.route('/points')
def points_app():
    return _read_html('points.html')

@app.route('/budget')
@login_required
@officer_required
def budget_app_route():
    return _read_html('budget.html')

@app.route('/wheel')
def wheel_app():
    return _read_html('wheel.html')

@app.route('/wheel/api/members')
@login_required
def wheel_members():
    conn = get_db()
    users = fetchall(conn, "SELECT user_id, username FROM users WHERE is_active=true ORDER BY username")
    conn.close()
    return jsonify(users)


# ============================================================================
# DAILIES ROUTES
# ============================================================================

@app.route('/dailies')
def dailies_app():
    return _read_html('dailies.html')

@app.route('/dailies/api/tasks', methods=['GET'])
@login_required
def dailies_get_tasks():
    conn = get_db()
    tasks = fetchall(conn, "SELECT * FROM daily_tasks WHERE is_active=true ORDER BY category, title")
    conn.close()
    return jsonify(tasks)

@app.route('/dailies/api/tasks', methods=['POST'])
@login_required
@admin_required
def dailies_create_task():
    data = request.json or {}
    title = sanitize_text(data.get('title'))
    category = sanitize_text(data.get('category'))
    if not title or not category:
        return jsonify({'error': 'Title and category required'}), 400
    conn = get_db()
    execute(conn, "INSERT INTO daily_tasks (title, description, category, created_by) VALUES (?,?,?,?)",
            (title, sanitize_text(data.get('description', '')), category, session['user_id']))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/dailies/api/tasks/<int:tid>', methods=['PUT'])
@login_required
@admin_required
def dailies_update_task(tid):
    data = request.json or {}
    fields, vals = [], []
    for f in ('title', 'description', 'category', 'is_active'):
        if f in data:
            val = sanitize_text(data[f]) if f in ('title', 'description', 'category') else data[f]
            fields.append(f"{f}=?"); vals.append(val)
    if not fields:
        return jsonify({'error': 'Nothing to update'}), 400
    vals.append(tid)
    conn = get_db()
    execute(conn, "UPDATE daily_tasks SET " + ', '.join(fields) + " WHERE task_id=?", vals)
    conn.commit(); conn.close()
    return jsonify({'success': True})

@app.route('/dailies/api/rotation', methods=['GET'])
@login_required
def dailies_get_rotation():
    conn = get_db()
    rows = fetchall(conn, (
        "SELECT r.rotation_id, r.task_id, r.day_of_week, r.member_id, "
        "t.title, t.category, t.description as task_desc, u.username as member_name "
        "FROM rotation_template r "
        "JOIN daily_tasks t ON r.task_id = t.task_id "
        "JOIN users u ON r.member_id = u.user_id "
        "WHERE t.is_active=true "
        "ORDER BY t.category, t.title, r.day_of_week"
    ))
    conn.close()
    return jsonify(rows)

@app.route('/dailies/api/rotation', methods=['POST'])
@login_required
@admin_required
def dailies_set_rotation():
    data = request.json or {}
    entries = data.get('entries', [])
    conn = get_db()
    for e in entries:
        existing = fetchone(conn,
            "SELECT rotation_id FROM rotation_template WHERE task_id=? AND day_of_week=?",
            (e['task_id'], e['day_of_week']))
        if existing:
            execute(conn, "UPDATE rotation_template SET member_id=? WHERE rotation_id=?",
                    (e['member_id'], existing['rotation_id']))
        else:
            execute(conn, "INSERT INTO rotation_template (task_id, day_of_week, member_id) VALUES (?,?,?)",
                    (e['task_id'], e['day_of_week'], e['member_id']))
    conn.commit(); conn.close()
    return jsonify({'success': True})

@app.route('/dailies/api/rotation/<int:rid>', methods=['DELETE'])
@login_required
@admin_required
def dailies_delete_rotation(rid):
    conn = get_db()
    execute(conn, "DELETE FROM rotation_template WHERE rotation_id=?", (rid,))
    conn.commit(); conn.close()
    return jsonify({'success': True})

@app.route('/dailies/api/assignments', methods=['GET'])
@login_required
def dailies_get_assignments():
    conn = get_db()
    role = session.get('role')
    date_str = request.args.get('date','').strip()
    week_str = request.args.get('week','').strip()

    try:
        if date_str:
            dates = [datetime.date.fromisoformat(date_str)]
        elif week_str:
            monday = datetime.date.fromisoformat(week_str)
            dates = [monday + datetime.timedelta(days=i) for i in range(7)]
        else:
            raise ValueError("default to today's week")
    except ValueError:
        today = datetime.date.today()
        monday = today - datetime.timedelta(days=today.weekday())
        dates = [monday + datetime.timedelta(days=i) for i in range(7)]

    rotation = fetchall(conn, (
        "SELECT r.task_id, r.day_of_week, r.member_id, r.rotation_id, "
        "t.title, t.category, t.description as task_desc "
        "FROM rotation_template r "
        "JOIN daily_tasks t ON r.task_id = t.task_id "
        "WHERE t.is_active=true"
    ))

    results = []
    for day in dates:
        dow = day.isoweekday()
        for slot in [r for r in rotation if r['day_of_week'] == dow]:
            existing = fetchone(conn,
                "SELECT a.*, u.username as member_name, ap.username as approver_name "
                "FROM daily_assignments a "
                "JOIN users u ON a.member_id = u.user_id "
                "LEFT JOIN users ap ON a.approved_by = ap.user_id "
                "WHERE a.task_id=? AND a.due_date=?",
                (slot['task_id'], day.isoformat()))
            if existing:
                row = dict(existing)
                row['title'] = slot['title']
                row['category'] = slot['category']
                row['task_desc'] = slot['task_desc']
                row['due_date'] = day.isoformat()
            else:
                u = fetchone(conn, "SELECT username FROM users WHERE user_id=?", (slot['member_id'],))
                row = {
                    'assignment_id': None,
                    'task_id': slot['task_id'],
                    'member_id': slot['member_id'],
                    'due_date': day.isoformat(),
                    'status': 'pending',
                    'title': slot['title'],
                    'category': slot['category'],
                    'task_desc': slot['task_desc'],
                    'member_name': u['username'] if u else '?',
                    'approver_name': None,
                    'notes': '',
                    'completed_at': None,
                    'approved_at': None,
                }
            if role not in ('admin', 'moderator') and row.get('member_id') != session['user_id']:
                continue
            results.append(row)

    conn.close()
    return jsonify(ser(results))

@app.route('/dailies/api/assignments/complete-by-slot', methods=['POST'])
@login_required
def dailies_complete_by_slot():
    data = request.json or {}
    task_id = data.get('task_id')
    due_date = data.get('due_date')
    if not task_id or not due_date:
        return jsonify({'error': 'task_id and due_date required'}), 400

    day = datetime.date.fromisoformat(due_date)
    monday = day - datetime.timedelta(days=day.weekday())
    conn = get_db()

    slot = fetchone(conn, "SELECT member_id FROM rotation_template WHERE task_id=? AND day_of_week=?",
                    (task_id, day.isoweekday()))
    if not slot:
        conn.close()
        return jsonify({'error': 'No rotation slot found'}), 404
    if session.get('role') not in ('admin', 'moderator') and slot['member_id'] != session['user_id']:
        conn.close()
        return jsonify({'error': 'Not your assignment'}), 403

    existing = fetchone(conn, "SELECT assignment_id FROM daily_assignments WHERE task_id=? AND due_date=?",
                        (task_id, due_date))
    if not existing:
        execute(conn, "INSERT INTO daily_assignments (task_id, member_id, week_start, due_date) VALUES (?,?,?,?)",
                (task_id, slot['member_id'], monday.isoformat(), due_date))
        conn.commit()
        existing = fetchone(conn, "SELECT assignment_id FROM daily_assignments WHERE task_id=? AND due_date=?",
                            (task_id, due_date))

    execute(conn,
        "UPDATE daily_assignments SET status='submitted', completed_at=CURRENT_TIMESTAMP, notes=? WHERE assignment_id=?",
        (sanitize_text(data.get('notes', '')), existing['assignment_id']))
    conn.commit()
    conn.close()
    return jsonify({'success': True})
    

@app.route('/dailies/api/assignments/ensure', methods=['POST'])
@login_required
@admin_required
def dailies_ensure_assignments():
    data = request.json or {}
    date_str = data.get('date')
    if not date_str:
        return jsonify({'error': 'date required'}), 400
    day = datetime.date.fromisoformat(date_str)
    dow = day.isoweekday()
    monday = day - datetime.timedelta(days=day.weekday())
    conn = get_db()
    rotation = fetchall(conn, "SELECT * FROM rotation_template WHERE day_of_week=?", (dow,))
    created = 0
    for slot in rotation:
        existing = fetchone(conn,
            "SELECT assignment_id FROM daily_assignments WHERE task_id=? AND due_date=?",
            (slot['task_id'], date_str))
        if not existing:
            execute(conn, "INSERT INTO daily_assignments (task_id, member_id, week_start, due_date) VALUES (?,?,?,?)",
                    (slot['task_id'], slot['member_id'], monday.isoformat(), date_str))
            created += 1
    conn.commit(); conn.close()
    return jsonify({'success': True, 'created': created})

@app.route('/dailies/api/assignments/<int:aid>/complete', methods=['POST'])
@login_required
def dailies_mark_complete(aid):
    data = request.json or {}
    conn = get_db()
    if session.get('role') not in ('admin', 'moderator'):
        a = fetchone(conn, "SELECT member_id FROM daily_assignments WHERE assignment_id=?", (aid,))
        if not a or a['member_id'] != session['user_id']:
            conn.close()
            return jsonify({'error': 'Not your assignment'}), 403
    execute(conn,
        "UPDATE daily_assignments SET status='submitted', completed_at=CURRENT_TIMESTAMP, notes=? WHERE assignment_id=?",
        (sanitize_text(data.get('notes', '')), aid))
    conn.commit(); conn.close()
    return jsonify({'success': True})

@app.route('/dailies/api/assignments/<int:aid>/approve', methods=['POST'])
@login_required
@admin_required
def dailies_approve(aid):
    conn = get_db()
    cur = execute(conn,
        "UPDATE daily_assignments SET status='approved', approved_by=?, approved_at=CURRENT_TIMESTAMP WHERE assignment_id=? AND status='submitted'",
        (session['user_id'], aid))
    if cur.rowcount != 1:
        conn.rollback()
        conn.close()
        return jsonify({'error': 'Not found or already reviewed'}), 404
    conn.commit(); conn.close()
    return jsonify({'success': True})

@app.route('/dailies/api/assignments/<int:aid>/miss', methods=['POST'])
@login_required
@admin_required
def dailies_mark_missed(aid):
    data = request.json or {}
    penalty = abs(int(data.get('penalty', 1)))
    conn = get_db()
    a = fetchone(conn, "SELECT * FROM daily_assignments WHERE assignment_id=? AND status NOT IN ('missed','approved')", (aid,))
    if not a:
        conn.close()
        return jsonify({'error': 'Not found or already reviewed'}), 404
    cur = execute(conn,
        "UPDATE daily_assignments SET status='missed', approved_by=?, approved_at=CURRENT_TIMESTAMP WHERE assignment_id=? AND status NOT IN ('missed','approved')",
        (session['user_id'], aid))
    if cur.rowcount != 1:
        conn.rollback()
        conn.close()
        return jsonify({'error': 'Not found or already reviewed'}), 404
    task = fetchone(conn, "SELECT title FROM daily_tasks WHERE task_id=?", (a['task_id'],))
    if penalty > 0:
        title = sanitize_text(task['title'] if task else 'Unknown')
        execute(conn,
            "INSERT INTO transactions (member_id, points, description, status, reviewed_by, reviewed_at) VALUES (?,?,?,'approved',?,CURRENT_TIMESTAMP)",
            (a['member_id'], -penalty, "Missed Daily: " + title, session['username']))
        execute(conn, "UPDATE users SET brotherhood_points=brotherhood_points-? WHERE user_id=?",
                (penalty, a['member_id']))
    conn.commit(); conn.close()
    return jsonify({'success': True})

@app.route('/dailies/api/assignments/<int:aid>', methods=['DELETE'])
@login_required
@admin_required
def dailies_delete_assignment(aid):
    conn = get_db()
    execute(conn, "DELETE FROM daily_assignments WHERE assignment_id=?", (aid,))
    conn.commit(); conn.close()
    return jsonify({'success': True})

@app.route('/dailies/api/members')
@login_required
def dailies_get_members():
    conn = get_db()
    users = fetchall(conn, "SELECT user_id, username FROM users WHERE is_active=true ORDER BY username")
    conn.close()
    return jsonify(users)


init_db()

if __name__ == '__main__':
    print("\n" + "="*55)
    print("  Δ Τ Δ  Brotherhood Portal")
    print("="*55)
    print(f"  → Landing:      http://localhost:5000")
    print(f"  → Points:       http://localhost:5000/points")
    print(f"  → Budget:       http://localhost:5000/budget")
    print(f"  → Wheel:        http://localhost:5000/wheel")
    print(f"  → Dailies:      http://localhost:5000/dailies")
    print(f"  → Setup:        http://localhost:5000/setup")
    print(f"  → Default login: admin / admin123")
    print(f"  → DB: {'PostgreSQL' if DATABASE_URL else 'SQLite (local)'}")
    print("="*55 + "\n")
    # python app.py is local-only; Railway uses gunicorn (Procfile)
    app.run(debug=not DATABASE_URL, host='127.0.0.1', port=int(os.environ.get('PORT', 5000)))
