#!/usr/bin/env python3
"""
Δ Τ Δ - Delta Tau Delta Brotherhood Points System
Modern Web App - Railway Edition (PostgreSQL)
Local:   pip install flask psycopg2-binary && python brotherhood_app.py
Railway: connects automatically via DATABASE_URL env var
"""

from flask import Flask, request, jsonify, session
import hashlib
import os
from functools import wraps

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
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24))

# ============================================================================
# DATABASE
# ============================================================================

def get_db():
    if DATABASE_URL:
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = False
        return conn
    else:
        conn = sqlite3.connect('brotherhood_system.db')
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
        execute(conn, '''CREATE TABLE IF NOT EXISTS audit_log (
            log_id SERIAL PRIMARY KEY,
            action TEXT NOT NULL,
            user_id INTEGER,
            details TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
        execute(conn, '''CREATE TABLE IF NOT EXISTS audit_log (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL,
            user_id INTEGER,
            details TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')

    conn.commit()
    # Seed default admin if no users exist
    row = fetchone(conn, "SELECT COUNT(*) as cnt FROM users")
    cnt = row['cnt'] if row else 0
    if cnt == 0:
        pw = hash_pw("admin123")
        execute(conn, "INSERT INTO users (username, password_hash, email, role) VALUES (?,?,?,?)",
                ("admin", pw, "admin@brotherhood.com", "admin"))
        conn.commit()
    conn.close()

def hash_pw(pw): return hashlib.sha256(pw.encode()).hexdigest()

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

# ============================================================================
# AUTH DECORATORS
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

# ============================================================================
# API ROUTES
# ============================================================================

@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.json
    conn = get_db()
    user = fetchone(conn, "SELECT * FROM users WHERE username=? AND is_active=true", (data.get('username'),))
    conn.close()
    if user and user['password_hash'] == hash_pw(data.get('password', '')):
        session['user_id'] = user['user_id']
        session['username'] = user['username']
        session['role'] = user['role']
        log_audit(user['user_id'], 'LOGIN', f"User {user['username']} logged in")
        return jsonify({'success': True, 'role': user['role'], 'username': user['username']})
    return jsonify({'error': 'Invalid credentials'}), 401

@app.route('/api/logout', methods=['POST'])
def api_logout():
    log_audit(session.get('user_id'), 'LOGOUT', f"User {session.get('username')} logged out")
    session.clear()
    return jsonify({'success': True})

@app.route('/api/me')
def api_me():
    if 'user_id' not in session:
        return jsonify({'authenticated': False})
    conn = get_db()
    user = fetchone(conn, "SELECT user_id, username, email, role, brotherhood_points FROM users WHERE user_id=?", (session['user_id'],))
    conn.close()
    if user:
        return jsonify({'authenticated': True, **dict(user)})
    return jsonify({'authenticated': False})

# Users
@app.route('/api/users', methods=['GET'])
@login_required
def api_get_users():
    conn = get_db()
    users = fetchall(conn, "SELECT user_id, username, email, role, brotherhood_points, is_active, created_at FROM users ORDER BY brotherhood_points DESC")
    conn.close()
    return jsonify(users)

@app.route('/api/users', methods=['POST'])
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

@app.route('/api/users/<int:uid>', methods=['PUT'])
@login_required
@admin_required
def api_update_user(uid):
    data = request.json
    fields, vals = [], []
    for f in ('username', 'email', 'role', 'is_active'):
        if f in data:
            fields.append(f"{f}=?")
            vals.append(data[f])
    if 'password' in data and data['password']:
        fields.append("password_hash=?")
        vals.append(hash_pw(data['password']))
    if not fields:
        return jsonify({'error': 'No fields to update'}), 400
    vals.append(uid)
    try:
        conn = get_db()
        execute(conn, f"UPDATE users SET {', '.join(fields)} WHERE user_id=?", vals)
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        if is_integrity_error(e):
            return jsonify({'error': 'Username or email already exists'}), 400
        raise

@app.route('/api/users/<int:uid>', methods=['DELETE'])
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
@app.route('/api/transactions', methods=['GET'])
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

@app.route('/api/transactions/pending', methods=['GET'])
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

@app.route('/api/transactions', methods=['POST'])
@login_required
def api_submit_transaction():
    data = request.json
    conn = get_db()
    execute(conn, "INSERT INTO transactions (member_id, points, description) VALUES (?,?,?)",
            (session['user_id'], data['points'], data['description']))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/transactions/<int:tid>/approve', methods=['POST'])
@login_required
@moderator_required
def api_approve(tid):
    conn = get_db()
    row = fetchone(conn, "SELECT member_id, points FROM transactions WHERE transaction_id=?", (tid,))
    if not row:
        conn.close()
        return jsonify({'error': 'Not found'}), 404
    execute(conn, "UPDATE transactions SET status='approved', reviewed_by=?, reviewed_at=CURRENT_TIMESTAMP WHERE transaction_id=?",
            (session['username'], tid))
    execute(conn, "UPDATE users SET brotherhood_points=brotherhood_points+? WHERE user_id=?", (row['points'], row['member_id']))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/transactions/<int:tid>/reject', methods=['POST'])
@login_required
@moderator_required
def api_reject(tid):
    data = request.json
    conn = get_db()
    execute(conn, "UPDATE transactions SET status='rejected', reviewed_by=?, reviewed_at=CURRENT_TIMESTAMP, rejection_reason=? WHERE transaction_id=?",
            (session['username'], data.get('reason', ''), tid))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

# ============================================================================
# MAIN HTML PAGE
# ============================================================================

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Δ Τ Δ Brotherhood Points</title>
<link href="https://fonts.googleapis.com/css2?family=Cinzel+Decorative:wght@700;900&family=Cinzel:wght@400;600;700&family=Crimson+Pro:ital,wght@0,300;0,400;0,600;1,300;1,400&display=swap" rel="stylesheet">
<style>
  :root {
    --purple: #3D0C45;
    --purple-mid: #5C1F6B;
    --purple-light: #7B3094;
    --gold: #C9A84C;
    --gold-bright: #E8C96A;
    --gold-dim: #8A7235;
    --dark: #0D0910;
    --dark-2: #150D1A;
    --dark-3: #1E1227;
    --dark-4: #261630;
    --surface: #1A0F21;
    --surface-2: #231428;
    --border: rgba(201,168,76,0.18);
    --border-strong: rgba(201,168,76,0.38);
    --text: #F0E8D0;
    --text-dim: #9A8E7A;
    --text-muted: #5C5248;
    --green: #4CAF7A;
    --red: #CF4A4A;
    --pending: #C9A84C;
    --radius: 4px;
    --radius-lg: 8px;
  }

  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    background: var(--dark);
    color: var(--text);
    font-family: 'Crimson Pro', Georgia, serif;
    font-size: 16px;
    line-height: 1.6;
    min-height: 100vh;
    overflow-x: hidden;
  }

  /* Noise texture overlay */
  body::before {
    content: '';
    position: fixed;
    inset: 0;
    background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)' opacity='0.04'/%3E%3C/svg%3E");
    pointer-events: none;
    z-index: 0;
    opacity: 0.6;
  }

  /* ---- SCROLLBAR ---- */
  ::-webkit-scrollbar { width: 6px; }
  ::-webkit-scrollbar-track { background: var(--dark-2); }
  ::-webkit-scrollbar-thumb { background: var(--purple-mid); border-radius: 3px; }

  /* ---- LAYOUT ---- */
  #app { position: relative; z-index: 1; }

  /* ---- LOGIN ---- */
  #login-screen {
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 100vh;
    padding: 2rem;
    background: radial-gradient(ellipse at 50% 0%, rgba(92,31,107,0.4) 0%, transparent 70%),
                radial-gradient(ellipse at 80% 100%, rgba(61,12,69,0.3) 0%, transparent 60%);
  }

  .login-card {
    width: 100%;
    max-width: 420px;
    background: var(--surface);
    border: 1px solid var(--border-strong);
    padding: 3rem 2.5rem;
    position: relative;
    box-shadow: 0 0 80px rgba(92,31,107,0.3), 0 0 0 1px rgba(201,168,76,0.08);
  }

  .login-card::before, .login-card::after {
    content: '';
    position: absolute;
    width: 24px; height: 24px;
    border-color: var(--gold);
    border-style: solid;
  }
  .login-card::before { top: -1px; left: -1px; border-width: 2px 0 0 2px; }
  .login-card::after { bottom: -1px; right: -1px; border-width: 0 2px 2px 0; }

  .crest {
    text-align: center;
    margin-bottom: 2rem;
  }
  .crest-symbol {
    font-family: 'Cinzel Decorative', serif;
    font-size: 3.5rem;
    color: var(--gold);
    display: block;
    line-height: 1;
    text-shadow: 0 0 40px rgba(201,168,76,0.4);
    letter-spacing: 0.1em;
  }
  .crest-name {
    font-family: 'Cinzel', serif;
    font-size: 0.75rem;
    letter-spacing: 0.35em;
    color: var(--gold-dim);
    text-transform: uppercase;
    margin-top: 0.5rem;
  }
  .crest-sub {
    font-family: 'Crimson Pro', serif;
    font-style: italic;
    font-size: 1rem;
    color: var(--text-dim);
    margin-top: 0.3rem;
  }

  .form-group { margin-bottom: 1.25rem; }
  .form-label {
    display: block;
    font-family: 'Cinzel', serif;
    font-size: 0.65rem;
    letter-spacing: 0.2em;
    color: var(--gold-dim);
    text-transform: uppercase;
    margin-bottom: 0.5rem;
  }
  .form-input {
    width: 100%;
    background: var(--dark-3);
    border: 1px solid var(--border);
    color: var(--text);
    padding: 0.75rem 1rem;
    font-family: 'Crimson Pro', serif;
    font-size: 1rem;
    outline: none;
    border-radius: var(--radius);
    transition: border-color 0.2s, box-shadow 0.2s;
  }
  .form-input:focus {
    border-color: var(--gold);
    box-shadow: 0 0 0 2px rgba(201,168,76,0.12);
  }
  .form-input::placeholder { color: var(--text-muted); }
  select.form-input option { background: var(--dark-3); }

  .btn {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.75rem 1.5rem;
    font-family: 'Cinzel', serif;
    font-size: 0.7rem;
    letter-spacing: 0.15em;
    text-transform: uppercase;
    cursor: pointer;
    border: none;
    border-radius: var(--radius);
    transition: all 0.2s;
    font-weight: 600;
  }
  .btn-primary {
    background: linear-gradient(135deg, var(--purple-mid), var(--purple));
    color: var(--gold);
    border: 1px solid var(--border-strong);
    width: 100%;
    justify-content: center;
    padding: 0.9rem;
  }
  .btn-primary:hover {
    background: linear-gradient(135deg, var(--purple-light), var(--purple-mid));
    box-shadow: 0 4px 20px rgba(92,31,107,0.5);
  }
  .btn-sm {
    padding: 0.4rem 0.9rem;
    font-size: 0.6rem;
  }
  .btn-ghost {
    background: transparent;
    color: var(--text-dim);
    border: 1px solid var(--border);
  }
  .btn-ghost:hover { border-color: var(--gold); color: var(--gold); }
  .btn-danger { background: rgba(207,74,74,0.15); color: var(--red); border: 1px solid rgba(207,74,74,0.3); }
  .btn-danger:hover { background: rgba(207,74,74,0.25); }
  .btn-success { background: rgba(76,175,122,0.15); color: var(--green); border: 1px solid rgba(76,175,122,0.3); }
  .btn-success:hover { background: rgba(76,175,122,0.25); }
  .btn-gold { background: linear-gradient(135deg, var(--gold), var(--gold-dim)); color: var(--dark); border: none; }
  .btn-gold:hover { filter: brightness(1.1); }

  .error-msg {
    color: var(--red);
    font-size: 0.875rem;
    margin-top: 0.5rem;
    display: none;
    font-style: italic;
  }

  /* ---- MAIN APP ---- */
  #main-app { display: none; flex-direction: column; min-height: 100vh; }

  /* TOPBAR */
  .topbar {
    background: linear-gradient(180deg, var(--purple) 0%, var(--dark-2) 100%);
    border-bottom: 1px solid var(--border-strong);
    padding: 0 2rem;
    height: 60px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    position: sticky;
    top: 0;
    z-index: 100;
    box-shadow: 0 2px 20px rgba(0,0,0,0.4);
  }
  .topbar-brand {
    display: flex;
    align-items: center;
    gap: 1rem;
  }
  .topbar-symbol {
    font-family: 'Cinzel Decorative', serif;
    font-size: 1.4rem;
    color: var(--gold);
    text-shadow: 0 0 20px rgba(201,168,76,0.5);
  }
  .topbar-title {
    font-family: 'Cinzel', serif;
    font-size: 0.7rem;
    letter-spacing: 0.25em;
    color: var(--gold-dim);
    text-transform: uppercase;
  }
  .topbar-user {
    display: flex;
    align-items: center;
    gap: 1rem;
    font-size: 0.875rem;
  }
  .user-badge {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    background: rgba(201,168,76,0.08);
    border: 1px solid var(--border);
    padding: 0.35rem 0.9rem;
    border-radius: 20px;
  }
  .user-name { font-family: 'Cinzel', serif; font-size: 0.7rem; color: var(--gold); letter-spacing: 0.1em; }
  .role-tag {
    font-size: 0.6rem;
    letter-spacing: 0.15em;
    text-transform: uppercase;
    padding: 0.15rem 0.5rem;
    border-radius: 20px;
    font-family: 'Cinzel', serif;
  }
  .role-admin { background: rgba(201,168,76,0.2); color: var(--gold); border: 1px solid var(--gold-dim); }
  .role-moderator { background: rgba(92,31,107,0.4); color: #C084D0; border: 1px solid var(--purple-light); }
  .role-member { background: rgba(255,255,255,0.06); color: var(--text-dim); border: 1px solid var(--border); }

  /* LAYOUT */
  .app-body { display: flex; flex: 1; }

  /* SIDEBAR */
  .sidebar {
    width: 220px;
    background: var(--dark-2);
    border-right: 1px solid var(--border);
    padding: 1.5rem 0;
    flex-shrink: 0;
    position: sticky;
    top: 60px;
    height: calc(100vh - 60px);
    overflow-y: auto;
  }
  .nav-section-title {
    font-family: 'Cinzel', serif;
    font-size: 0.55rem;
    letter-spacing: 0.3em;
    color: var(--text-muted);
    text-transform: uppercase;
    padding: 0 1.5rem;
    margin-bottom: 0.5rem;
    margin-top: 1.5rem;
  }
  .nav-item {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.65rem 1.5rem;
    cursor: pointer;
    transition: all 0.15s;
    color: var(--text-dim);
    font-size: 0.9rem;
    border-left: 3px solid transparent;
    position: relative;
  }
  .nav-item:hover { background: rgba(201,168,76,0.05); color: var(--text); }
  .nav-item.active {
    color: var(--gold);
    background: rgba(201,168,76,0.08);
    border-left-color: var(--gold);
  }
  .nav-item .icon { font-size: 1rem; width: 20px; text-align: center; }
  .nav-badge {
    margin-left: auto;
    background: var(--red);
    color: white;
    font-size: 0.6rem;
    font-family: 'Cinzel', serif;
    padding: 0.1rem 0.4rem;
    border-radius: 10px;
    min-width: 18px;
    text-align: center;
  }
  .nav-divider { height: 1px; background: var(--border); margin: 1rem 1.5rem; }

  /* CONTENT */
  .content { flex: 1; padding: 2rem; overflow-x: auto; }

  /* PAGE HEADER */
  .page-header {
    margin-bottom: 2rem;
    padding-bottom: 1.25rem;
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    gap: 1rem;
    flex-wrap: wrap;
  }
  .page-title {
    font-family: 'Cinzel', serif;
    font-size: 1.5rem;
    color: var(--gold);
    letter-spacing: 0.05em;
  }
  .page-subtitle { font-style: italic; color: var(--text-dim); font-size: 0.875rem; margin-top: 0.25rem; }

  /* CARDS */
  .card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    padding: 1.5rem;
    margin-bottom: 1.5rem;
  }
  .card-title {
    font-family: 'Cinzel', serif;
    font-size: 0.8rem;
    letter-spacing: 0.15em;
    color: var(--gold-dim);
    text-transform: uppercase;
    margin-bottom: 1.25rem;
    padding-bottom: 0.75rem;
    border-bottom: 1px solid var(--border);
  }

  /* STATS ROW */
  .stats-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 1rem; margin-bottom: 2rem; }
  .stat-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    padding: 1.25rem 1.5rem;
    position: relative;
    overflow: hidden;
  }
  .stat-card::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 2px;
    background: linear-gradient(90deg, var(--gold-dim), var(--gold));
  }
  .stat-label { font-family: 'Cinzel', serif; font-size: 0.6rem; letter-spacing: 0.2em; color: var(--text-muted); text-transform: uppercase; }
  .stat-value { font-family: 'Cinzel Decorative', serif; font-size: 2rem; color: var(--gold); line-height: 1.2; margin: 0.3rem 0; }
  .stat-sub { font-size: 0.8rem; color: var(--text-dim); font-style: italic; }

  /* TABLE */
  .table-wrap { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
  thead tr { border-bottom: 1px solid var(--border-strong); }
  th {
    font-family: 'Cinzel', serif;
    font-size: 0.6rem;
    letter-spacing: 0.18em;
    color: var(--gold-dim);
    text-transform: uppercase;
    padding: 0.75rem 1rem;
    text-align: left;
    font-weight: 600;
    white-space: nowrap;
  }
  td { padding: 0.75rem 1rem; border-bottom: 1px solid var(--border); color: var(--text); vertical-align: middle; }
  tr:last-child td { border-bottom: none; }
  tbody tr { transition: background 0.15s; }
  tbody tr:hover { background: rgba(201,168,76,0.04); }

  /* BADGES */
  .badge {
    display: inline-block;
    padding: 0.2rem 0.6rem;
    border-radius: 20px;
    font-size: 0.65rem;
    font-family: 'Cinzel', serif;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    font-weight: 600;
  }
  .badge-pending { background: rgba(201,168,76,0.15); color: var(--gold); border: 1px solid rgba(201,168,76,0.3); }
  .badge-approved { background: rgba(76,175,122,0.15); color: var(--green); border: 1px solid rgba(76,175,122,0.3); }
  .badge-rejected { background: rgba(207,74,74,0.15); color: var(--red); border: 1px solid rgba(207,74,74,0.3); }
  .badge-admin { background: rgba(201,168,76,0.15); color: var(--gold); border: 1px solid rgba(201,168,76,0.25); }
  .badge-moderator { background: rgba(192,132,208,0.15); color: #C084D0; border: 1px solid rgba(192,132,208,0.25); }
  .badge-member { background: rgba(255,255,255,0.06); color: var(--text-dim); border: 1px solid var(--border); }
  .badge-active { background: rgba(76,175,122,0.1); color: var(--green); border: 1px solid rgba(76,175,122,0.2); }
  .badge-inactive { background: rgba(207,74,74,0.1); color: var(--red); border: 1px solid rgba(207,74,74,0.2); }

  /* POINTS */
  .points-num { font-family: 'Cinzel', serif; color: var(--gold); font-size: 0.95rem; }

  /* RANK */
  .rank-1 { color: var(--gold); font-weight: bold; }
  .rank-2 { color: #C0C0C0; }
  .rank-3 { color: #CD7F32; }
  .rank-medal { font-size: 1.1rem; }

  /* LEADERBOARD TOP 3 */
  .podium { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 1rem; margin-bottom: 2rem; }
  .podium-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    padding: 1.5rem;
    text-align: center;
    position: relative;
    overflow: hidden;
  }
  .podium-card.first {
    background: linear-gradient(180deg, rgba(201,168,76,0.12) 0%, var(--surface) 60%);
    border-color: var(--gold-dim);
    transform: translateY(-8px);
  }
  .podium-card.second { background: linear-gradient(180deg, rgba(192,192,192,0.08) 0%, var(--surface) 60%); }
  .podium-card.third { background: linear-gradient(180deg, rgba(205,127,50,0.08) 0%, var(--surface) 60%); }
  .podium-rank { font-family: 'Cinzel Decorative', serif; font-size: 2rem; margin-bottom: 0.5rem; }
  .first .podium-rank { color: var(--gold); }
  .second .podium-rank { color: #C0C0C0; }
  .third .podium-rank { color: #CD7F32; }
  .podium-name { font-family: 'Cinzel', serif; font-size: 0.9rem; letter-spacing: 0.1em; color: var(--text); }
  .podium-pts { font-family: 'Cinzel Decorative', serif; font-size: 1.5rem; color: var(--gold); margin-top: 0.5rem; }
  .podium-pts-label { font-size: 0.7rem; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.15em; }

  /* MODAL */
  .modal-overlay {
    position: fixed;
    inset: 0;
    background: rgba(0,0,0,0.7);
    backdrop-filter: blur(4px);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 200;
    padding: 1rem;
    opacity: 0;
    pointer-events: none;
    transition: opacity 0.2s;
  }
  .modal-overlay.show { opacity: 1; pointer-events: all; }
  .modal {
    background: var(--surface);
    border: 1px solid var(--border-strong);
    border-radius: var(--radius-lg);
    width: 100%;
    max-width: 480px;
    max-height: 90vh;
    overflow-y: auto;
    transform: translateY(20px);
    transition: transform 0.2s;
    position: relative;
  }
  .modal-overlay.show .modal { transform: translateY(0); }
  .modal-header {
    background: linear-gradient(135deg, var(--purple) 0%, var(--dark-2) 100%);
    padding: 1.25rem 1.5rem;
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  .modal-title { font-family: 'Cinzel', serif; font-size: 0.85rem; letter-spacing: 0.15em; color: var(--gold); text-transform: uppercase; }
  .modal-close { background: none; border: none; color: var(--text-dim); font-size: 1.2rem; cursor: pointer; padding: 0.25rem; }
  .modal-close:hover { color: var(--text); }
  .modal-body { padding: 1.5rem; }
  .modal-footer { padding: 1rem 1.5rem; border-top: 1px solid var(--border); display: flex; gap: 0.75rem; justify-content: flex-end; }

  /* TOAST */
  #toast-container { position: fixed; top: 1rem; right: 1rem; z-index: 9999; display: flex; flex-direction: column; gap: 0.5rem; }
  .toast {
    background: var(--surface);
    border: 1px solid var(--border);
    padding: 0.8rem 1.2rem;
    border-radius: var(--radius);
    font-size: 0.875rem;
    display: flex;
    align-items: center;
    gap: 0.75rem;
    min-width: 280px;
    box-shadow: 0 4px 20px rgba(0,0,0,0.4);
    animation: slideIn 0.3s ease;
  }
  .toast.success { border-left: 3px solid var(--green); }
  .toast.error { border-left: 3px solid var(--red); }
  .toast.info { border-left: 3px solid var(--gold); }
  @keyframes slideIn { from { transform: translateX(100%); opacity: 0; } to { transform: none; opacity: 1; } }

  /* SEARCH */
  .search-bar {
    display: flex;
    gap: 0.75rem;
    margin-bottom: 1rem;
    flex-wrap: wrap;
    align-items: center;
  }
  .search-input {
    background: var(--dark-3);
    border: 1px solid var(--border);
    color: var(--text);
    padding: 0.5rem 1rem;
    font-family: 'Crimson Pro', serif;
    font-size: 0.9rem;
    outline: none;
    border-radius: var(--radius);
    min-width: 220px;
    transition: border-color 0.2s;
  }
  .search-input:focus { border-color: var(--gold-dim); }
  .search-input::placeholder { color: var(--text-muted); }

  /* EMPTY STATE */
  .empty-state { text-align: center; padding: 3rem; color: var(--text-muted); }
  .empty-icon { font-size: 2.5rem; margin-bottom: 1rem; }
  .empty-text { font-style: italic; font-size: 1rem; }

  /* ACTION BTNS */
  .action-btns { display: flex; gap: 0.4rem; flex-wrap: wrap; }

  /* TEXTAREA */
  textarea.form-input { resize: vertical; min-height: 80px; }

  /* SECTION PAGES */
  .page { display: none; }
  .page.active { display: block; }

  /* POINTS SUBMIT */
  .submit-form { max-width: 560px; }

  /* UTILITY */
  .text-gold { color: var(--gold); }
  .text-dim { color: var(--text-dim); }
  .text-green { color: var(--green); }
  .text-red { color: var(--red); }
  .flex { display: flex; }
  .gap-2 { gap: 0.5rem; }
  .mt-1 { margin-top: 0.5rem; }
  .truncate { max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

  /* RESPONSIVE */
  @media (max-width: 768px) {
    .sidebar { display: none; }
    .content { padding: 1rem; }
    .podium { grid-template-columns: 1fr; }
    .stats-row { grid-template-columns: 1fr 1fr; }
  }
</style>
</head>
<body>
<div id="app">

<!-- LOGIN -->
<div id="login-screen">
  <div class="login-card">
    <div class="crest">
      <span class="crest-symbol">ΔΤΔ</span>
      <div class="crest-name">Delta Tau Delta</div>
      <div class="crest-sub">Brotherhood Points System</div>
    </div>
    <div class="form-group">
      <label class="form-label">Username</label>
      <input class="form-input" type="text" id="login-username" placeholder="Enter your username" autocomplete="username">
    </div>
    <div class="form-group">
      <label class="form-label">Password</label>
      <input class="form-input" type="password" id="login-password" placeholder="••••••••" autocomplete="current-password">
    </div>
    <div class="error-msg" id="login-error">Invalid credentials or inactive account.</div>
    <button class="btn btn-primary" id="login-btn" onclick="doLogin()">Sign In to Brotherhood</button>
  </div>
</div>

<!-- MAIN APP -->
<div id="main-app">
  <div class="topbar">
    <div class="topbar-brand">
      <span class="topbar-symbol">ΔΤΔ</span>
      <span class="topbar-title">Brotherhood Points</span>
    </div>
    <div class="topbar-user">
      <div class="user-badge">
        <span class="user-name" id="topbar-username"></span>
        <span class="role-tag" id="topbar-role"></span>
      </div>
      <button class="btn btn-ghost btn-sm" onclick="doLogout()">Sign Out</button>
    </div>
  </div>

  <div class="app-body">
    <nav class="sidebar">
      <div class="nav-section-title">Navigation</div>
      <div class="nav-item active" onclick="showPage('leaderboard', this)" id="nav-leaderboard">
        <span class="icon">🏆</span> Leaderboard
      </div>
      <div class="nav-item" onclick="showPage('submit', this)" id="nav-submit" style="display:none">
        <span class="icon">✦</span> Submit Points
      </div>
      <div class="nav-item" onclick="showPage('my-transactions', this)" id="nav-my-tx" style="display:none">
        <span class="icon">📋</span> My Requests
      </div>
      <div class="nav-divider"></div>
      <div class="nav-section-title" id="mod-section" style="display:none">Moderation</div>
      <div class="nav-item" onclick="showPage('pending', this)" id="nav-pending" style="display:none">
        <span class="icon">⏳</span> Pending
        <span class="nav-badge" id="pending-count" style="display:none">0</span>
      </div>
      <div class="nav-item" onclick="showPage('all-transactions', this)" id="nav-all-tx" style="display:none">
        <span class="icon">📜</span> All Transactions
      </div>
      <div class="nav-divider" id="admin-divider" style="display:none"></div>
      <div class="nav-section-title" id="admin-section" style="display:none">Admin</div>
      <div class="nav-item" onclick="showPage('users', this)" id="nav-users" style="display:none">
        <span class="icon">👥</span> User Management
      </div>
    </nav>

    <main class="content">
      <!-- Leaderboard -->
      <div class="page active" id="page-leaderboard">
        <div class="page-header">
          <div>
            <div class="page-title">Brotherhood Leaderboard</div>
            <div class="page-subtitle">Rankings by earned brotherhood points</div>
          </div>
          <button class="btn btn-ghost btn-sm" onclick="loadLeaderboard()">↻ Refresh</button>
        </div>
        <div class="podium" id="podium"></div>
        <div class="card">
          <div class="card-title">Full Rankings</div>
          <div class="table-wrap">
            <table>
              <thead>
                <tr><th>#</th><th>Member</th><th>Email</th><th>Role</th><th>Points</th><th>Status</th></tr>
              </thead>
              <tbody id="leaderboard-body"></tbody>
            </table>
          </div>
        </div>
      </div>

      <!-- Submit Points -->
      <div class="page" id="page-submit">
        <div class="page-header">
          <div>
            <div class="page-title">Submit Points Request</div>
            <div class="page-subtitle">Submit your brotherhood activities for review</div>
          </div>
        </div>
        <div class="card submit-form">
          <div class="card-title">New Request</div>
          <div class="form-group">
            <label class="form-label">Points Value</label>
            <input class="form-input" type="number" id="sub-points" min="1" max="1000" placeholder="e.g. 10">
          </div>
          <div class="form-group">
            <label class="form-label">Description / Activity</label>
            <textarea class="form-input" id="sub-desc" placeholder="Describe the activity you completed..."></textarea>
          </div>
          <button class="btn btn-gold" onclick="submitPoints()">✦ Submit for Review</button>
        </div>
      </div>

      <!-- My Transactions -->
      <div class="page" id="page-my-transactions">
        <div class="page-header">
          <div>
            <div class="page-title">My Requests</div>
            <div class="page-subtitle">Track your submitted point requests</div>
          </div>
          <button class="btn btn-ghost btn-sm" onclick="loadMyTransactions()">↻ Refresh</button>
        </div>
        <div class="card">
          <div class="table-wrap">
            <table>
              <thead>
                <tr><th>ID</th><th>Points</th><th>Description</th><th>Status</th><th>Submitted</th><th>Reviewer</th></tr>
              </thead>
              <tbody id="my-tx-body"></tbody>
            </table>
          </div>
        </div>
      </div>

      <!-- Pending Moderation -->
      <div class="page" id="page-pending">
        <div class="page-header">
          <div>
            <div class="page-title">Pending Requests</div>
            <div class="page-subtitle">Review and approve or reject submitted requests</div>
          </div>
          <button class="btn btn-ghost btn-sm" onclick="loadPending()">↻ Refresh</button>
        </div>
        <div class="card">
          <div class="table-wrap">
            <table>
              <thead>
                <tr><th>ID</th><th>Member</th><th>Points</th><th>Description</th><th>Submitted</th><th>Actions</th></tr>
              </thead>
              <tbody id="pending-body"></tbody>
            </table>
          </div>
        </div>
      </div>

      <!-- All Transactions -->
      <div class="page" id="page-all-transactions">
        <div class="page-header">
          <div>
            <div class="page-title">Transaction History</div>
            <div class="page-subtitle">Complete record of all point requests</div>
          </div>
          <button class="btn btn-ghost btn-sm" onclick="loadAllTransactions()">↻ Refresh</button>
        </div>
        <div class="card">
          <div class="search-bar">
            <input class="search-input" id="tx-search" placeholder="Search by member or description..." oninput="filterTransactions()">
          </div>
          <div class="table-wrap">
            <table>
              <thead>
                <tr><th>ID</th><th>Member</th><th>Points</th><th>Description</th><th>Status</th><th>Submitted</th><th>Reviewer</th></tr>
              </thead>
              <tbody id="all-tx-body"></tbody>
            </table>
          </div>
        </div>
      </div>

      <!-- User Management -->
      <div class="page" id="page-users">
        <div class="page-header">
          <div>
            <div class="page-title">User Management</div>
            <div class="page-subtitle">Manage brotherhood member accounts</div>
          </div>
          <button class="btn btn-gold btn-sm" onclick="openAddUser()">+ Add Member</button>
        </div>
        <div class="card">
          <div class="search-bar">
            <input class="search-input" id="user-search" placeholder="Search members..." oninput="filterUsers()">
          </div>
          <div class="table-wrap">
            <table>
              <thead>
                <tr><th>ID</th><th>Username</th><th>Email</th><th>Role</th><th>Points</th><th>Status</th><th>Joined</th><th>Actions</th></tr>
              </thead>
              <tbody id="users-body"></tbody>
            </table>
          </div>
        </div>
      </div>
    </main>
  </div>
</div>

<!-- TOAST CONTAINER -->
<div id="toast-container"></div>

<!-- ADD USER MODAL -->
<div class="modal-overlay" id="modal-add-user">
  <div class="modal">
    <div class="modal-header">
      <span class="modal-title">Add New Member</span>
      <button class="modal-close" onclick="closeModal('modal-add-user')">✕</button>
    </div>
    <div class="modal-body">
      <div class="form-group"><label class="form-label">Username</label><input class="form-input" id="add-username" placeholder="Username"></div>
      <div class="form-group"><label class="form-label">Email</label><input class="form-input" type="email" id="add-email" placeholder="email@example.com"></div>
      <div class="form-group"><label class="form-label">Password</label><input class="form-input" type="password" id="add-password" placeholder="Password"></div>
      <div class="form-group">
        <label class="form-label">Role</label>
        <select class="form-input" id="add-role">
          <option value="member">Member</option>
          <option value="moderator">Moderator</option>
          <option value="admin">Admin</option>
        </select>
      </div>
      <div class="error-msg" id="add-error"></div>
    </div>
    <div class="modal-footer">
      <button class="btn btn-ghost btn-sm" onclick="closeModal('modal-add-user')">Cancel</button>
      <button class="btn btn-gold btn-sm" onclick="createUser()">Create Member</button>
    </div>
  </div>
</div>

<!-- EDIT USER MODAL -->
<div class="modal-overlay" id="modal-edit-user">
  <div class="modal">
    <div class="modal-header">
      <span class="modal-title">Edit Member</span>
      <button class="modal-close" onclick="closeModal('modal-edit-user')">✕</button>
    </div>
    <div class="modal-body">
      <input type="hidden" id="edit-uid">
      <div class="form-group"><label class="form-label">Username</label><input class="form-input" id="edit-username" placeholder="Username"></div>
      <div class="form-group"><label class="form-label">Email</label><input class="form-input" type="email" id="edit-email"></div>
      <div class="form-group"><label class="form-label">New Password <span class="text-dim">(leave blank to keep)</span></label><input class="form-input" type="password" id="edit-password" placeholder="New password"></div>
      <div class="form-group">
        <label class="form-label">Role</label>
        <select class="form-input" id="edit-role">
          <option value="member">Member</option>
          <option value="moderator">Moderator</option>
          <option value="admin">Admin</option>
        </select>
      </div>
      <div class="form-group">
        <label class="form-label">Status</label>
        <select class="form-input" id="edit-active">
          <option value="1">Active</option>
          <option value="0">Inactive</option>
        </select>
      </div>
      <div class="error-msg" id="edit-error"></div>
    </div>
    <div class="modal-footer">
      <button class="btn btn-ghost btn-sm" onclick="closeModal('modal-edit-user')">Cancel</button>
      <button class="btn btn-gold btn-sm" onclick="saveUser()">Save Changes</button>
    </div>
  </div>
</div>

<!-- REJECT MODAL -->
<div class="modal-overlay" id="modal-reject">
  <div class="modal">
    <div class="modal-header">
      <span class="modal-title">Reject Request</span>
      <button class="modal-close" onclick="closeModal('modal-reject')">✕</button>
    </div>
    <div class="modal-body">
      <input type="hidden" id="reject-tid">
      <div class="form-group">
        <label class="form-label">Reason for Rejection</label>
        <textarea class="form-input" id="reject-reason" placeholder="Explain why this request is being rejected..."></textarea>
      </div>
    </div>
    <div class="modal-footer">
      <button class="btn btn-ghost btn-sm" onclick="closeModal('modal-reject')">Cancel</button>
      <button class="btn btn-danger btn-sm" onclick="confirmReject()">Reject Request</button>
    </div>
  </div>
</div>

<script>
let currentUser = null;
let allUsers = [];
let allTransactions = [];

// ---- UTILS ----
function toast(msg, type='info') {
  const c = document.getElementById('toast-container');
  const t = document.createElement('div');
  t.className = `toast ${type}`;
  const icons = {success:'✓', error:'✕', info:'ⓘ'};
  t.innerHTML = `<span>${icons[type]||'ⓘ'}</span><span>${msg}</span>`;
  c.appendChild(t);
  setTimeout(() => t.remove(), 3500);
}

function openModal(id) { document.getElementById(id).classList.add('show'); }
function closeModal(id) { document.getElementById(id).classList.remove('show'); }

function fmtDate(d) {
  if (!d) return '—';
  return new Date(d).toLocaleDateString('en-US', {month:'short', day:'numeric', year:'numeric'});
}

function roleBadge(role) {
  return `<span class="badge badge-${role}">${role}</span>`;
}
function statusBadge(s) {
  return `<span class="badge badge-${s}">${s}</span>`;
}

// ---- AUTH ----
async function doLogin() {
  const u = document.getElementById('login-username').value.trim();
  const p = document.getElementById('login-password').value;
  const err = document.getElementById('login-error');
  err.style.display = 'none';
  document.getElementById('login-btn').textContent = 'Signing in…';
  try {
    const r = await fetch('/api/login', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({username:u, password:p})});
    const d = await r.json();
    if (d.success) {
      await loadApp();
    } else {
      err.style.display = 'block';
      document.getElementById('login-btn').textContent = 'Sign In to Brotherhood';
    }
  } catch(e) {
    err.textContent = 'Connection error. Is the server running?';
    err.style.display = 'block';
    document.getElementById('login-btn').textContent = 'Sign In to Brotherhood';
  }
}

async function doLogout() {
  await fetch('/api/logout', {method:'POST'});
  currentUser = null;
  document.getElementById('main-app').style.display = 'none';
  document.getElementById('login-screen').style.display = 'flex';
  document.getElementById('login-password').value = '';
}

async function loadApp() {
  const r = await fetch('/api/me');
  const d = await r.json();
  if (!d.authenticated) { return; }
  currentUser = d;

  document.getElementById('login-screen').style.display = 'none';
  document.getElementById('main-app').style.display = 'flex';

  document.getElementById('topbar-username').textContent = d.username.toUpperCase();
  const rb = document.getElementById('topbar-role');
  rb.textContent = d.role;
  rb.className = `role-tag role-${d.role}`;

  const role = d.role;
  // Show/hide nav items
  const show = (id) => document.getElementById(id).style.display = 'flex';
  const hide = (id) => document.getElementById(id).style.display = 'none';

  if (role === 'member') {
    show('nav-submit'); show('nav-my-tx');
    hide('nav-pending'); hide('nav-all-tx'); hide('nav-users');
    hide('mod-section'); hide('admin-section'); hide('admin-divider');
  } else if (role === 'moderator') {
    show('nav-submit'); show('nav-my-tx');
    show('nav-pending'); show('nav-all-tx');
    document.getElementById('mod-section').style.display = 'block';
    hide('nav-users'); hide('admin-section'); hide('admin-divider');
  } else if (role === 'admin') {
    show('nav-submit'); show('nav-my-tx');
    show('nav-pending'); show('nav-all-tx');
    document.getElementById('mod-section').style.display = 'block';
    show('nav-users');
    document.getElementById('admin-section').style.display = 'block';
    document.getElementById('admin-divider').style.display = 'block';
  }

  showPage('leaderboard', document.getElementById('nav-leaderboard'));
  loadLeaderboard();
  if (role !== 'member') pollPending();
}

async function pollPending() {
  if (!currentUser || currentUser.role === 'member') return;
  try {
    const r = await fetch('/api/transactions/pending');
    const d = await r.json();
    const badge = document.getElementById('pending-count');
    if (d.length > 0) {
      badge.textContent = d.length;
      badge.style.display = 'inline';
    } else {
      badge.style.display = 'none';
    }
  } catch(e) {}
  setTimeout(pollPending, 30000);
}

// ---- NAV ----
function showPage(page, el) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  const pageEl = document.getElementById('page-' + page);
  if (pageEl) pageEl.classList.add('active');
  if (el) el.classList.add('active');

  // Load data for page
  if (page === 'leaderboard') loadLeaderboard();
  else if (page === 'submit') {}
  else if (page === 'my-transactions') loadMyTransactions();
  else if (page === 'pending') loadPending();
  else if (page === 'all-transactions') loadAllTransactions();
  else if (page === 'users') loadUsers();
}

// ---- LEADERBOARD ----
async function loadLeaderboard() {
  const r = await fetch('/api/users');
  const users = await r.json();
  const active = users.filter(u => u.is_active);

  // Podium
  const podium = document.getElementById('podium');
  const medals = ['🥇','🥈','🥉'];
  const classes = ['first','second','third'];
  const top3 = active.slice(0,3);
  // Reorder: 2nd, 1st, 3rd for podium effect
  const order = top3.length >= 3 ? [top3[1], top3[0], top3[2]] : top3.length === 2 ? [top3[1], top3[0]] : top3;
  const orderClasses = top3.length >= 3 ? ['second','first','third'] : top3.length === 2 ? ['second','first'] : ['first'];
  const orderMedals = top3.length >= 3 ? [medals[1],medals[0],medals[2]] : top3.length === 2 ? [medals[1],medals[0]] : medals;

  if (top3.length === 0) {
    podium.innerHTML = '';
  } else {
    podium.innerHTML = order.map((u, i) => `
      <div class="podium-card ${orderClasses[i]}">
        <div class="podium-rank">${orderMedals[i]}</div>
        <div class="podium-name">${u.username}</div>
        <div class="podium-pts">${u.brotherhood_points}</div>
        <div class="podium-pts-label">Points</div>
      </div>
    `).join('');
  }

  // Table
  const tbody = document.getElementById('leaderboard-body');
  if (active.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6"><div class="empty-state"><div class="empty-icon">🏆</div><div class="empty-text">No members yet</div></div></td></tr>`;
    return;
  }
  tbody.innerHTML = active.map((u, i) => `
    <tr>
      <td><span class="rank-${i+1}">${i < 3 ? ['🥇','🥈','🥉'][i] : '#' + (i+1)}</span></td>
      <td style="font-family:'Cinzel',serif;font-size:0.85rem;">${u.username}</td>
      <td class="text-dim" style="font-size:0.85rem;">${u.email}</td>
      <td>${roleBadge(u.role)}</td>
      <td><span class="points-num">${u.brotherhood_points}</span></td>
      <td>${u.is_active ? '<span class="badge badge-active">Active</span>' : '<span class="badge badge-inactive">Inactive</span>'}</td>
    </tr>
  `).join('');
}

// ---- SUBMIT POINTS ----
async function submitPoints() {
  const pts = parseInt(document.getElementById('sub-points').value);
  const desc = document.getElementById('sub-desc').value.trim();
  if (!pts || pts < 1) { toast('Enter a valid point value','error'); return; }
  if (!desc) { toast('Please provide a description','error'); return; }
  const r = await fetch('/api/transactions', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({points:pts, description:desc})});
  const d = await r.json();
  if (d.success) {
    toast('Request submitted for review!','success');
    document.getElementById('sub-points').value = '';
    document.getElementById('sub-desc').value = '';
  } else {
    toast(d.error || 'Error submitting request','error');
  }
}

// ---- MY TRANSACTIONS ----
async function loadMyTransactions() {
  const r = await fetch('/api/transactions');
  const txs = await r.json();
  const tbody = document.getElementById('my-tx-body');
  if (txs.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6"><div class="empty-state"><div class="empty-icon">📋</div><div class="empty-text">No requests submitted yet</div></div></td></tr>`;
    return;
  }
  tbody.innerHTML = txs.map(t => `
    <tr>
      <td class="text-dim">#${t.transaction_id}</td>
      <td><span class="points-num">+${t.points}</span></td>
      <td class="truncate" title="${t.description}">${t.description}</td>
      <td>${statusBadge(t.status)}</td>
      <td class="text-dim" style="font-size:0.8rem;">${fmtDate(t.created_at)}</td>
      <td class="text-dim" style="font-size:0.8rem;">${t.reviewed_by || '—'}</td>
    </tr>
  `).join('');
}

// ---- PENDING ----
async function loadPending() {
  const r = await fetch('/api/transactions/pending');
  const txs = await r.json();
  const badge = document.getElementById('pending-count');
  badge.textContent = txs.length;
  badge.style.display = txs.length > 0 ? 'inline' : 'none';

  const tbody = document.getElementById('pending-body');
  if (txs.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6"><div class="empty-state"><div class="empty-icon">✓</div><div class="empty-text">All caught up — no pending requests</div></div></td></tr>`;
    return;
  }
  tbody.innerHTML = txs.map(t => `
    <tr>
      <td class="text-dim">#${t.transaction_id}</td>
      <td style="font-family:'Cinzel',serif;font-size:0.85rem;">${t.member_name}</td>
      <td><span class="points-num">+${t.points}</span></td>
      <td class="truncate" title="${t.description}">${t.description}</td>
      <td class="text-dim" style="font-size:0.8rem;">${fmtDate(t.created_at)}</td>
      <td>
        <div class="action-btns">
          <button class="btn btn-success btn-sm" onclick="approveTransaction(${t.transaction_id})">✓ Approve</button>
          <button class="btn btn-danger btn-sm" onclick="openReject(${t.transaction_id})">✕ Reject</button>
        </div>
      </td>
    </tr>
  `).join('');
}

async function approveTransaction(tid) {
  const r = await fetch(`/api/transactions/${tid}/approve`, {method:'POST'});
  const d = await r.json();
  if (d.success) { toast('Transaction approved!','success'); loadPending(); loadLeaderboard(); }
  else toast(d.error||'Error','error');
}

function openReject(tid) {
  document.getElementById('reject-tid').value = tid;
  document.getElementById('reject-reason').value = '';
  openModal('modal-reject');
}
async function confirmReject() {
  const tid = document.getElementById('reject-tid').value;
  const reason = document.getElementById('reject-reason').value.trim();
  if (!reason) { toast('Please provide a reason','error'); return; }
  const r = await fetch(`/api/transactions/${tid}/reject`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({reason})});
  const d = await r.json();
  if (d.success) { toast('Request rejected','info'); closeModal('modal-reject'); loadPending(); }
  else toast(d.error||'Error','error');
}

// ---- ALL TRANSACTIONS ----
async function loadAllTransactions() {
  const r = await fetch('/api/transactions');
  allTransactions = await r.json();
  renderAllTransactions(allTransactions);
}
function renderAllTransactions(txs) {
  const tbody = document.getElementById('all-tx-body');
  if (txs.length === 0) {
    tbody.innerHTML = `<tr><td colspan="7"><div class="empty-state"><div class="empty-text">No transactions found</div></div></td></tr>`;
    return;
  }
  tbody.innerHTML = txs.map(t => `
    <tr>
      <td class="text-dim">#${t.transaction_id}</td>
      <td style="font-family:'Cinzel',serif;font-size:0.85rem;">${t.member_name}</td>
      <td><span class="points-num">+${t.points}</span></td>
      <td class="truncate" title="${t.description}">${t.description}</td>
      <td>${statusBadge(t.status)}</td>
      <td class="text-dim" style="font-size:0.8rem;">${fmtDate(t.created_at)}</td>
      <td class="text-dim" style="font-size:0.8rem;">${t.reviewed_by || '—'}</td>
    </tr>
  `).join('');
}
function filterTransactions() {
  const q = document.getElementById('tx-search').value.toLowerCase();
  renderAllTransactions(allTransactions.filter(t =>
    t.member_name.toLowerCase().includes(q) || t.description.toLowerCase().includes(q)
  ));
}

// ---- USERS ----
async function loadUsers() {
  const r = await fetch('/api/users');
  allUsers = await r.json();
  renderUsers(allUsers);
}
function renderUsers(users) {
  const tbody = document.getElementById('users-body');
  if (users.length === 0) {
    tbody.innerHTML = `<tr><td colspan="8"><div class="empty-state"><div class="empty-text">No users found</div></div></td></tr>`;
    return;
  }
  tbody.innerHTML = users.map(u => `
    <tr>
      <td class="text-dim">${u.user_id}</td>
      <td style="font-family:'Cinzel',serif;font-size:0.85rem;">${u.username}</td>
      <td class="text-dim" style="font-size:0.85rem;">${u.email}</td>
      <td>${roleBadge(u.role)}</td>
      <td><span class="points-num">${u.brotherhood_points}</span></td>
      <td>${u.is_active ? '<span class="badge badge-active">Active</span>' : '<span class="badge badge-inactive">Inactive</span>'}</td>
      <td class="text-dim" style="font-size:0.8rem;">${fmtDate(u.created_at)}</td>
      <td>
        <div class="action-btns">
          <button class="btn btn-ghost btn-sm" onclick="openEditUser(${u.user_id})">Edit</button>
          ${u.is_active ? `<button class="btn btn-danger btn-sm" onclick="deactivateUser(${u.user_id})">Deactivate</button>` : ''}
        </div>
      </td>
    </tr>
  `).join('');
}
function filterUsers() {
  const q = document.getElementById('user-search').value.toLowerCase();
  renderUsers(allUsers.filter(u => u.username.toLowerCase().includes(q) || u.email.toLowerCase().includes(q)));
}

function openAddUser() {
  ['add-username','add-email','add-password'].forEach(id => document.getElementById(id).value = '');
  document.getElementById('add-role').value = 'member';
  document.getElementById('add-error').style.display = 'none';
  openModal('modal-add-user');
}
async function createUser() {
  const data = {
    username: document.getElementById('add-username').value.trim(),
    email: document.getElementById('add-email').value.trim(),
    password: document.getElementById('add-password').value,
    role: document.getElementById('add-role').value
  };
  if (!data.username || !data.email || !data.password) { showErr('add-error','All fields are required'); return; }
  const r = await fetch('/api/users', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)});
  const d = await r.json();
  if (d.success) { toast('Member created!','success'); closeModal('modal-add-user'); loadUsers(); }
  else showErr('add-error', d.error||'Error creating user');
}

function openEditUser(uid) {
  const u = allUsers.find(x => x.user_id === uid);
  if (!u) return;
  document.getElementById('edit-uid').value = uid;
  document.getElementById('edit-username').value = u.username;
  document.getElementById('edit-email').value = u.email;
  document.getElementById('edit-password').value = '';
  document.getElementById('edit-role').value = u.role;
  document.getElementById('edit-active').value = u.is_active ? '1' : '0';
  document.getElementById('edit-error').style.display = 'none';
  openModal('modal-edit-user');
}
async function saveUser() {
  const uid = document.getElementById('edit-uid').value;
  const data = {
    username: document.getElementById('edit-username').value.trim(),
    email: document.getElementById('edit-email').value.trim(),
    role: document.getElementById('edit-role').value,
    is_active: parseInt(document.getElementById('edit-active').value),
    password: document.getElementById('edit-password').value
  };
  const r = await fetch(`/api/users/${uid}`, {method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)});
  const d = await r.json();
  if (d.success) { toast('Member updated!','success'); closeModal('modal-edit-user'); loadUsers(); }
  else showErr('edit-error', d.error||'Error saving user');
}

async function deactivateUser(uid) {
  if (!confirm('Deactivate this member?')) return;
  const r = await fetch(`/api/users/${uid}`, {method:'DELETE'});
  const d = await r.json();
  if (d.success) { toast('Member deactivated','info'); loadUsers(); }
  else toast('Error','error');
}

function showErr(id, msg) {
  const el = document.getElementById(id);
  el.textContent = msg;
  el.style.display = 'block';
}

// Enter key on login
document.getElementById('login-password').addEventListener('keydown', e => { if (e.key === 'Enter') doLogin(); });
document.getElementById('login-username').addEventListener('keydown', e => { if (e.key === 'Enter') doLogin(); });

// Close modals on overlay click
document.querySelectorAll('.modal-overlay').forEach(o => {
  o.addEventListener('click', e => { if (e.target === o) o.classList.remove('show'); });
});

// Check session on load
(async () => {
  const r = await fetch('/api/me');
  const d = await r.json();
  if (d.authenticated) {
    await loadApp();
  }
})();
</script>
</body>
</html>"""

@app.route('/')
def index():
    return HTML

# Init DB on startup (works for both gunicorn and direct python execution)
init_db()

if __name__ == '__main__':
    print("\n" + "="*55)
    print("  Δ Τ Δ  Delta Tau Delta Brotherhood Points System")
    print("="*55)
    print(f"  → Open: http://localhost:5000")
    print(f"  → Default login: admin / admin123")
    print(f"  → DB: PostgreSQL" if DATABASE_URL else "  → DB: SQLite (local)")
    print("="*55 + "\n")
    app.run(debug=False, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
