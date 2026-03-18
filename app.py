#!/usr/bin/env python3
"""
Δ Τ Δ - Brotherhood Portal (Combined App)
Points system + Budget system with shared login.
Local:   pip install flask psycopg2-binary && python app.py
Railway: set DATABASE_URL env var

Routes:
  /          → Landing page
  /points    → Brotherhood Points app
  /budget    → Budget & Bookkeeping app
"""

from flask import Flask, request, jsonify, session, redirect
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



def ser(rows):
    """Make datetime fields JSON-serialisable."""
    import datetime
    for r in rows:
        for k, v in r.items():
            if isinstance(v, (datetime.datetime, datetime.date)):
                r[k] = v.isoformat()
    return rows


app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24))

# ============================================================================
# SHARED AUTH DECORATORS
# ============================================================================

def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('role') != 'admin':
            return jsonify({'error': 'Forbidden'}), 403
        return f(*args, **kwargs)
    return decorated

def moderator_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('role') not in ('admin', 'moderator'):
            return jsonify({'error': 'Forbidden'}), 403
        return f(*args, **kwargs)
    return decorated

# Alias for budget app compatibility
mod_required = moderator_required

# ============================================================================
# SHARED AUTH ROUTES  (one login serves both apps)
# ============================================================================

@app.route('/api/login', methods=['POST'])
@app.route('/points/api/login', methods=['POST'])
@app.route('/budget/api/login', methods=['POST'])
def api_login():
    data = request.json or {}
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
        return jsonify({'authenticated': False})
    conn = get_db()
    user = fetchone(conn, "SELECT user_id, username, email, role, brotherhood_points FROM users WHERE user_id=?", (session['user_id'],))
    conn.close()
    if user:
        return jsonify({'authenticated': True, **dict(user)})
    return jsonify({'authenticated': False})

@app.route('/points/api/users', methods=['GET'])
@app.route('/budget/api/users', methods=['GET'])
@login_required
def api_get_users():
    conn = get_db()
    users = fetchall(conn, "SELECT user_id, username, email, role, brotherhood_points, is_active, created_at FROM users ORDER BY brotherhood_points DESC")
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
    # Allow submitting on behalf of another member (any logged-in user can do this)
    target_member_id = data.get('member_id', session['user_id'])
    conn = get_db()
    # Verify target member exists
    target = fetchone(conn, "SELECT user_id FROM users WHERE user_id=? AND is_active=true", (target_member_id,))
    if not target:
        conn.close()
        return jsonify({'error': 'Member not found'}), 404
    execute(conn, "INSERT INTO transactions (member_id, points, description) VALUES (?,?,?)",
            (target_member_id, data['points'], data['description']))
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
    label = (data.get('label') or '').strip()
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
    label = (data.get('label') or '').strip()
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

@app.route('/points/api/transactions/<int:tid>/reject', methods=['POST'])
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
# BUDGET API ROUTES
# ============================================================================

# ============================================================================
# DEPARTMENTS
# ============================================================================

@app.route('/budget/api/departments', methods=['GET'])
@login_required
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
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'Name is required'}), 400
    conn = get_db()
    try:
        execute(conn, "INSERT INTO budget_departments (name, description, created_by) VALUES (?,?,?)",
                (name, data.get('description','').strip(), session['user_id']))
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
            fields.append(f"{f}=?"); vals.append(data[f])
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
    name = (data.get('name') or '').strip()
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
        fields.append("name=?"); vals.append(data['name'])
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
@admin_required
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
def api_submit_request():
    data = request.json or {}
    item_id = data.get('item_id')
    description = (data.get('description') or '').strip()
    vendor = (data.get('vendor') or '').strip()
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
    reason = (data.get('reason') or '').strip()
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
# PAGE ROUTES
# ============================================================================


import os as _os

def _read_html(name):
    path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), name)
    with open(path) as f:
        return f.read()

@app.route('/')
def index():
    return _read_html('landing.html')

@app.route('/points')
def points_app():
    return _read_html('points.html')

@app.route('/budget')
def budget_app_route():
    return _read_html('budget.html')

init_db()

if __name__ == '__main__':
    print("\n" + "="*55)
    print("  Δ Τ Δ  Brotherhood Portal")
    print("="*55)
    print(f"  → Landing:      http://localhost:5000")
    print(f"  → Points:       http://localhost:5000/points")
    print(f"  → Budget:       http://localhost:5000/budget")
    print(f"  → Default login: admin / admin123")
    print(f"  → DB: {'PostgreSQL' if DATABASE_URL else 'SQLite (local)'}")
    print("="*55 + "\n")
    app.run(debug=False, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
