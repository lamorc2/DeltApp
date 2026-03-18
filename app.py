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

LANDING_HTML = '<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="UTF-8">\n<meta name="viewport" content="width=device-width, initial-scale=1.0">\n<title>Δ Τ Δ — Brotherhood Portal</title>\n<link href="https://fonts.googleapis.com/css2?family=Cinzel+Decorative:wght@700;900&family=Cinzel:wght@400;600;700&family=Crimson+Pro:ital,wght@0,300;0,400;0,600;1,300;1,400&display=swap" rel="stylesheet">\n<style>\n*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}\nbody{background:#0D0910;color:#F0E8D0;font-family:\'Crimson Pro\',Georgia,serif;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:2rem;overflow:hidden}\nbody::before{content:\'\';position:fixed;inset:0;background:radial-gradient(ellipse at 30% 20%,rgba(92,31,107,.35) 0%,transparent 60%),radial-gradient(ellipse at 70% 80%,rgba(61,12,69,.25) 0%,transparent 55%);pointer-events:none}\n.portal{position:relative;z-index:1;text-align:center;max-width:640px;width:100%}\n.symbol{font-family:\'Cinzel Decorative\',serif;font-size:5rem;color:#C9A84C;text-shadow:0 0 60px rgba(201,168,76,.4);line-height:1;display:block;margin-bottom:1rem}\n.org-name{font-family:\'Cinzel\',serif;font-size:.85rem;letter-spacing:.4em;color:#8A7235;text-transform:uppercase;margin-bottom:.5rem}\n.tagline{font-family:\'Crimson Pro\',serif;font-style:italic;font-size:1.2rem;color:#9A8E7A;margin-bottom:3rem}\n.apps{display:grid;grid-template-columns:1fr 1fr;gap:1.5rem;margin-bottom:2rem}\n.app-card{background:#1A0F21;border:1px solid rgba(201,168,76,.2);border-radius:8px;padding:2.5rem 2rem;text-decoration:none;color:inherit;transition:all .25s;position:relative;overflow:hidden;display:block}\n.app-card::before{content:\'\';position:absolute;inset:0;background:linear-gradient(135deg,rgba(201,168,76,.05) 0%,transparent 60%);opacity:0;transition:opacity .25s}\n.app-card:hover{border-color:rgba(201,168,76,.5);transform:translateY(-4px);box-shadow:0 12px 40px rgba(0,0,0,.4)}\n.app-card:hover::before{opacity:1}\n.app-icon{font-size:2.5rem;margin-bottom:1rem;display:block}\n.app-name{font-family:\'Cinzel\',serif;font-size:1rem;letter-spacing:.12em;color:#C9A84C;text-transform:uppercase;margin-bottom:.5rem}\n.app-desc{font-size:.9rem;color:#9A8E7A;font-style:italic;line-height:1.5}\n.footer{font-size:.75rem;color:#5C5248;font-family:\'Cinzel\',serif;letter-spacing:.2em}\n@media(max-width:480px){.apps{grid-template-columns:1fr}}\n</style>\n</head>\n<body>\n<div class="portal">\n  <span class="symbol">ΔΤΔ</span>\n  <div class="org-name">Delta Tau Delta</div>\n  <div class="tagline">Brotherhood Management Portal</div>\n  <div class="apps">\n    <a class="app-card" href="/points">\n      <span class="app-icon">⚔</span>\n      <div class="app-name">Brotherhood Points</div>\n      <div class="app-desc">Track member activities, submit point requests, and view the brotherhood leaderboard</div>\n    </a>\n    <a class="app-card" href="/budget">\n      <span class="app-icon">◈</span>\n      <div class="app-name">Treasury &amp; Budget</div>\n      <div class="app-desc">Manage department budgets, submit expense requests, and track brotherhood spending</div>\n    </a>\n  </div>\n  <div class="footer">Δ Τ Δ — Est. 1858</div>\n</div>\n</body>\n</html>'
POINTS_HTML  = '<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="UTF-8">\n<meta name="viewport" content="width=device-width, initial-scale=1.0">\n<title>Δ Τ Δ Brotherhood Points</title>\n<link href="https://fonts.googleapis.com/css2?family=Cinzel+Decorative:wght@700;900&family=Cinzel:wght@400;600;700&family=Crimson+Pro:ital,wght@0,300;0,400;0,600;1,300;1,400&display=swap" rel="stylesheet">\n<style>\n  :root {\n    --purple: #3D0C45;\n    --purple-mid: #5C1F6B;\n    --purple-light: #7B3094;\n    --gold: #C9A84C;\n    --gold-bright: #E8C96A;\n    --gold-dim: #8A7235;\n    --dark: #0D0910;\n    --dark-2: #150D1A;\n    --dark-3: #1E1227;\n    --dark-4: #261630;\n    --surface: #1A0F21;\n    --surface-2: #231428;\n    --border: rgba(201,168,76,0.18);\n    --border-strong: rgba(201,168,76,0.38);\n    --text: #F0E8D0;\n    --text-dim: #9A8E7A;\n    --text-muted: #5C5248;\n    --green: #4CAF7A;\n    --red: #CF4A4A;\n    --pending: #C9A84C;\n    --radius: 4px;\n    --radius-lg: 8px;\n  }\n\n  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }\n\n  body {\n    background: var(--dark);\n    color: var(--text);\n    font-family: \'Crimson Pro\', Georgia, serif;\n    font-size: 16px;\n    line-height: 1.6;\n    min-height: 100vh;\n    overflow-x: hidden;\n  }\n\n  /* Noise texture overlay */\n  body::before {\n    content: \'\';\n    position: fixed;\n    inset: 0;\n    background-image: url("data:image/svg+xml,%3Csvg viewBox=\'0 0 256 256\' xmlns=\'http://www.w3.org/2000/svg\'%3E%3Cfilter id=\'noise\'%3E%3CfeTurbulence type=\'fractalNoise\' baseFrequency=\'0.9\' numOctaves=\'4\' stitchTiles=\'stitch\'/%3E%3C/filter%3E%3Crect width=\'100%25\' height=\'100%25\' filter=\'url(%23noise)\' opacity=\'0.04\'/%3E%3C/svg%3E");\n    pointer-events: none;\n    z-index: 0;\n    opacity: 0.6;\n  }\n\n  /* ---- SCROLLBAR ---- */\n  ::-webkit-scrollbar { width: 6px; }\n  ::-webkit-scrollbar-track { background: var(--dark-2); }\n  ::-webkit-scrollbar-thumb { background: var(--purple-mid); border-radius: 3px; }\n\n  /* ---- LAYOUT ---- */\n  #app { position: relative; z-index: 1; }\n\n  /* ---- LOGIN ---- */\n  #login-screen {\n    display: flex;\n    align-items: center;\n    justify-content: center;\n    min-height: 100vh;\n    padding: 2rem;\n    background: radial-gradient(ellipse at 50% 0%, rgba(92,31,107,0.4) 0%, transparent 70%),\n                radial-gradient(ellipse at 80% 100%, rgba(61,12,69,0.3) 0%, transparent 60%);\n  }\n\n  .login-card {\n    width: 100%;\n    max-width: 420px;\n    background: var(--surface);\n    border: 1px solid var(--border-strong);\n    padding: 3rem 2.5rem;\n    position: relative;\n    box-shadow: 0 0 80px rgba(92,31,107,0.3), 0 0 0 1px rgba(201,168,76,0.08);\n  }\n\n  .login-card::before, .login-card::after {\n    content: \'\';\n    position: absolute;\n    width: 24px; height: 24px;\n    border-color: var(--gold);\n    border-style: solid;\n  }\n  .login-card::before { top: -1px; left: -1px; border-width: 2px 0 0 2px; }\n  .login-card::after { bottom: -1px; right: -1px; border-width: 0 2px 2px 0; }\n\n  .crest {\n    text-align: center;\n    margin-bottom: 2rem;\n  }\n  .crest-symbol {\n    font-family: \'Cinzel Decorative\', serif;\n    font-size: 3.5rem;\n    color: var(--gold);\n    display: block;\n    line-height: 1;\n    text-shadow: 0 0 40px rgba(201,168,76,0.4);\n    letter-spacing: 0.1em;\n  }\n  .crest-name {\n    font-family: \'Cinzel\', serif;\n    font-size: 0.75rem;\n    letter-spacing: 0.35em;\n    color: var(--gold-dim);\n    text-transform: uppercase;\n    margin-top: 0.5rem;\n  }\n  .crest-sub {\n    font-family: \'Crimson Pro\', serif;\n    font-style: italic;\n    font-size: 1rem;\n    color: var(--text-dim);\n    margin-top: 0.3rem;\n  }\n\n  .form-group { margin-bottom: 1.25rem; }\n  .form-label {\n    display: block;\n    font-family: \'Cinzel\', serif;\n    font-size: 0.65rem;\n    letter-spacing: 0.2em;\n    color: var(--gold-dim);\n    text-transform: uppercase;\n    margin-bottom: 0.5rem;\n  }\n  .form-input {\n    width: 100%;\n    background: var(--dark-3);\n    border: 1px solid var(--border);\n    color: var(--text);\n    padding: 0.75rem 1rem;\n    font-family: \'Crimson Pro\', serif;\n    font-size: 1rem;\n    outline: none;\n    border-radius: var(--radius);\n    transition: border-color 0.2s, box-shadow 0.2s;\n  }\n  .form-input:focus {\n    border-color: var(--gold);\n    box-shadow: 0 0 0 2px rgba(201,168,76,0.12);\n  }\n  .form-input::placeholder { color: var(--text-muted); }\n  select.form-input option { background: var(--dark-3); }\n\n  .btn {\n    display: inline-flex;\n    align-items: center;\n    gap: 0.5rem;\n    padding: 0.75rem 1.5rem;\n    font-family: \'Cinzel\', serif;\n    font-size: 0.7rem;\n    letter-spacing: 0.15em;\n    text-transform: uppercase;\n    cursor: pointer;\n    border: none;\n    border-radius: var(--radius);\n    transition: all 0.2s;\n    font-weight: 600;\n  }\n  .btn-primary {\n    background: linear-gradient(135deg, var(--purple-mid), var(--purple));\n    color: var(--gold);\n    border: 1px solid var(--border-strong);\n    width: 100%;\n    justify-content: center;\n    padding: 0.9rem;\n  }\n  .btn-primary:hover {\n    background: linear-gradient(135deg, var(--purple-light), var(--purple-mid));\n    box-shadow: 0 4px 20px rgba(92,31,107,0.5);\n  }\n  .btn-sm {\n    padding: 0.4rem 0.9rem;\n    font-size: 0.6rem;\n  }\n  .btn-ghost {\n    background: transparent;\n    color: var(--text-dim);\n    border: 1px solid var(--border);\n  }\n  .btn-ghost:hover { border-color: var(--gold); color: var(--gold); }\n  .btn-danger { background: rgba(207,74,74,0.15); color: var(--red); border: 1px solid rgba(207,74,74,0.3); }\n  .btn-danger:hover { background: rgba(207,74,74,0.25); }\n  .btn-success { background: rgba(76,175,122,0.15); color: var(--green); border: 1px solid rgba(76,175,122,0.3); }\n  .btn-success:hover { background: rgba(76,175,122,0.25); }\n  .btn-gold { background: linear-gradient(135deg, var(--gold), var(--gold-dim)); color: var(--dark); border: none; }\n  .btn-gold:hover { filter: brightness(1.1); }\n\n  .error-msg {\n    color: var(--red);\n    font-size: 0.875rem;\n    margin-top: 0.5rem;\n    display: none;\n    font-style: italic;\n  }\n\n  /* ---- MAIN APP ---- */\n  #main-app { display: none; flex-direction: column; min-height: 100vh; }\n\n  /* TOPBAR */\n  .topbar {\n    background: linear-gradient(180deg, var(--purple) 0%, var(--dark-2) 100%);\n    border-bottom: 1px solid var(--border-strong);\n    padding: 0 2rem;\n    height: 60px;\n    display: flex;\n    align-items: center;\n    justify-content: space-between;\n    position: sticky;\n    top: 0;\n    z-index: 100;\n    box-shadow: 0 2px 20px rgba(0,0,0,0.4);\n  }\n  .topbar-brand {\n    display: flex;\n    align-items: center;\n    gap: 1rem;\n  }\n  .topbar-symbol {\n    font-family: \'Cinzel Decorative\', serif;\n    font-size: 1.4rem;\n    color: var(--gold);\n    text-shadow: 0 0 20px rgba(201,168,76,0.5);\n  }\n  .topbar-title {\n    font-family: \'Cinzel\', serif;\n    font-size: 0.7rem;\n    letter-spacing: 0.25em;\n    color: var(--gold-dim);\n    text-transform: uppercase;\n  }\n  .topbar-user {\n    display: flex;\n    align-items: center;\n    gap: 1rem;\n    font-size: 0.875rem;\n  }\n  .user-badge {\n    display: flex;\n    align-items: center;\n    gap: 0.6rem;\n    background: rgba(201,168,76,0.08);\n    border: 1px solid var(--border);\n    padding: 0.35rem 0.9rem;\n    border-radius: 20px;\n  }\n  .user-name { font-family: \'Cinzel\', serif; font-size: 0.7rem; color: var(--gold); letter-spacing: 0.1em; }\n  .role-tag {\n    font-size: 0.6rem;\n    letter-spacing: 0.15em;\n    text-transform: uppercase;\n    padding: 0.15rem 0.5rem;\n    border-radius: 20px;\n    font-family: \'Cinzel\', serif;\n  }\n  .role-admin { background: rgba(201,168,76,0.2); color: var(--gold); border: 1px solid var(--gold-dim); }\n  .role-moderator { background: rgba(92,31,107,0.4); color: #C084D0; border: 1px solid var(--purple-light); }\n  .role-member { background: rgba(255,255,255,0.06); color: var(--text-dim); border: 1px solid var(--border); }\n\n  /* LAYOUT */\n  .app-body { display: flex; flex: 1; }\n\n  /* SIDEBAR */\n  .sidebar {\n    width: 220px;\n    background: var(--dark-2);\n    border-right: 1px solid var(--border);\n    padding: 1.5rem 0;\n    flex-shrink: 0;\n    position: sticky;\n    top: 60px;\n    height: calc(100vh - 60px);\n    overflow-y: auto;\n  }\n  .nav-section-title {\n    font-family: \'Cinzel\', serif;\n    font-size: 0.55rem;\n    letter-spacing: 0.3em;\n    color: var(--text-muted);\n    text-transform: uppercase;\n    padding: 0 1.5rem;\n    margin-bottom: 0.5rem;\n    margin-top: 1.5rem;\n  }\n  .nav-item {\n    display: flex;\n    align-items: center;\n    gap: 0.75rem;\n    padding: 0.65rem 1.5rem;\n    cursor: pointer;\n    transition: all 0.15s;\n    color: var(--text-dim);\n    font-size: 0.9rem;\n    border-left: 3px solid transparent;\n    position: relative;\n  }\n  .nav-item:hover { background: rgba(201,168,76,0.05); color: var(--text); }\n  .nav-item.active {\n    color: var(--gold);\n    background: rgba(201,168,76,0.08);\n    border-left-color: var(--gold);\n  }\n  .nav-item .icon { font-size: 1rem; width: 20px; text-align: center; }\n  .nav-badge {\n    margin-left: auto;\n    background: var(--red);\n    color: white;\n    font-size: 0.6rem;\n    font-family: \'Cinzel\', serif;\n    padding: 0.1rem 0.4rem;\n    border-radius: 10px;\n    min-width: 18px;\n    text-align: center;\n  }\n  .nav-divider { height: 1px; background: var(--border); margin: 1rem 1.5rem; }\n\n  /* CONTENT */\n  .content { flex: 1; padding: 2rem; overflow-x: auto; }\n\n  /* PAGE HEADER */\n  .page-header {\n    margin-bottom: 2rem;\n    padding-bottom: 1.25rem;\n    border-bottom: 1px solid var(--border);\n    display: flex;\n    align-items: flex-end;\n    justify-content: space-between;\n    gap: 1rem;\n    flex-wrap: wrap;\n  }\n  .page-title {\n    font-family: \'Cinzel\', serif;\n    font-size: 1.5rem;\n    color: var(--gold);\n    letter-spacing: 0.05em;\n  }\n  .page-subtitle { font-style: italic; color: var(--text-dim); font-size: 0.875rem; margin-top: 0.25rem; }\n\n  /* CARDS */\n  .card {\n    background: var(--surface);\n    border: 1px solid var(--border);\n    border-radius: var(--radius-lg);\n    padding: 1.5rem;\n    margin-bottom: 1.5rem;\n  }\n  .card-title {\n    font-family: \'Cinzel\', serif;\n    font-size: 0.8rem;\n    letter-spacing: 0.15em;\n    color: var(--gold-dim);\n    text-transform: uppercase;\n    margin-bottom: 1.25rem;\n    padding-bottom: 0.75rem;\n    border-bottom: 1px solid var(--border);\n  }\n\n  /* STATS ROW */\n  .stats-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 1rem; margin-bottom: 2rem; }\n  .stat-card {\n    background: var(--surface);\n    border: 1px solid var(--border);\n    border-radius: var(--radius-lg);\n    padding: 1.25rem 1.5rem;\n    position: relative;\n    overflow: hidden;\n  }\n  .stat-card::before {\n    content: \'\';\n    position: absolute;\n    top: 0; left: 0; right: 0;\n    height: 2px;\n    background: linear-gradient(90deg, var(--gold-dim), var(--gold));\n  }\n  .stat-label { font-family: \'Cinzel\', serif; font-size: 0.6rem; letter-spacing: 0.2em; color: var(--text-muted); text-transform: uppercase; }\n  .stat-value { font-family: \'Cinzel Decorative\', serif; font-size: 2rem; color: var(--gold); line-height: 1.2; margin: 0.3rem 0; }\n  .stat-sub { font-size: 0.8rem; color: var(--text-dim); font-style: italic; }\n\n  /* TABLE */\n  .table-wrap { overflow-x: auto; }\n  table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }\n  thead tr { border-bottom: 1px solid var(--border-strong); }\n  th {\n    font-family: \'Cinzel\', serif;\n    font-size: 0.6rem;\n    letter-spacing: 0.18em;\n    color: var(--gold-dim);\n    text-transform: uppercase;\n    padding: 0.75rem 1rem;\n    text-align: left;\n    font-weight: 600;\n    white-space: nowrap;\n  }\n  td { padding: 0.75rem 1rem; border-bottom: 1px solid var(--border); color: var(--text); vertical-align: middle; }\n  tr:last-child td { border-bottom: none; }\n  tbody tr { transition: background 0.15s; }\n  tbody tr:hover { background: rgba(201,168,76,0.04); }\n\n  /* BADGES */\n  .badge {\n    display: inline-block;\n    padding: 0.2rem 0.6rem;\n    border-radius: 20px;\n    font-size: 0.65rem;\n    font-family: \'Cinzel\', serif;\n    letter-spacing: 0.08em;\n    text-transform: uppercase;\n    font-weight: 600;\n  }\n  .badge-pending { background: rgba(201,168,76,0.15); color: var(--gold); border: 1px solid rgba(201,168,76,0.3); }\n  .badge-approved { background: rgba(76,175,122,0.15); color: var(--green); border: 1px solid rgba(76,175,122,0.3); }\n  .badge-rejected { background: rgba(207,74,74,0.15); color: var(--red); border: 1px solid rgba(207,74,74,0.3); }\n  .badge-admin { background: rgba(201,168,76,0.15); color: var(--gold); border: 1px solid rgba(201,168,76,0.25); }\n  .badge-moderator { background: rgba(192,132,208,0.15); color: #C084D0; border: 1px solid rgba(192,132,208,0.25); }\n  .badge-member { background: rgba(255,255,255,0.06); color: var(--text-dim); border: 1px solid var(--border); }\n  .badge-active { background: rgba(76,175,122,0.1); color: var(--green); border: 1px solid rgba(76,175,122,0.2); }\n  .badge-inactive { background: rgba(207,74,74,0.1); color: var(--red); border: 1px solid rgba(207,74,74,0.2); }\n\n  /* POINTS */\n  .points-num { font-family: \'Cinzel\', serif; color: var(--gold); font-size: 0.95rem; }\n\n  /* RANK */\n  .rank-1 { color: var(--gold); font-weight: bold; }\n  .rank-2 { color: #C0C0C0; }\n  .rank-3 { color: #CD7F32; }\n  .rank-medal { font-size: 1.1rem; }\n\n  /* LEADERBOARD TOP 3 */\n  .podium { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 1rem; margin-bottom: 2rem; }\n  .podium-card {\n    background: var(--surface);\n    border: 1px solid var(--border);\n    border-radius: var(--radius-lg);\n    padding: 1.5rem;\n    text-align: center;\n    position: relative;\n    overflow: hidden;\n  }\n  .podium-card.first {\n    background: linear-gradient(180deg, rgba(201,168,76,0.12) 0%, var(--surface) 60%);\n    border-color: var(--gold-dim);\n    transform: translateY(-8px);\n  }\n  .podium-card.second { background: linear-gradient(180deg, rgba(192,192,192,0.08) 0%, var(--surface) 60%); }\n  .podium-card.third { background: linear-gradient(180deg, rgba(205,127,50,0.08) 0%, var(--surface) 60%); }\n  .podium-rank { font-family: \'Cinzel Decorative\', serif; font-size: 2rem; margin-bottom: 0.5rem; }\n  .first .podium-rank { color: var(--gold); }\n  .second .podium-rank { color: #C0C0C0; }\n  .third .podium-rank { color: #CD7F32; }\n  .podium-name { font-family: \'Cinzel\', serif; font-size: 0.9rem; letter-spacing: 0.1em; color: var(--text); }\n  .podium-pts { font-family: \'Cinzel Decorative\', serif; font-size: 1.5rem; color: var(--gold); margin-top: 0.5rem; }\n  .podium-pts-label { font-size: 0.7rem; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.15em; }\n\n  /* MODAL */\n  .modal-overlay {\n    position: fixed;\n    inset: 0;\n    background: rgba(0,0,0,0.7);\n    backdrop-filter: blur(4px);\n    display: flex;\n    align-items: center;\n    justify-content: center;\n    z-index: 200;\n    padding: 1rem;\n    opacity: 0;\n    pointer-events: none;\n    transition: opacity 0.2s;\n  }\n  .modal-overlay.show { opacity: 1; pointer-events: all; }\n  .modal {\n    background: var(--surface);\n    border: 1px solid var(--border-strong);\n    border-radius: var(--radius-lg);\n    width: 100%;\n    max-width: 480px;\n    max-height: 90vh;\n    overflow-y: auto;\n    transform: translateY(20px);\n    transition: transform 0.2s;\n    position: relative;\n  }\n  .modal-overlay.show .modal { transform: translateY(0); }\n  .modal-header {\n    background: linear-gradient(135deg, var(--purple) 0%, var(--dark-2) 100%);\n    padding: 1.25rem 1.5rem;\n    border-bottom: 1px solid var(--border);\n    display: flex;\n    align-items: center;\n    justify-content: space-between;\n  }\n  .modal-title { font-family: \'Cinzel\', serif; font-size: 0.85rem; letter-spacing: 0.15em; color: var(--gold); text-transform: uppercase; }\n  .modal-close { background: none; border: none; color: var(--text-dim); font-size: 1.2rem; cursor: pointer; padding: 0.25rem; }\n  .modal-close:hover { color: var(--text); }\n  .modal-body { padding: 1.5rem; }\n  .modal-footer { padding: 1rem 1.5rem; border-top: 1px solid var(--border); display: flex; gap: 0.75rem; justify-content: flex-end; }\n\n  /* TOAST */\n  #toast-container { position: fixed; top: 1rem; right: 1rem; z-index: 9999; display: flex; flex-direction: column; gap: 0.5rem; }\n  .toast {\n    background: var(--surface);\n    border: 1px solid var(--border);\n    padding: 0.8rem 1.2rem;\n    border-radius: var(--radius);\n    font-size: 0.875rem;\n    display: flex;\n    align-items: center;\n    gap: 0.75rem;\n    min-width: 280px;\n    box-shadow: 0 4px 20px rgba(0,0,0,0.4);\n    animation: slideIn 0.3s ease;\n  }\n  .toast.success { border-left: 3px solid var(--green); }\n  .toast.error { border-left: 3px solid var(--red); }\n  .toast.info { border-left: 3px solid var(--gold); }\n  @keyframes slideIn { from { transform: translateX(100%); opacity: 0; } to { transform: none; opacity: 1; } }\n\n  /* SEARCH */\n  .search-bar {\n    display: flex;\n    gap: 0.75rem;\n    margin-bottom: 1rem;\n    flex-wrap: wrap;\n    align-items: center;\n  }\n  .search-input {\n    background: var(--dark-3);\n    border: 1px solid var(--border);\n    color: var(--text);\n    padding: 0.5rem 1rem;\n    font-family: \'Crimson Pro\', serif;\n    font-size: 0.9rem;\n    outline: none;\n    border-radius: var(--radius);\n    min-width: 220px;\n    transition: border-color 0.2s;\n  }\n  .search-input:focus { border-color: var(--gold-dim); }\n  .search-input::placeholder { color: var(--text-muted); }\n\n  /* EMPTY STATE */\n  .empty-state { text-align: center; padding: 3rem; color: var(--text-muted); }\n  .empty-icon { font-size: 2.5rem; margin-bottom: 1rem; }\n  .empty-text { font-style: italic; font-size: 1rem; }\n\n  /* ACTION BTNS */\n  .action-btns { display: flex; gap: 0.4rem; flex-wrap: wrap; }\n\n  /* TEXTAREA */\n  textarea.form-input { resize: vertical; min-height: 80px; }\n\n  /* SECTION PAGES */\n  .page { display: none; }\n  .page.active { display: block; }\n\n  /* POINTS SUBMIT */\n  .submit-form { max-width: 600px; }\n\n  /* CUSTOM ACTION TOGGLE */\n  .custom-toggle-row {\n    display: flex;\n    align-items: center;\n    gap: 0.75rem;\n    margin-bottom: 1rem;\n  }\n  .toggle-checkbox {\n    width: 16px; height: 16px;\n    accent-color: var(--gold);\n    cursor: pointer;\n    flex-shrink: 0;\n  }\n  .toggle-label {\n    font-family: \'Cinzel\', serif;\n    font-size: 0.65rem;\n    letter-spacing: 0.15em;\n    color: var(--text-dim);\n    text-transform: uppercase;\n    cursor: pointer;\n    user-select: none;\n  }\n\n  /* ACTION DROPDOWN OPTION PREVIEW */\n  .action-preview {\n    background: var(--dark-3);\n    border: 1px solid var(--border);\n    border-radius: var(--radius);\n    padding: 0.6rem 1rem;\n    margin-top: 0.5rem;\n    display: flex;\n    align-items: center;\n    justify-content: space-between;\n    min-height: 42px;\n  }\n  .action-preview-label { font-style: italic; color: var(--text-dim); font-size: 0.9rem; }\n  .action-pts-badge {\n    font-family: \'Cinzel\', serif;\n    font-size: 0.8rem;\n    padding: 0.2rem 0.6rem;\n    border-radius: 20px;\n    font-weight: 700;\n  }\n  .pts-positive { background: rgba(76,175,122,0.15); color: var(--green); border: 1px solid rgba(76,175,122,0.3); }\n  .pts-negative { background: rgba(207,74,74,0.15); color: var(--red); border: 1px solid rgba(207,74,74,0.3); }\n  .pts-zero { background: rgba(255,255,255,0.06); color: var(--text-dim); border: 1px solid var(--border); }\n\n  /* ACTIONS MANAGEMENT */\n  .actions-grid { display: grid; gap: 0.75rem; }\n  .action-row {\n    display: flex;\n    align-items: center;\n    gap: 1rem;\n    background: var(--dark-3);\n    border: 1px solid var(--border);\n    border-radius: var(--radius);\n    padding: 0.75rem 1rem;\n    transition: border-color 0.15s;\n  }\n  .action-row:hover { border-color: var(--border-strong); }\n  .action-row-label { flex: 1; font-size: 0.95rem; }\n  .action-row-pts { font-family: \'Cinzel\', serif; font-size: 0.85rem; min-width: 60px; text-align: right; }\n  .disabled-row { opacity: 0.4; }\n\n  /* UTILITY */\n  .text-gold { color: var(--gold); }\n  .text-dim { color: var(--text-dim); }\n  .text-green { color: var(--green); }\n  .text-red { color: var(--red); }\n  .flex { display: flex; }\n  .gap-2 { gap: 0.5rem; }\n  .mt-1 { margin-top: 0.5rem; }\n  .truncate { max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }\n\n  /* RESPONSIVE */\n  @media (max-width: 768px) {\n    .sidebar { display: none; }\n    .content { padding: 1rem; }\n    .podium { grid-template-columns: 1fr; }\n    .stats-row { grid-template-columns: 1fr 1fr; }\n  }\n</style>\n</head>\n<body>\n<div id="app">\n\n<!-- LOGIN -->\n<div id="login-screen">\n  <div class="login-card">\n    <div class="crest">\n      <span class="crest-symbol">ΔΤΔ</span>\n      <div class="crest-name">Delta Tau Delta</div>\n      <div class="crest-sub">Brotherhood Points System</div>\n    </div>\n    <div class="form-group">\n      <label class="form-label">Username</label>\n      <input class="form-input" type="text" id="login-username" placeholder="Enter your username" autocomplete="username">\n    </div>\n    <div class="form-group">\n      <label class="form-label">Password</label>\n      <input class="form-input" type="password" id="login-password" placeholder="••••••••" autocomplete="current-password">\n    </div>\n    <div class="error-msg" id="login-error">Invalid credentials or inactive account.</div>\n    <button class="btn btn-primary" id="login-btn" onclick="doLogin()">Sign In to Brotherhood</button>\n  </div>\n</div>\n\n<!-- MAIN APP -->\n<div id="main-app">\n  <div class="topbar">\n    <div class="topbar-brand">\n      <span class="topbar-symbol">ΔΤΔ</span>\n      <span class="topbar-title">Brotherhood Points</span>\n    </div>\n    <div class="topbar-nav-links" style="display:flex;gap:.5rem;margin-left:1.5rem">\n      <a href="/points" style="font-family:\'Cinzel\',serif;font-size:.65rem;letter-spacing:.15em;color:var(--gold);text-decoration:none;padding:.35rem .8rem;border:1px solid var(--gold-dim);border-radius:4px;background:rgba(201,168,76,.12)">⚔ Points</a>\n      <a href="/budget" style="font-family:\'Cinzel\',serif;font-size:.65rem;letter-spacing:.15em;color:var(--text-dim);text-decoration:none;padding:.35rem .8rem;border:1px solid var(--border);border-radius:4px">◈ Budget</a>\n    </div>\n    <div class="topbar-user">\n      <div class="user-badge">\n        <span class="user-name" id="topbar-username"></span>\n        <span class="role-tag" id="topbar-role"></span>\n      </div>\n      <button class="btn btn-ghost btn-sm" onclick="doLogout()">Sign Out</button>\n    </div>\n  </div>\n\n  <div class="app-body">\n    <nav class="sidebar">\n      <div class="nav-section-title">Navigation</div>\n      <div class="nav-item active" onclick="showPage(\'leaderboard\', this)" id="nav-leaderboard">\n        <span class="icon">🏆</span> Leaderboard\n      </div>\n      <div class="nav-item" onclick="showPage(\'submit\', this)" id="nav-submit" style="display:none">\n        <span class="icon">✦</span> Submit Points\n      </div>\n      <div class="nav-item" onclick="showPage(\'my-transactions\', this)" id="nav-my-tx" style="display:none">\n        <span class="icon">📋</span> My Requests\n      </div>\n      <div class="nav-divider"></div>\n      <div class="nav-section-title" id="mod-section" style="display:none">Moderation</div>\n      <div class="nav-item" onclick="showPage(\'pending\', this)" id="nav-pending" style="display:none">\n        <span class="icon">⏳</span> Pending\n        <span class="nav-badge" id="pending-count" style="display:none">0</span>\n      </div>\n      <div class="nav-item" onclick="showPage(\'all-transactions\', this)" id="nav-all-tx" style="display:none">\n        <span class="icon">📜</span> All Transactions\n      </div>\n      <div class="nav-divider" id="admin-divider" style="display:none"></div>\n      <div class="nav-section-title" id="admin-section" style="display:none">Admin</div>\n      <div class="nav-item" onclick="showPage(\'actions\', this)" id="nav-actions" style="display:none">\n        <span class="icon">⚙</span> Point Actions\n      </div>\n      <div class="nav-item" onclick="showPage(\'users\', this)" id="nav-users" style="display:none">\n        <span class="icon">👥</span> User Management\n      </div>\n    </nav>\n\n    <main class="content">\n      <!-- Leaderboard -->\n      <div class="page active" id="page-leaderboard">\n        <div class="page-header">\n          <div>\n            <div class="page-title">Brotherhood Leaderboard</div>\n            <div class="page-subtitle">Rankings by earned brotherhood points</div>\n          </div>\n          <button class="btn btn-ghost btn-sm" onclick="loadLeaderboard()">↻ Refresh</button>\n        </div>\n        <div class="podium" id="podium"></div>\n        <div class="card">\n          <div class="card-title">Full Rankings</div>\n          <div class="table-wrap">\n            <table>\n              <thead>\n                <tr><th>#</th><th>Member</th><th>Email</th><th>Role</th><th>Points</th><th>Status</th></tr>\n              </thead>\n              <tbody id="leaderboard-body"></tbody>\n            </table>\n          </div>\n        </div>\n      </div>\n\n      <!-- Submit Points -->\n      <div class="page" id="page-submit">\n        <div class="page-header">\n          <div>\n            <div class="page-title">Submit Points Request</div>\n            <div class="page-subtitle">Report an activity for any member</div>\n          </div>\n        </div>\n        <div class="card submit-form">\n          <div class="card-title">New Request</div>\n\n          <div class="form-group">\n            <label class="form-label">Member</label>\n            <select class="form-input" id="sub-member">\n              <option value="">Loading members...</option>\n            </select>\n          </div>\n\n          <div class="form-group">\n            <label class="form-label">Action</label>\n            <select class="form-input" id="sub-action" onchange="onActionChange()" disabled>\n              <option value="">— Select an action —</option>\n            </select>\n            <div class="action-preview" id="action-preview">\n              <span class="action-preview-label">Select an action to see details</span>\n            </div>\n          </div>\n\n          <div class="custom-toggle-row">\n            <input type="checkbox" class="toggle-checkbox" id="sub-custom-check" onchange="toggleCustom()">\n            <label class="toggle-label" for="sub-custom-check">Custom entry</label>\n          </div>\n\n          <div id="custom-fields" style="display:none;">\n            <div class="form-group">\n              <label class="form-label">Custom Description</label>\n              <input class="form-input" type="text" id="sub-custom-desc" placeholder="Describe the activity...">\n            </div>\n            <div class="form-group">\n              <label class="form-label">Points Value <span class="text-dim">(use negative for deductions)</span></label>\n              <input class="form-input" type="number" id="sub-custom-points" placeholder="e.g. 5 or -2">\n            </div>\n          </div>\n\n          <button class="btn btn-gold" onclick="submitPoints()" style="margin-top:0.5rem;">✦ Submit for Review</button>\n        </div>\n      </div>\n\n      <!-- My Transactions -->\n      <div class="page" id="page-my-transactions">\n        <div class="page-header">\n          <div>\n            <div class="page-title">My Requests</div>\n            <div class="page-subtitle">Track your submitted point requests</div>\n          </div>\n          <button class="btn btn-ghost btn-sm" onclick="loadMyTransactions()">↻ Refresh</button>\n        </div>\n        <div class="card">\n          <div class="table-wrap">\n            <table>\n              <thead>\n                <tr><th>ID</th><th>Points</th><th>Description</th><th>Status</th><th>Submitted</th><th>Reviewer</th></tr>\n              </thead>\n              <tbody id="my-tx-body"></tbody>\n            </table>\n          </div>\n        </div>\n      </div>\n\n      <!-- Pending Moderation -->\n      <div class="page" id="page-pending">\n        <div class="page-header">\n          <div>\n            <div class="page-title">Pending Requests</div>\n            <div class="page-subtitle">Review and approve or reject submitted requests</div>\n          </div>\n          <button class="btn btn-ghost btn-sm" onclick="loadPending()">↻ Refresh</button>\n        </div>\n        <div class="card">\n          <div class="table-wrap">\n            <table>\n              <thead>\n                <tr><th>ID</th><th>Member</th><th>Points</th><th>Description</th><th>Submitted</th><th>Actions</th></tr>\n              </thead>\n              <tbody id="pending-body"></tbody>\n            </table>\n          </div>\n        </div>\n      </div>\n\n      <!-- All Transactions -->\n      <div class="page" id="page-all-transactions">\n        <div class="page-header">\n          <div>\n            <div class="page-title">Transaction History</div>\n            <div class="page-subtitle">Complete record of all point requests</div>\n          </div>\n          <button class="btn btn-ghost btn-sm" onclick="loadAllTransactions()">↻ Refresh</button>\n        </div>\n        <div class="card">\n          <div class="search-bar">\n            <input class="search-input" id="tx-search" placeholder="Search by member or description..." oninput="filterTransactions()">\n          </div>\n          <div class="table-wrap">\n            <table>\n              <thead>\n                <tr><th>ID</th><th>Member</th><th>Points</th><th>Description</th><th>Status</th><th>Submitted</th><th>Reviewer</th></tr>\n              </thead>\n              <tbody id="all-tx-body"></tbody>\n            </table>\n          </div>\n        </div>\n      </div>\n\n      <!-- User Management -->\n      <div class="page" id="page-users">\n        <div class="page-header">\n          <div>\n            <div class="page-title">User Management</div>\n            <div class="page-subtitle">Manage brotherhood member accounts</div>\n          </div>\n          <button class="btn btn-gold btn-sm" onclick="openAddUser()">+ Add Member</button>\n        </div>\n        <div class="card">\n          <div class="search-bar">\n            <input class="search-input" id="user-search" placeholder="Search members..." oninput="filterUsers()">\n          </div>\n          <div class="table-wrap">\n            <table>\n              <thead>\n                <tr><th>ID</th><th>Username</th><th>Email</th><th>Role</th><th>Points</th><th>Status</th><th>Joined</th><th>Actions</th></tr>\n              </thead>\n              <tbody id="users-body"></tbody>\n            </table>\n          </div>\n        </div>\n      </div>\n      <!-- Point Actions Management -->\n      <div class="page" id="page-actions">\n        <div class="page-header">\n          <div>\n            <div class="page-title">Point Actions</div>\n            <div class="page-subtitle">Define the actions members can report</div>\n          </div>\n          <button class="btn btn-gold btn-sm" onclick="openAddAction()">+ New Action</button>\n        </div>\n        <div class="card">\n          <div class="card-title">Defined Actions</div>\n          <div class="actions-grid" id="actions-grid">\n            <div class="empty-state"><div class="empty-text">Loading...</div></div>\n          </div>\n        </div>\n      </div>\n\n    </main>\n  </div>\n</div>\n\n<!-- TOAST CONTAINER -->\n<div id="toast-container"></div>\n\n<!-- ADD USER MODAL -->\n<div class="modal-overlay" id="modal-add-user">\n  <div class="modal">\n    <div class="modal-header">\n      <span class="modal-title">Add New Member</span>\n      <button class="modal-close" onclick="closeModal(\'modal-add-user\')">✕</button>\n    </div>\n    <div class="modal-body">\n      <div class="form-group"><label class="form-label">Username</label><input class="form-input" id="add-username" placeholder="Username"></div>\n      <div class="form-group"><label class="form-label">Email</label><input class="form-input" type="email" id="add-email" placeholder="email@example.com"></div>\n      <div class="form-group"><label class="form-label">Password</label><input class="form-input" type="password" id="add-password" placeholder="Password"></div>\n      <div class="form-group">\n        <label class="form-label">Role</label>\n        <select class="form-input" id="add-role">\n          <option value="member">Member</option>\n          <option value="moderator">Moderator</option>\n          <option value="admin">Admin</option>\n        </select>\n      </div>\n      <div class="error-msg" id="add-error"></div>\n    </div>\n    <div class="modal-footer">\n      <button class="btn btn-ghost btn-sm" onclick="closeModal(\'modal-add-user\')">Cancel</button>\n      <button class="btn btn-gold btn-sm" onclick="createUser()">Create Member</button>\n    </div>\n  </div>\n</div>\n\n<!-- EDIT USER MODAL -->\n<div class="modal-overlay" id="modal-edit-user">\n  <div class="modal">\n    <div class="modal-header">\n      <span class="modal-title">Edit Member</span>\n      <button class="modal-close" onclick="closeModal(\'modal-edit-user\')">✕</button>\n    </div>\n    <div class="modal-body">\n      <input type="hidden" id="edit-uid">\n      <div class="form-group"><label class="form-label">Username</label><input class="form-input" id="edit-username" placeholder="Username"></div>\n      <div class="form-group"><label class="form-label">Email</label><input class="form-input" type="email" id="edit-email"></div>\n      <div class="form-group"><label class="form-label">New Password <span class="text-dim">(leave blank to keep)</span></label><input class="form-input" type="password" id="edit-password" placeholder="New password"></div>\n      <div class="form-group">\n        <label class="form-label">Role</label>\n        <select class="form-input" id="edit-role">\n          <option value="member">Member</option>\n          <option value="moderator">Moderator</option>\n          <option value="admin">Admin</option>\n        </select>\n      </div>\n      <div class="form-group">\n        <label class="form-label">Status</label>\n        <select class="form-input" id="edit-active">\n          <option value="1">Active</option>\n          <option value="0">Inactive</option>\n        </select>\n      </div>\n      <div class="error-msg" id="edit-error"></div>\n    </div>\n    <div class="modal-footer">\n      <button class="btn btn-ghost btn-sm" onclick="closeModal(\'modal-edit-user\')">Cancel</button>\n      <button class="btn btn-gold btn-sm" onclick="saveUser()">Save Changes</button>\n    </div>\n  </div>\n</div>\n\n<!-- REJECT MODAL -->\n<div class="modal-overlay" id="modal-reject">\n  <div class="modal">\n    <div class="modal-header">\n      <span class="modal-title">Reject Request</span>\n      <button class="modal-close" onclick="closeModal(\'modal-reject\')">✕</button>\n    </div>\n    <div class="modal-body">\n      <input type="hidden" id="reject-tid">\n      <div class="form-group">\n        <label class="form-label">Reason for Rejection</label>\n        <textarea class="form-input" id="reject-reason" placeholder="Explain why this request is being rejected..."></textarea>\n      </div>\n    </div>\n    <div class="modal-footer">\n      <button class="btn btn-ghost btn-sm" onclick="closeModal(\'modal-reject\')">Cancel</button>\n      <button class="btn btn-danger btn-sm" onclick="confirmReject()">Reject Request</button>\n    </div>\n  </div>\n</div>\n\n<!-- ADD ACTION MODAL -->\n<div class="modal-overlay" id="modal-add-action">\n  <div class="modal">\n    <div class="modal-header">\n      <span class="modal-title">New Point Action</span>\n      <button class="modal-close" onclick="closeModal(\'modal-add-action\')">✕</button>\n    </div>\n    <div class="modal-body">\n      <div class="form-group"><label class="form-label">Label</label><input class="form-input" id="action-label" placeholder="e.g. Missed a Daily"></div>\n      <div class="form-group"><label class="form-label">Points <span class="text-dim">(negative for deductions)</span></label><input class="form-input" type="number" id="action-points" placeholder="e.g. -1 or 3"></div>\n      <div class="error-msg" id="action-error"></div>\n    </div>\n    <div class="modal-footer">\n      <button class="btn btn-ghost btn-sm" onclick="closeModal(\'modal-add-action\')">Cancel</button>\n      <button class="btn btn-gold btn-sm" onclick="createAction()">Create Action</button>\n    </div>\n  </div>\n</div>\n\n<!-- EDIT ACTION MODAL -->\n<div class="modal-overlay" id="modal-edit-action">\n  <div class="modal">\n    <div class="modal-header">\n      <span class="modal-title">Edit Action</span>\n      <button class="modal-close" onclick="closeModal(\'modal-edit-action\')">✕</button>\n    </div>\n    <div class="modal-body">\n      <input type="hidden" id="edit-action-id">\n      <div class="form-group"><label class="form-label">Label</label><input class="form-input" id="edit-action-label"></div>\n      <div class="form-group"><label class="form-label">Points</label><input class="form-input" type="number" id="edit-action-points"></div>\n      <div class="error-msg" id="edit-action-error"></div>\n    </div>\n    <div class="modal-footer">\n      <button class="btn btn-ghost btn-sm" onclick="closeModal(\'modal-edit-action\')">Cancel</button>\n      <button class="btn btn-gold btn-sm" onclick="saveAction()">Save</button>\n    </div>\n  </div>\n</div>\n\n<script>\nlet currentUser = null;\nlet allUsers = [];\nlet allTransactions = [];\nlet allActions = [];\n\n// ---- UTILS ----\nfunction toast(msg, type=\'info\') {\n  const c = document.getElementById(\'toast-container\');\n  const t = document.createElement(\'div\');\n  t.className = `toast ${type}`;\n  const icons = {success:\'✓\', error:\'✕\', info:\'ⓘ\'};\n  t.innerHTML = `<span>${icons[type]||\'ⓘ\'}</span><span>${msg}</span>`;\n  c.appendChild(t);\n  setTimeout(() => t.remove(), 3500);\n}\n\nfunction openModal(id) { document.getElementById(id).classList.add(\'show\'); }\nfunction closeModal(id) { document.getElementById(id).classList.remove(\'show\'); }\n\nfunction fmtDate(d) {\n  if (!d) return \'—\';\n  return new Date(d).toLocaleDateString(\'en-US\', {month:\'short\', day:\'numeric\', year:\'numeric\'});\n}\n\nfunction roleBadge(role) {\n  return `<span class="badge badge-${role}">${role}</span>`;\n}\nfunction statusBadge(s) {\n  return `<span class="badge badge-${s}">${s}</span>`;\n}\n\n// ---- AUTH ----\nasync function doLogin() {\n  const u = document.getElementById(\'login-username\').value.trim();\n  const p = document.getElementById(\'login-password\').value;\n  const err = document.getElementById(\'login-error\');\n  err.style.display = \'none\';\n  document.getElementById(\'login-btn\').textContent = \'Signing in…\';\n  try {\n    const r = await fetch(\'/points/api/login\', {method:\'POST\', headers:{\'Content-Type\':\'application/json\'}, body:JSON.stringify({username:u, password:p})});\n    const d = await r.json();\n    if (d.success) {\n      await loadApp();\n    } else {\n      err.style.display = \'block\';\n      document.getElementById(\'login-btn\').textContent = \'Sign In to Brotherhood\';\n    }\n  } catch(e) {\n    err.textContent = \'Connection error. Is the server running?\';\n    err.style.display = \'block\';\n    document.getElementById(\'login-btn\').textContent = \'Sign In to Brotherhood\';\n  }\n}\n\nasync function doLogout() {\n  await fetch(\'/points/api/logout\', {method:\'POST\'});\n  currentUser = null;\n  document.getElementById(\'main-app\').style.display = \'none\';\n  document.getElementById(\'login-screen\').style.display = \'flex\';\n  document.getElementById(\'login-password\').value = \'\';\n}\n\nasync function loadApp() {\n  const r = await fetch(\'/points/api/me\');\n  const d = await r.json();\n  if (!d.authenticated) { return; }\n  currentUser = d;\n\n  document.getElementById(\'login-screen\').style.display = \'none\';\n  document.getElementById(\'main-app\').style.display = \'flex\';\n\n  document.getElementById(\'topbar-username\').textContent = d.username.toUpperCase();\n  const rb = document.getElementById(\'topbar-role\');\n  rb.textContent = d.role;\n  rb.className = `role-tag role-${d.role}`;\n\n  const role = d.role;\n  // Show/hide nav items\n  const show = (id) => document.getElementById(id).style.display = \'flex\';\n  const hide = (id) => document.getElementById(id).style.display = \'none\';\n\n  if (role === \'member\') {\n    show(\'nav-submit\'); show(\'nav-my-tx\');\n    hide(\'nav-pending\'); hide(\'nav-all-tx\'); hide(\'nav-users\');\n    hide(\'mod-section\'); hide(\'admin-section\'); hide(\'admin-divider\');\n  } else if (role === \'moderator\') {\n    show(\'nav-submit\'); show(\'nav-my-tx\');\n    show(\'nav-pending\'); show(\'nav-all-tx\');\n    document.getElementById(\'mod-section\').style.display = \'block\';\n    hide(\'nav-users\'); hide(\'admin-section\'); hide(\'admin-divider\');\n  } else if (role === \'admin\') {\n    show(\'nav-submit\'); show(\'nav-my-tx\');\n    show(\'nav-pending\'); show(\'nav-all-tx\');\n    document.getElementById(\'mod-section\').style.display = \'block\';\n    show(\'nav-actions\'); show(\'nav-users\');\n    document.getElementById(\'admin-section\').style.display = \'block\';\n    document.getElementById(\'admin-divider\').style.display = \'block\';\n  }\n\n  showPage(\'leaderboard\', document.getElementById(\'nav-leaderboard\'));\n  loadLeaderboard();\n  if (role !== \'member\') pollPending();\n}\n\nasync function pollPending() {\n  if (!currentUser || currentUser.role === \'member\') return;\n  try {\n    const r = await fetch(\'/points/api/transactions/pending\');\n    const d = await r.json();\n    const badge = document.getElementById(\'pending-count\');\n    if (d.length > 0) {\n      badge.textContent = d.length;\n      badge.style.display = \'inline\';\n    } else {\n      badge.style.display = \'none\';\n    }\n  } catch(e) {}\n  setTimeout(pollPending, 30000);\n}\n\n// ---- NAV ----\nfunction showPage(page, el) {\n  document.querySelectorAll(\'.page\').forEach(p => p.classList.remove(\'active\'));\n  document.querySelectorAll(\'.nav-item\').forEach(n => n.classList.remove(\'active\'));\n  const pageEl = document.getElementById(\'page-\' + page);\n  if (pageEl) pageEl.classList.add(\'active\');\n  if (el) el.classList.add(\'active\');\n\n  // Load data for page\n  if (page === \'leaderboard\') loadLeaderboard();\n  else if (page === \'submit\') loadSubmitForm();\n  else if (page === \'my-transactions\') loadMyTransactions();\n  else if (page === \'pending\') loadPending();\n  else if (page === \'all-transactions\') loadAllTransactions();\n  else if (page === \'users\') loadUsers();\n  else if (page === \'actions\') loadActions();\n}\n\n// ---- LEADERBOARD ----\nasync function loadLeaderboard() {\n  const r = await fetch(\'/points/api/users\');\n  const users = await r.json();\n  const active = users.filter(u => u.is_active);\n\n  // Podium\n  const podium = document.getElementById(\'podium\');\n  const medals = [\'🥇\',\'🥈\',\'🥉\'];\n  const classes = [\'first\',\'second\',\'third\'];\n  const top3 = active.slice(0,3);\n  // Reorder: 2nd, 1st, 3rd for podium effect\n  const order = top3.length >= 3 ? [top3[1], top3[0], top3[2]] : top3.length === 2 ? [top3[1], top3[0]] : top3;\n  const orderClasses = top3.length >= 3 ? [\'second\',\'first\',\'third\'] : top3.length === 2 ? [\'second\',\'first\'] : [\'first\'];\n  const orderMedals = top3.length >= 3 ? [medals[1],medals[0],medals[2]] : top3.length === 2 ? [medals[1],medals[0]] : medals;\n\n  if (top3.length === 0) {\n    podium.innerHTML = \'\';\n  } else {\n    podium.innerHTML = order.map((u, i) => `\n      <div class="podium-card ${orderClasses[i]}">\n        <div class="podium-rank">${orderMedals[i]}</div>\n        <div class="podium-name">${u.username}</div>\n        <div class="podium-pts">${u.brotherhood_points}</div>\n        <div class="podium-pts-label">Points</div>\n      </div>\n    `).join(\'\');\n  }\n\n  // Table\n  const tbody = document.getElementById(\'leaderboard-body\');\n  if (active.length === 0) {\n    tbody.innerHTML = `<tr><td colspan="6"><div class="empty-state"><div class="empty-icon">🏆</div><div class="empty-text">No members yet</div></div></td></tr>`;\n    return;\n  }\n  tbody.innerHTML = active.map((u, i) => `\n    <tr>\n      <td><span class="rank-${i+1}">${i < 3 ? [\'🥇\',\'🥈\',\'🥉\'][i] : \'#\' + (i+1)}</span></td>\n      <td style="font-family:\'Cinzel\',serif;font-size:0.85rem;">${u.username}</td>\n      <td class="text-dim" style="font-size:0.85rem;">${u.email}</td>\n      <td>${roleBadge(u.role)}</td>\n      <td><span class="points-num">${u.brotherhood_points}</span></td>\n      <td>${u.is_active ? \'<span class="badge badge-active">Active</span>\' : \'<span class="badge badge-inactive">Inactive</span>\'}</td>\n    </tr>\n  `).join(\'\');\n}\n\n// ---- SUBMIT POINTS ----\nasync function loadSubmitForm() {\n  // Load members into dropdown\n  const r = await fetch(\'/points/api/users\');\n  const users = await r.json();\n  const sel = document.getElementById(\'sub-member\');\n  sel.innerHTML = users.filter(u => u.is_active).map(u =>\n    `<option value="${u.user_id}" ${u.user_id === currentUser.user_id ? \'selected\' : \'\'}>${u.username}</option>`\n  ).join(\'\');\n\n  // Load actions into dropdown\n  const ar = await fetch(\'/points/api/actions\');\n  allActions = await ar.json();\n  const asel = document.getElementById(\'sub-action\');\n  if (allActions.length === 0) {\n    asel.innerHTML = \'<option value="">No actions defined yet</option>\';\n    asel.disabled = true;\n  } else {\n    asel.innerHTML = \'<option value="">— Select an action —</option>\' +\n      allActions.map(a => {\n        const sign = a.points > 0 ? \'+\' : \'\';\n        return `<option value="${a.action_id}" data-pts="${a.points}">${a.label} (${sign}${a.points})</option>`;\n      }).join(\'\');\n    asel.disabled = false;\n  }\n  updateActionPreview();\n}\n\nfunction onActionChange() {\n  updateActionPreview();\n}\n\nfunction updateActionPreview() {\n  const asel = document.getElementById(\'sub-action\');\n  const preview = document.getElementById(\'action-preview\');\n  const opt = asel.options[asel.selectedIndex];\n  if (!opt || !opt.value) {\n    preview.innerHTML = \'<span class="action-preview-label">Select an action to see details</span>\';\n    return;\n  }\n  const pts = parseInt(opt.dataset.pts);\n  const sign = pts > 0 ? \'+\' : \'\';\n  const cls = pts > 0 ? \'pts-positive\' : pts < 0 ? \'pts-negative\' : \'pts-zero\';\n  preview.innerHTML = `<span class="action-preview-label">${opt.text.split(\'(\')[0].trim()}</span><span class="action-pts-badge ${cls}">${sign}${pts} pts</span>`;\n}\n\nfunction toggleCustom() {\n  const checked = document.getElementById(\'sub-custom-check\').checked;\n  document.getElementById(\'custom-fields\').style.display = checked ? \'block\' : \'none\';\n  document.getElementById(\'sub-action\').disabled = checked;\n  document.getElementById(\'action-preview\').style.opacity = checked ? \'0.35\' : \'1\';\n  if (!checked) updateActionPreview();\n}\n\nasync function submitPoints() {\n  const memberId = parseInt(document.getElementById(\'sub-member\').value);\n  const isCustom = document.getElementById(\'sub-custom-check\').checked;\n\n  let points, description;\n\n  if (isCustom) {\n    description = document.getElementById(\'sub-custom-desc\').value.trim();\n    points = parseInt(document.getElementById(\'sub-custom-points\').value);\n    if (!description) { toast(\'Please enter a description\',\'error\'); return; }\n    if (isNaN(points) || points === 0) { toast(\'Please enter a valid point value\',\'error\'); return; }\n  } else {\n    const asel = document.getElementById(\'sub-action\');\n    const opt = asel.options[asel.selectedIndex];\n    if (!opt || !opt.value) { toast(\'Please select an action\',\'error\'); return; }\n    points = parseInt(opt.dataset.pts);\n    description = opt.text.split(\'(\')[0].trim();\n  }\n\n  if (!memberId) { toast(\'Please select a member\',\'error\'); return; }\n\n  const r = await fetch(\'/points/api/transactions\', {\n    method:\'POST\',\n    headers:{\'Content-Type\':\'application/json\'},\n    body:JSON.stringify({member_id: memberId, points, description})\n  });\n  const d = await r.json();\n  if (d.success) {\n    toast(\'Request submitted for review!\',\'success\');\n    document.getElementById(\'sub-action\').value = \'\';\n    document.getElementById(\'sub-custom-desc\').value = \'\';\n    document.getElementById(\'sub-custom-points\').value = \'\';\n    document.getElementById(\'sub-custom-check\').checked = false;\n    toggleCustom();\n    updateActionPreview();\n  } else {\n    toast(d.error || \'Error submitting request\',\'error\');\n  }\n}\n\n// ---- POINT ACTIONS MANAGEMENT ----\nasync function loadActions() {\n  const r = await fetch(\'/points/api/actions/all\');\n  const actions = await r.json();\n  const grid = document.getElementById(\'actions-grid\');\n  if (actions.length === 0) {\n    grid.innerHTML = \'<div class="empty-state"><div class="empty-icon">⚙</div><div class="empty-text">No actions defined yet — add one above</div></div>\';\n    return;\n  }\n  grid.innerHTML = actions.map(a => {\n    const pts = a.points;\n    const sign = pts > 0 ? \'+\' : \'\';\n    const cls = pts > 0 ? \'pts-positive\' : pts < 0 ? \'pts-negative\' : \'pts-zero\';\n    const activeRow = a.is_active ? \'\' : \' disabled-row\';\n    return `\n    <div class="action-row${activeRow}">\n      <div class="action-row-label">${a.label}</div>\n      <div class="action-row-pts"><span class="action-pts-badge ${cls}">${sign}${pts}</span></div>\n      <span class="badge ${a.is_active ? \'badge-active\' : \'badge-inactive\'}">${a.is_active ? \'Active\' : \'Disabled\'}</span>\n      <div class="action-btns">\n        <button class="btn btn-ghost btn-sm" onclick="openEditAction(${a.action_id})">Edit</button>\n        ${a.is_active\n          ? `<button class="btn btn-danger btn-sm" onclick="toggleAction(${a.action_id}, false)">Disable</button>`\n          : `<button class="btn btn-success btn-sm" onclick="toggleAction(${a.action_id}, true)">Enable</button>`}\n      </div>\n    </div>`;\n  }).join(\'\');\n}\n\nfunction openAddAction() {\n  document.getElementById(\'action-label\').value = \'\';\n  document.getElementById(\'action-points\').value = \'\';\n  document.getElementById(\'action-error\').style.display = \'none\';\n  openModal(\'modal-add-action\');\n}\nasync function createAction() {\n  const label = document.getElementById(\'action-label\').value.trim();\n  const points = document.getElementById(\'action-points\').value;\n  if (!label || points === \'\') { showErr(\'action-error\', \'Label and points are required\'); return; }\n  const r = await fetch(\'/points/api/actions\', {method:\'POST\', headers:{\'Content-Type\':\'application/json\'}, body:JSON.stringify({label, points: parseInt(points)})});\n  const d = await r.json();\n  if (d.success) { toast(\'Action created!\',\'success\'); closeModal(\'modal-add-action\'); loadActions(); }\n  else showErr(\'action-error\', d.error || \'Error\');\n}\n\nfunction openEditAction(aid) {\n  const r = fetch(\'/points/api/actions/all\').then(r => r.json()).then(actions => {\n    const a = actions.find(x => x.action_id === aid);\n    if (!a) return;\n    document.getElementById(\'edit-action-id\').value = aid;\n    document.getElementById(\'edit-action-label\').value = a.label;\n    document.getElementById(\'edit-action-points\').value = a.points;\n    document.getElementById(\'edit-action-error\').style.display = \'none\';\n    openModal(\'modal-edit-action\');\n  });\n}\nasync function saveAction() {\n  const aid = document.getElementById(\'edit-action-id\').value;\n  const label = document.getElementById(\'edit-action-label\').value.trim();\n  const points = document.getElementById(\'edit-action-points\').value;\n  if (!label || points === \'\') { showErr(\'edit-action-error\', \'Both fields required\'); return; }\n  const r = await fetch(`/points/api/actions/${aid}`, {method:\'PUT\', headers:{\'Content-Type\':\'application/json\'}, body:JSON.stringify({label, points: parseInt(points)})});\n  const d = await r.json();\n  if (d.success) { toast(\'Action updated!\',\'success\'); closeModal(\'modal-edit-action\'); loadActions(); }\n  else showErr(\'edit-action-error\', d.error || \'Error\');\n}\nasync function toggleAction(aid, active) {\n  const r = await fetch(`/points/api/actions/${aid}`, {method:\'PUT\', headers:{\'Content-Type\':\'application/json\'}, body:JSON.stringify({is_active: active})});\n  const d = await r.json();\n  if (d.success) { toast(active ? \'Action enabled\' : \'Action disabled\',\'info\'); loadActions(); }\n  else toast(\'Error\',\'error\');\n}\n\n// ---- MY TRANSACTIONS ----\nasync function loadMyTransactions() {\n  const r = await fetch(\'/points/api/transactions\');\n  const txs = await r.json();\n  const tbody = document.getElementById(\'my-tx-body\');\n  if (txs.length === 0) {\n    tbody.innerHTML = `<tr><td colspan="6"><div class="empty-state"><div class="empty-icon">📋</div><div class="empty-text">No requests submitted yet</div></div></td></tr>`;\n    return;\n  }\n  tbody.innerHTML = txs.map(t => `\n    <tr>\n      <td class="text-dim">#${t.transaction_id}</td>\n      <td><span class="points-num">+${t.points}</span></td>\n      <td class="truncate" title="${t.description}">${t.description}</td>\n      <td>${statusBadge(t.status)}</td>\n      <td class="text-dim" style="font-size:0.8rem;">${fmtDate(t.created_at)}</td>\n      <td class="text-dim" style="font-size:0.8rem;">${t.reviewed_by || \'—\'}</td>\n    </tr>\n  `).join(\'\');\n}\n\n// ---- PENDING ----\nasync function loadPending() {\n  const r = await fetch(\'/points/api/transactions/pending\');\n  const txs = await r.json();\n  const badge = document.getElementById(\'pending-count\');\n  badge.textContent = txs.length;\n  badge.style.display = txs.length > 0 ? \'inline\' : \'none\';\n\n  const tbody = document.getElementById(\'pending-body\');\n  if (txs.length === 0) {\n    tbody.innerHTML = `<tr><td colspan="6"><div class="empty-state"><div class="empty-icon">✓</div><div class="empty-text">All caught up — no pending requests</div></div></td></tr>`;\n    return;\n  }\n  tbody.innerHTML = txs.map(t => `\n    <tr>\n      <td class="text-dim">#${t.transaction_id}</td>\n      <td style="font-family:\'Cinzel\',serif;font-size:0.85rem;">${t.member_name}</td>\n      <td><span class="points-num">+${t.points}</span></td>\n      <td class="truncate" title="${t.description}">${t.description}</td>\n      <td class="text-dim" style="font-size:0.8rem;">${fmtDate(t.created_at)}</td>\n      <td>\n        <div class="action-btns">\n          <button class="btn btn-success btn-sm" onclick="approveTransaction(${t.transaction_id})">✓ Approve</button>\n          <button class="btn btn-danger btn-sm" onclick="openReject(${t.transaction_id})">✕ Reject</button>\n        </div>\n      </td>\n    </tr>\n  `).join(\'\');\n}\n\nasync function approveTransaction(tid) {\n  const r = await fetch(`/points/api/transactions/${tid}/approve`, {method:\'POST\'});\n  const d = await r.json();\n  if (d.success) { toast(\'Transaction approved!\',\'success\'); loadPending(); loadLeaderboard(); }\n  else toast(d.error||\'Error\',\'error\');\n}\n\nfunction openReject(tid) {\n  document.getElementById(\'reject-tid\').value = tid;\n  document.getElementById(\'reject-reason\').value = \'\';\n  openModal(\'modal-reject\');\n}\nasync function confirmReject() {\n  const tid = document.getElementById(\'reject-tid\').value;\n  const reason = document.getElementById(\'reject-reason\').value.trim();\n  if (!reason) { toast(\'Please provide a reason\',\'error\'); return; }\n  const r = await fetch(`/points/api/transactions/${tid}/reject`, {method:\'POST\', headers:{\'Content-Type\':\'application/json\'}, body:JSON.stringify({reason})});\n  const d = await r.json();\n  if (d.success) { toast(\'Request rejected\',\'info\'); closeModal(\'modal-reject\'); loadPending(); }\n  else toast(d.error||\'Error\',\'error\');\n}\n\n// ---- ALL TRANSACTIONS ----\nasync function loadAllTransactions() {\n  const r = await fetch(\'/points/api/transactions\');\n  allTransactions = await r.json();\n  renderAllTransactions(allTransactions);\n}\nfunction renderAllTransactions(txs) {\n  const tbody = document.getElementById(\'all-tx-body\');\n  if (txs.length === 0) {\n    tbody.innerHTML = `<tr><td colspan="7"><div class="empty-state"><div class="empty-text">No transactions found</div></div></td></tr>`;\n    return;\n  }\n  tbody.innerHTML = txs.map(t => `\n    <tr>\n      <td class="text-dim">#${t.transaction_id}</td>\n      <td style="font-family:\'Cinzel\',serif;font-size:0.85rem;">${t.member_name}</td>\n      <td><span class="points-num">+${t.points}</span></td>\n      <td class="truncate" title="${t.description}">${t.description}</td>\n      <td>${statusBadge(t.status)}</td>\n      <td class="text-dim" style="font-size:0.8rem;">${fmtDate(t.created_at)}</td>\n      <td class="text-dim" style="font-size:0.8rem;">${t.reviewed_by || \'—\'}</td>\n    </tr>\n  `).join(\'\');\n}\nfunction filterTransactions() {\n  const q = document.getElementById(\'tx-search\').value.toLowerCase();\n  renderAllTransactions(allTransactions.filter(t =>\n    t.member_name.toLowerCase().includes(q) || t.description.toLowerCase().includes(q)\n  ));\n}\n\n// ---- USERS ----\nasync function loadUsers() {\n  const r = await fetch(\'/points/api/users\');\n  allUsers = await r.json();\n  renderUsers(allUsers);\n}\nfunction renderUsers(users) {\n  const tbody = document.getElementById(\'users-body\');\n  if (users.length === 0) {\n    tbody.innerHTML = `<tr><td colspan="8"><div class="empty-state"><div class="empty-text">No users found</div></div></td></tr>`;\n    return;\n  }\n  tbody.innerHTML = users.map(u => `\n    <tr>\n      <td class="text-dim">${u.user_id}</td>\n      <td style="font-family:\'Cinzel\',serif;font-size:0.85rem;">${u.username}</td>\n      <td class="text-dim" style="font-size:0.85rem;">${u.email}</td>\n      <td>${roleBadge(u.role)}</td>\n      <td><span class="points-num">${u.brotherhood_points}</span></td>\n      <td>${u.is_active ? \'<span class="badge badge-active">Active</span>\' : \'<span class="badge badge-inactive">Inactive</span>\'}</td>\n      <td class="text-dim" style="font-size:0.8rem;">${fmtDate(u.created_at)}</td>\n      <td>\n        <div class="action-btns">\n          <button class="btn btn-ghost btn-sm" onclick="openEditUser(${u.user_id})">Edit</button>\n          ${u.is_active ? `<button class="btn btn-danger btn-sm" onclick="deactivateUser(${u.user_id})">Deactivate</button>` : \'\'}\n        </div>\n      </td>\n    </tr>\n  `).join(\'\');\n}\nfunction filterUsers() {\n  const q = document.getElementById(\'user-search\').value.toLowerCase();\n  renderUsers(allUsers.filter(u => u.username.toLowerCase().includes(q) || u.email.toLowerCase().includes(q)));\n}\n\nfunction openAddUser() {\n  [\'add-username\',\'add-email\',\'add-password\'].forEach(id => document.getElementById(id).value = \'\');\n  document.getElementById(\'add-role\').value = \'member\';\n  document.getElementById(\'add-error\').style.display = \'none\';\n  openModal(\'modal-add-user\');\n}\nasync function createUser() {\n  const data = {\n    username: document.getElementById(\'add-username\').value.trim(),\n    email: document.getElementById(\'add-email\').value.trim(),\n    password: document.getElementById(\'add-password\').value,\n    role: document.getElementById(\'add-role\').value\n  };\n  if (!data.username || !data.email || !data.password) { showErr(\'add-error\',\'All fields are required\'); return; }\n  const r = await fetch(\'/points/api/users\', {method:\'POST\', headers:{\'Content-Type\':\'application/json\'}, body:JSON.stringify(data)});\n  const d = await r.json();\n  if (d.success) { toast(\'Member created!\',\'success\'); closeModal(\'modal-add-user\'); loadUsers(); }\n  else showErr(\'add-error\', d.error||\'Error creating user\');\n}\n\nfunction openEditUser(uid) {\n  const u = allUsers.find(x => x.user_id === uid);\n  if (!u) return;\n  document.getElementById(\'edit-uid\').value = uid;\n  document.getElementById(\'edit-username\').value = u.username;\n  document.getElementById(\'edit-email\').value = u.email;\n  document.getElementById(\'edit-password\').value = \'\';\n  document.getElementById(\'edit-role\').value = u.role;\n  document.getElementById(\'edit-active\').value = u.is_active ? \'1\' : \'0\';\n  document.getElementById(\'edit-error\').style.display = \'none\';\n  openModal(\'modal-edit-user\');\n}\nasync function saveUser() {\n  const uid = document.getElementById(\'edit-uid\').value;\n  const data = {\n    username: document.getElementById(\'edit-username\').value.trim(),\n    email: document.getElementById(\'edit-email\').value.trim(),\n    role: document.getElementById(\'edit-role\').value,\n    is_active: parseInt(document.getElementById(\'edit-active\').value),\n    password: document.getElementById(\'edit-password\').value\n  };\n  const r = await fetch(`/points/api/users/${uid}`, {method:\'PUT\', headers:{\'Content-Type\':\'application/json\'}, body:JSON.stringify(data)});\n  const d = await r.json();\n  if (d.success) { toast(\'Member updated!\',\'success\'); closeModal(\'modal-edit-user\'); loadUsers(); }\n  else showErr(\'edit-error\', d.error||\'Error saving user\');\n}\n\nasync function deactivateUser(uid) {\n  if (!confirm(\'Deactivate this member?\')) return;\n  const r = await fetch(`/points/api/users/${uid}`, {method:\'DELETE\'});\n  const d = await r.json();\n  if (d.success) { toast(\'Member deactivated\',\'info\'); loadUsers(); }\n  else toast(\'Error\',\'error\');\n}\n\nfunction showErr(id, msg) {\n  const el = document.getElementById(id);\n  el.textContent = msg;\n  el.style.display = \'block\';\n}\n\n// Enter key on login\ndocument.getElementById(\'login-password\').addEventListener(\'keydown\', e => { if (e.key === \'Enter\') doLogin(); });\ndocument.getElementById(\'login-username\').addEventListener(\'keydown\', e => { if (e.key === \'Enter\') doLogin(); });\n\n// Close modals on overlay click\ndocument.querySelectorAll(\'.modal-overlay\').forEach(o => {\n  o.addEventListener(\'click\', e => { if (e.target === o) o.classList.remove(\'show\'); });\n});\n\n// Check session on load\n(async () => {\n  const r = await fetch(\'/points/api/me\');\n  const d = await r.json();\n  if (d.authenticated) {\n    await loadApp();\n  }\n})();\n</script>\n</body>\n</html>'
BUDGET_HTML  = '<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="UTF-8">\n<meta name="viewport" content="width=device-width, initial-scale=1.0">\n<title>Δ Τ Δ Budget System</title>\n<link href="https://fonts.googleapis.com/css2?family=Cinzel+Decorative:wght@700;900&family=Cinzel:wght@400;600;700&family=Crimson+Pro:ital,wght@0,300;0,400;0,600;1,300;1,400&display=swap" rel="stylesheet">\n<style>\n:root {\n  --purple: #3D0C45; --purple-mid: #5C1F6B; --purple-light: #7B3094;\n  --gold: #C9A84C; --gold-bright: #E8C96A; --gold-dim: #8A7235;\n  --dark: #0D0910; --dark-2: #150D1A; --dark-3: #1E1227; --dark-4: #261630;\n  --surface: #1A0F21; --surface-2: #231428;\n  --border: rgba(201,168,76,0.18); --border-strong: rgba(201,168,76,0.38);\n  --text: #F0E8D0; --text-dim: #9A8E7A; --text-muted: #5C5248;\n  --green: #4CAF7A; --red: #CF4A4A; --blue: #5B8DD9;\n  --radius: 4px; --radius-lg: 8px;\n}\n*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}\nbody{background:var(--dark);color:var(--text);font-family:\'Crimson Pro\',Georgia,serif;font-size:16px;line-height:1.6;min-height:100vh;overflow-x:hidden}\nbody::before{content:\'\';position:fixed;inset:0;background-image:url("data:image/svg+xml,%3Csvg viewBox=\'0 0 256 256\' xmlns=\'http://www.w3.org/2000/svg\'%3E%3Cfilter id=\'n\'%3E%3CfeTurbulence type=\'fractalNoise\' baseFrequency=\'0.9\' numOctaves=\'4\' stitchTiles=\'stitch\'/%3E%3C/filter%3E%3Crect width=\'100%25\' height=\'100%25\' filter=\'url(%23n)\' opacity=\'0.04\'/%3E%3C/svg%3E");pointer-events:none;z-index:0;opacity:.6}\n::-webkit-scrollbar{width:6px}::-webkit-scrollbar-track{background:var(--dark-2)}::-webkit-scrollbar-thumb{background:var(--purple-mid);border-radius:3px}\n#app{position:relative;z-index:1}\n\n/* LOGIN */\n#login-screen{display:flex;align-items:center;justify-content:center;min-height:100vh;padding:2rem;background:radial-gradient(ellipse at 50% 0%,rgba(92,31,107,.4) 0%,transparent 70%),radial-gradient(ellipse at 80% 100%,rgba(61,12,69,.3) 0%,transparent 60%)}\n.login-card{width:100%;max-width:420px;background:var(--surface);border:1px solid var(--border-strong);padding:3rem 2.5rem;position:relative;box-shadow:0 0 80px rgba(92,31,107,.3),0 0 0 1px rgba(201,168,76,.08)}\n.login-card::before,.login-card::after{content:\'\';position:absolute;width:24px;height:24px;border-color:var(--gold);border-style:solid}\n.login-card::before{top:-1px;left:-1px;border-width:2px 0 0 2px}\n.login-card::after{bottom:-1px;right:-1px;border-width:0 2px 2px 0}\n.crest{text-align:center;margin-bottom:2rem}\n.crest-symbol{font-family:\'Cinzel Decorative\',serif;font-size:3.5rem;color:var(--gold);display:block;line-height:1;text-shadow:0 0 40px rgba(201,168,76,.4);letter-spacing:.1em}\n.crest-name{font-family:\'Cinzel\',serif;font-size:.75rem;letter-spacing:.35em;color:var(--gold-dim);text-transform:uppercase;margin-top:.5rem}\n.crest-sub{font-family:\'Crimson Pro\',serif;font-style:italic;font-size:1rem;color:var(--text-dim);margin-top:.3rem}\n\n/* FORMS */\n.form-group{margin-bottom:1.25rem}\n.form-label{display:block;font-family:\'Cinzel\',serif;font-size:.65rem;letter-spacing:.2em;color:var(--gold-dim);text-transform:uppercase;margin-bottom:.5rem}\n.form-input{width:100%;background:var(--dark-3);border:1px solid var(--border);color:var(--text);padding:.75rem 1rem;font-family:\'Crimson Pro\',serif;font-size:1rem;outline:none;border-radius:var(--radius);transition:border-color .2s,box-shadow .2s}\n.form-input:focus{border-color:var(--gold);box-shadow:0 0 0 2px rgba(201,168,76,.12)}\n.form-input::placeholder{color:var(--text-muted)}\n.form-input:disabled{opacity:.45;cursor:not-allowed}\nselect.form-input option{background:var(--dark-3)}\ntextarea.form-input{resize:vertical;min-height:80px}\n.error-msg{color:var(--red);font-size:.875rem;margin-top:.5rem;display:none;font-style:italic}\n\n/* BUTTONS */\n.btn{display:inline-flex;align-items:center;gap:.5rem;padding:.75rem 1.5rem;font-family:\'Cinzel\',serif;font-size:.7rem;letter-spacing:.15em;text-transform:uppercase;cursor:pointer;border:none;border-radius:var(--radius);transition:all .2s;font-weight:600}\n.btn-primary{background:linear-gradient(135deg,var(--purple-mid),var(--purple));color:var(--gold);border:1px solid var(--border-strong);width:100%;justify-content:center;padding:.9rem}\n.btn-primary:hover{background:linear-gradient(135deg,var(--purple-light),var(--purple-mid));box-shadow:0 4px 20px rgba(92,31,107,.5)}\n.btn-sm{padding:.4rem .9rem;font-size:.6rem}\n.btn-ghost{background:transparent;color:var(--text-dim);border:1px solid var(--border)}\n.btn-ghost:hover{border-color:var(--gold);color:var(--gold)}\n.btn-danger{background:rgba(207,74,74,.15);color:var(--red);border:1px solid rgba(207,74,74,.3)}\n.btn-danger:hover{background:rgba(207,74,74,.25)}\n.btn-success{background:rgba(76,175,122,.15);color:var(--green);border:1px solid rgba(76,175,122,.3)}\n.btn-success:hover{background:rgba(76,175,122,.25)}\n.btn-gold{background:linear-gradient(135deg,var(--gold),var(--gold-dim));color:var(--dark);border:none}\n.btn-gold:hover{filter:brightness(1.1)}\n\n/* TOPBAR */\n#main-app{display:none;flex-direction:column;min-height:100vh}\n.topbar{background:linear-gradient(180deg,var(--purple) 0%,var(--dark-2) 100%);border-bottom:1px solid var(--border-strong);padding:0 2rem;height:60px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:100;box-shadow:0 2px 20px rgba(0,0,0,.4)}\n.topbar-brand{display:flex;align-items:center;gap:1rem}\n.topbar-symbol{font-family:\'Cinzel Decorative\',serif;font-size:1.4rem;color:var(--gold);text-shadow:0 0 20px rgba(201,168,76,.5)}\n.topbar-title{font-family:\'Cinzel\',serif;font-size:.7rem;letter-spacing:.25em;color:var(--gold-dim);text-transform:uppercase}\n.topbar-sub{font-family:\'Crimson Pro\',serif;font-style:italic;font-size:.8rem;color:var(--text-muted);margin-left:.5rem}\n.topbar-user{display:flex;align-items:center;gap:1rem;font-size:.875rem}\n.user-badge{display:flex;align-items:center;gap:.6rem;background:rgba(201,168,76,.08);border:1px solid var(--border);padding:.35rem .9rem;border-radius:20px}\n.user-name{font-family:\'Cinzel\',serif;font-size:.7rem;color:var(--gold);letter-spacing:.1em}\n.role-tag{font-size:.6rem;letter-spacing:.15em;text-transform:uppercase;padding:.15rem .5rem;border-radius:20px;font-family:\'Cinzel\',serif}\n.role-admin{background:rgba(201,168,76,.2);color:var(--gold);border:1px solid var(--gold-dim)}\n.role-moderator{background:rgba(192,132,208,.15);color:#C084D0;border:1px solid var(--purple-light)}\n.role-member{background:rgba(255,255,255,.06);color:var(--text-dim);border:1px solid var(--border)}\n\n/* LAYOUT */\n.app-body{display:flex;flex:1}\n.sidebar{width:230px;background:var(--dark-2);border-right:1px solid var(--border);padding:1.5rem 0;flex-shrink:0;position:sticky;top:60px;height:calc(100vh - 60px);overflow-y:auto}\n.nav-section-title{font-family:\'Cinzel\',serif;font-size:.55rem;letter-spacing:.3em;color:var(--text-muted);text-transform:uppercase;padding:0 1.5rem;margin-bottom:.5rem;margin-top:1.5rem}\n.nav-item{display:flex;align-items:center;gap:.75rem;padding:.65rem 1.5rem;cursor:pointer;transition:all .15s;color:var(--text-dim);font-size:.9rem;border-left:3px solid transparent}\n.nav-item:hover{background:rgba(201,168,76,.05);color:var(--text)}\n.nav-item.active{color:var(--gold);background:rgba(201,168,76,.08);border-left-color:var(--gold)}\n.nav-item .icon{font-size:1rem;width:20px;text-align:center}\n.nav-badge{margin-left:auto;background:var(--red);color:white;font-size:.6rem;font-family:\'Cinzel\',serif;padding:.1rem .4rem;border-radius:10px;min-width:18px;text-align:center}\n.nav-divider{height:1px;background:var(--border);margin:1rem 1.5rem}\n.nav-dept{padding:.5rem 1.5rem .5rem 2.5rem;font-size:.85rem;color:var(--text-muted);cursor:pointer;transition:all .15s;border-left:3px solid transparent;display:flex;align-items:center;gap:.5rem}\n.nav-dept:hover{color:var(--text-dim);background:rgba(255,255,255,.03)}\n.nav-dept.active{color:var(--gold-dim);border-left-color:var(--gold-dim)}\n.nav-dept-dot{width:5px;height:5px;border-radius:50%;background:currentColor;flex-shrink:0}\n\n/* CONTENT */\n.content{flex:1;padding:2rem;overflow-x:auto;min-width:0}\n.page{display:none}.page.active{display:block}\n\n/* PAGE HEADER */\n.page-header{margin-bottom:2rem;padding-bottom:1.25rem;border-bottom:1px solid var(--border);display:flex;align-items:flex-end;justify-content:space-between;gap:1rem;flex-wrap:wrap}\n.page-title{font-family:\'Cinzel\',serif;font-size:1.5rem;color:var(--gold);letter-spacing:.05em}\n.page-subtitle{font-style:italic;color:var(--text-dim);font-size:.875rem;margin-top:.25rem}\n\n/* CARDS */\n.card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);padding:1.5rem;margin-bottom:1.5rem}\n.card-title{font-family:\'Cinzel\',serif;font-size:.8rem;letter-spacing:.15em;color:var(--gold-dim);text-transform:uppercase;margin-bottom:1.25rem;padding-bottom:.75rem;border-bottom:1px solid var(--border)}\n\n/* STAT CARDS */\n.stats-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:1rem;margin-bottom:2rem}\n.stat-card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);padding:1.25rem 1.5rem;position:relative;overflow:hidden}\n.stat-card::before{content:\'\';position:absolute;top:0;left:0;right:0;height:2px;background:linear-gradient(90deg,var(--gold-dim),var(--gold))}\n.stat-card.stat-spent::before{background:linear-gradient(90deg,#8B1A1A,var(--red))}\n.stat-card.stat-remaining::before{background:linear-gradient(90deg,#1A5C35,var(--green))}\n.stat-card.stat-pending::before{background:linear-gradient(90deg,var(--gold-dim),var(--gold-bright))}\n.stat-label{font-family:\'Cinzel\',serif;font-size:.6rem;letter-spacing:.2em;color:var(--text-muted);text-transform:uppercase}\n.stat-value{font-family:\'Cinzel Decorative\',serif;font-size:1.7rem;color:var(--gold);line-height:1.2;margin:.3rem 0}\n.stat-value.red{color:var(--red)}.stat-value.green{color:var(--green)}\n.stat-sub{font-size:.8rem;color:var(--text-dim);font-style:italic}\n\n/* BUDGET BAR */\n.budget-bar-wrap{margin:1rem 0}\n.budget-bar-labels{display:flex;justify-content:space-between;font-size:.75rem;color:var(--text-dim);margin-bottom:.4rem;font-family:\'Cinzel\',serif}\n.budget-bar-track{height:8px;background:var(--dark-3);border-radius:4px;overflow:hidden;position:relative}\n.budget-bar-fill{height:100%;border-radius:4px;transition:width .4s ease;background:linear-gradient(90deg,var(--green),#7DD69A)}\n.budget-bar-fill.warn{background:linear-gradient(90deg,#B8860B,var(--gold))}\n.budget-bar-fill.over{background:linear-gradient(90deg,#8B1A1A,var(--red))}\n.budget-bar-pending{height:100%;border-radius:4px;position:absolute;top:0;background:rgba(201,168,76,.35)}\n\n/* TABLE */\n.table-wrap{overflow-x:auto}\ntable{width:100%;border-collapse:collapse;font-size:.9rem}\nthead tr{border-bottom:1px solid var(--border-strong)}\nth{font-family:\'Cinzel\',serif;font-size:.6rem;letter-spacing:.18em;color:var(--gold-dim);text-transform:uppercase;padding:.75rem 1rem;text-align:left;font-weight:600;white-space:nowrap}\ntd{padding:.75rem 1rem;border-bottom:1px solid var(--border);color:var(--text);vertical-align:middle}\ntr:last-child td{border-bottom:none}\ntbody tr{transition:background .15s}\ntbody tr:hover{background:rgba(201,168,76,.04)}\n\n/* BADGES */\n.badge{display:inline-block;padding:.2rem .6rem;border-radius:20px;font-size:.65rem;font-family:\'Cinzel\',serif;letter-spacing:.08em;text-transform:uppercase;font-weight:600}\n.badge-pending{background:rgba(201,168,76,.15);color:var(--gold);border:1px solid rgba(201,168,76,.3)}\n.badge-approved{background:rgba(76,175,122,.15);color:var(--green);border:1px solid rgba(76,175,122,.3)}\n.badge-rejected{background:rgba(207,74,74,.15);color:var(--red);border:1px solid rgba(207,74,74,.3)}\n.money{font-family:\'Cinzel\',serif;color:var(--gold);font-size:.9rem}\n.money.red{color:var(--red)}.money.green{color:var(--green)}\n\n/* DEPT VIEW */\n.dept-header{background:linear-gradient(135deg,var(--purple) 0%,var(--dark-2) 100%);border:1px solid var(--border-strong);border-radius:var(--radius-lg);padding:1.75rem 2rem;margin-bottom:1.5rem;position:relative;overflow:hidden}\n.dept-header::after{content:\'ΔΤΔ\';position:absolute;right:2rem;top:50%;transform:translateY(-50%);font-family:\'Cinzel Decorative\',serif;font-size:4rem;color:rgba(201,168,76,.06);pointer-events:none}\n.dept-header-name{font-family:\'Cinzel\',serif;font-size:1.4rem;color:var(--gold);letter-spacing:.08em}\n.dept-header-desc{font-style:italic;color:var(--text-dim);margin-top:.25rem}\n\n/* ITEMS GRID */\n.items-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:1rem;margin-bottom:1.5rem}\n.item-card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);padding:1.25rem;cursor:pointer;transition:all .2s;position:relative}\n.item-card:hover{border-color:var(--gold-dim);transform:translateY(-2px);box-shadow:0 4px 20px rgba(0,0,0,.3)}\n.item-card.selected{border-color:var(--gold);box-shadow:0 0 0 1px var(--gold-dim)}\n.item-card-name{font-family:\'Cinzel\',serif;font-size:.85rem;letter-spacing:.05em;margin-bottom:.75rem}\n.item-figures{display:flex;justify-content:space-between;font-size:.8rem;margin-top:.5rem}\n.item-fig-label{color:var(--text-muted);font-size:.65rem;text-transform:uppercase;font-family:\'Cinzel\',serif;letter-spacing:.1em}\n.item-fig-val{font-family:\'Cinzel\',serif}\n\n/* MODAL */\n.modal-overlay{position:fixed;inset:0;background:rgba(0,0,0,.7);backdrop-filter:blur(4px);display:flex;align-items:center;justify-content:center;z-index:200;padding:1rem;opacity:0;pointer-events:none;transition:opacity .2s}\n.modal-overlay.show{opacity:1;pointer-events:all}\n.modal{background:var(--surface);border:1px solid var(--border-strong);border-radius:var(--radius-lg);width:100%;max-width:500px;max-height:90vh;overflow-y:auto;transform:translateY(20px);transition:transform .2s}\n.modal-overlay.show .modal{transform:translateY(0)}\n.modal-header{background:linear-gradient(135deg,var(--purple) 0%,var(--dark-2) 100%);padding:1.25rem 1.5rem;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between}\n.modal-title{font-family:\'Cinzel\',serif;font-size:.85rem;letter-spacing:.15em;color:var(--gold);text-transform:uppercase}\n.modal-close{background:none;border:none;color:var(--text-dim);font-size:1.2rem;cursor:pointer;padding:.25rem}\n.modal-close:hover{color:var(--text)}\n.modal-body{padding:1.5rem}\n.modal-footer{padding:1rem 1.5rem;border-top:1px solid var(--border);display:flex;gap:.75rem;justify-content:flex-end}\n\n/* TOAST */\n#toast-container{position:fixed;top:1rem;right:1rem;z-index:9999;display:flex;flex-direction:column;gap:.5rem}\n.toast{background:var(--surface);border:1px solid var(--border);padding:.8rem 1.2rem;border-radius:var(--radius);font-size:.875rem;display:flex;align-items:center;gap:.75rem;min-width:280px;box-shadow:0 4px 20px rgba(0,0,0,.4);animation:slideIn .3s ease}\n.toast.success{border-left:3px solid var(--green)}.toast.error{border-left:3px solid var(--red)}.toast.info{border-left:3px solid var(--gold)}\n@keyframes slideIn{from{transform:translateX(100%);opacity:0}to{transform:none;opacity:1}}\n\n/* MISC */\n.search-bar{display:flex;gap:.75rem;margin-bottom:1rem;flex-wrap:wrap;align-items:center}\n.search-input{background:var(--dark-3);border:1px solid var(--border);color:var(--text);padding:.5rem 1rem;font-family:\'Crimson Pro\',serif;font-size:.9rem;outline:none;border-radius:var(--radius);min-width:220px;transition:border-color .2s}\n.search-input:focus{border-color:var(--gold-dim)}\n.search-input::placeholder{color:var(--text-muted)}\n.empty-state{text-align:center;padding:3rem;color:var(--text-muted)}\n.empty-icon{font-size:2.5rem;margin-bottom:1rem}.empty-text{font-style:italic}\n.action-btns{display:flex;gap:.4rem;flex-wrap:wrap}\n.text-dim{color:var(--text-dim)}.text-gold{color:var(--gold)}.truncate{max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}\n.row-info{font-size:.75rem;color:var(--text-muted);font-style:italic;margin-top:.2rem}\n\n@media(max-width:768px){.sidebar{display:none}.content{padding:1rem}.items-grid{grid-template-columns:1fr}.stats-row{grid-template-columns:1fr 1fr}}\n</style>\n</head>\n<body>\n<div id="app">\n\n<!-- LOGIN -->\n<div id="login-screen">\n  <div class="login-card">\n    <div class="crest">\n      <span class="crest-symbol">ΔΤΔ</span>\n      <div class="crest-name">Delta Tau Delta</div>\n      <div class="crest-sub">Budget &amp; Bookkeeping</div>\n    </div>\n    <div class="form-group">\n      <label class="form-label">Username</label>\n      <input class="form-input" type="text" id="login-username" placeholder="Enter your username" autocomplete="username">\n    </div>\n    <div class="form-group">\n      <label class="form-label">Password</label>\n      <input class="form-input" type="password" id="login-password" placeholder="••••••••" autocomplete="current-password">\n    </div>\n    <div class="error-msg" id="login-error">Invalid credentials or inactive account.</div>\n    <button class="btn btn-primary" id="login-btn" onclick="doLogin()">Sign In to Treasury</button>\n  </div>\n</div>\n\n<!-- MAIN APP -->\n<div id="main-app">\n  <div class="topbar">\n    <div class="topbar-brand">\n      <span class="topbar-symbol">ΔΤΔ</span>\n      <span class="topbar-title">Treasury</span>\n      <span class="topbar-sub">Budget &amp; Bookkeeping</span>\n    </div>\n    <div class="topbar-nav-links" style="display:flex;gap:.5rem;margin-left:1.5rem">\n      <a href="/points" style="font-family:\'Cinzel\',serif;font-size:.65rem;letter-spacing:.15em;color:var(--text-dim);text-decoration:none;padding:.35rem .8rem;border:1px solid var(--border);border-radius:4px">⚔ Points</a>\n      <a href="/budget" style="font-family:\'Cinzel\',serif;font-size:.65rem;letter-spacing:.15em;color:var(--gold);text-decoration:none;padding:.35rem .8rem;border:1px solid var(--gold-dim);border-radius:4px;background:rgba(201,168,76,.12)">◈ Budget</a>\n    </div>\n    <div class="topbar-user">\n      <div class="user-badge">\n        <span class="user-name" id="topbar-username"></span>\n        <span class="role-tag" id="topbar-role"></span>\n      </div>\n      <button class="btn btn-ghost btn-sm" onclick="doLogout()">Sign Out</button>\n    </div>\n  </div>\n\n  <div class="app-body">\n    <nav class="sidebar">\n      <div class="nav-section-title">Overview</div>\n      <div class="nav-item active" onclick="showPage(\'overview\',this)" id="nav-overview">\n        <span class="icon">◈</span> Dashboard\n      </div>\n      <div class="nav-item" onclick="showPage(\'submit\',this)" id="nav-submit">\n        <span class="icon">✦</span> Submit Request\n      </div>\n      <div class="nav-item" onclick="showPage(\'my-requests\',this)" id="nav-my">\n        <span class="icon">📋</span> My Requests\n      </div>\n\n      <div class="nav-divider"></div>\n      <div class="nav-section-title" id="mod-label" style="display:none">Moderation</div>\n      <div class="nav-item" onclick="showPage(\'pending\',this)" id="nav-pending" style="display:none">\n        <span class="icon">⏳</span> Pending\n        <span class="nav-badge" id="pending-badge" style="display:none">0</span>\n      </div>\n\n      <div class="nav-divider"></div>\n      <div class="nav-section-title">Departments</div>\n      <div id="dept-nav-list"></div>\n\n      <div class="nav-divider" id="admin-divider" style="display:none"></div>\n      <div class="nav-section-title" id="admin-label" style="display:none">Admin</div>\n      <div class="nav-item" onclick="showPage(\'manage-depts\',this)" id="nav-manage" style="display:none">\n        <span class="icon">⚙</span> Manage Depts &amp; Items\n      </div>\n    </nav>\n\n    <main class="content">\n\n      <!-- OVERVIEW -->\n      <div class="page active" id="page-overview">\n        <div class="page-header">\n          <div><div class="page-title">Treasury Overview</div><div class="page-subtitle">Total budget status across all departments</div></div>\n          <button class="btn btn-ghost btn-sm" onclick="loadOverview()">↻ Refresh</button>\n        </div>\n        <div class="stats-row" id="overview-stats"></div>\n        <div class="card">\n          <div class="card-title">Departments at a Glance</div>\n          <div class="table-wrap">\n            <table>\n              <thead><tr><th>Department</th><th>Total Budget</th><th>Spent</th><th>Remaining</th><th>Usage</th></tr></thead>\n              <tbody id="overview-depts-body"></tbody>\n            </table>\n          </div>\n        </div>\n      </div>\n\n      <!-- SUBMIT REQUEST -->\n      <div class="page" id="page-submit">\n        <div class="page-header">\n          <div><div class="page-title">Submit Budget Request</div><div class="page-subtitle">Request funds from a department budget line</div></div>\n        </div>\n        <div class="card" style="max-width:580px">\n          <div class="card-title">New Request</div>\n          <div class="form-group">\n            <label class="form-label">Department</label>\n            <select class="form-input" id="req-dept" onchange="onDeptChange()">\n              <option value="">— Select a department —</option>\n            </select>\n          </div>\n          <div class="form-group">\n            <label class="form-label">Budget Line Item</label>\n            <select class="form-input" id="req-item" disabled onchange="onItemChange()">\n              <option value="">— Select a budget item —</option>\n            </select>\n            <div id="item-budget-preview" style="margin-top:.5rem;display:none">\n              <div class="budget-bar-wrap" id="item-bar-wrap"></div>\n            </div>\n          </div>\n          <div class="form-group">\n            <label class="form-label">Amount ($)</label>\n            <input class="form-input" type="number" id="req-amount" min="0.01" step="0.01" placeholder="0.00">\n          </div>\n          <div class="form-group">\n            <label class="form-label">Description / Purpose</label>\n            <textarea class="form-input" id="req-desc" placeholder="What is this expense for?"></textarea>\n          </div>\n          <div class="form-group">\n            <label class="form-label">Vendor / Payee <span class="text-dim">(optional)</span></label>\n            <input class="form-input" type="text" id="req-vendor" placeholder="e.g. Amazon, Home Depot">\n          </div>\n          <button class="btn btn-gold" onclick="submitRequest()">✦ Submit for Approval</button>\n        </div>\n      </div>\n\n      <!-- MY REQUESTS -->\n      <div class="page" id="page-my-requests">\n        <div class="page-header">\n          <div><div class="page-title">My Requests</div><div class="page-subtitle">Track your submitted budget requests</div></div>\n          <button class="btn btn-ghost btn-sm" onclick="loadMyRequests()">↻ Refresh</button>\n        </div>\n        <div class="card">\n          <div class="table-wrap">\n            <table>\n              <thead><tr><th>ID</th><th>Dept</th><th>Item</th><th>Amount</th><th>Description</th><th>Status</th><th>Submitted</th></tr></thead>\n              <tbody id="my-req-body"></tbody>\n            </table>\n          </div>\n        </div>\n      </div>\n\n      <!-- PENDING MODERATION -->\n      <div class="page" id="page-pending">\n        <div class="page-header">\n          <div><div class="page-title">Pending Requests</div><div class="page-subtitle">Review and approve or reject budget requests</div></div>\n          <button class="btn btn-ghost btn-sm" onclick="loadPending()">↻ Refresh</button>\n        </div>\n        <div class="card">\n          <div class="table-wrap">\n            <table>\n              <thead><tr><th>ID</th><th>Member</th><th>Dept</th><th>Item</th><th>Amount</th><th>Description</th><th>Vendor</th><th>Submitted</th><th>Actions</th></tr></thead>\n              <tbody id="pending-body"></tbody>\n            </table>\n          </div>\n        </div>\n      </div>\n\n      <!-- DEPARTMENT VIEW -->\n      <div class="page" id="page-dept">\n        <div id="dept-view-header" class="dept-header">\n          <div class="dept-header-name" id="dept-view-name">Department</div>\n          <div class="dept-header-desc" id="dept-view-desc"></div>\n        </div>\n        <div class="stats-row" id="dept-stats"></div>\n        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:1rem;flex-wrap:wrap;gap:.5rem">\n          <span style="font-family:\'Cinzel\',serif;font-size:.75rem;letter-spacing:.15em;color:var(--gold-dim);text-transform:uppercase">Budget Line Items</span>\n          <button class="btn btn-ghost btn-sm" id="btn-add-item-dept" style="display:none" onclick="openAddItemFromDept()">+ Add Item</button>\n        </div>\n        <div class="items-grid" id="dept-items-grid"></div>\n        <div class="card">\n          <div class="card-title" id="dept-tx-title">Transactions</div>\n          <div class="table-wrap">\n            <table>\n              <thead><tr><th>ID</th><th>Item</th><th>Member</th><th>Amount</th><th>Description</th><th>Vendor</th><th>Status</th><th>Date</th></tr></thead>\n              <tbody id="dept-tx-body"></tbody>\n            </table>\n          </div>\n        </div>\n      </div>\n\n      <!-- MANAGE DEPARTMENTS & ITEMS (admin) -->\n      <div class="page" id="page-manage-depts">\n        <div class="page-header">\n          <div><div class="page-title">Manage Departments</div><div class="page-subtitle">Create and configure departments and budget items</div></div>\n          <button class="btn btn-gold btn-sm" onclick="openAddDept()">+ New Department</button>\n        </div>\n        <div id="manage-depts-list"></div>\n      </div>\n\n    </main>\n  </div>\n</div>\n\n<div id="toast-container"></div>\n\n<!-- ADD DEPT MODAL -->\n<div class="modal-overlay" id="modal-add-dept">\n  <div class="modal">\n    <div class="modal-header"><span class="modal-title">New Department</span><button class="modal-close" onclick="closeModal(\'modal-add-dept\')">✕</button></div>\n    <div class="modal-body">\n      <div class="form-group"><label class="form-label">Department Name</label><input class="form-input" id="add-dept-name" placeholder="e.g. Social Events"></div>\n      <div class="form-group"><label class="form-label">Description <span class="text-dim">(optional)</span></label><textarea class="form-input" id="add-dept-desc" placeholder="What does this department cover?"></textarea></div>\n      <div class="error-msg" id="add-dept-error"></div>\n    </div>\n    <div class="modal-footer">\n      <button class="btn btn-ghost btn-sm" onclick="closeModal(\'modal-add-dept\')">Cancel</button>\n      <button class="btn btn-gold btn-sm" onclick="createDept()">Create Department</button>\n    </div>\n  </div>\n</div>\n\n<!-- EDIT DEPT MODAL -->\n<div class="modal-overlay" id="modal-edit-dept">\n  <div class="modal">\n    <div class="modal-header"><span class="modal-title">Edit Department</span><button class="modal-close" onclick="closeModal(\'modal-edit-dept\')">✕</button></div>\n    <div class="modal-body">\n      <input type="hidden" id="edit-dept-id">\n      <div class="form-group"><label class="form-label">Name</label><input class="form-input" id="edit-dept-name"></div>\n      <div class="form-group"><label class="form-label">Description</label><textarea class="form-input" id="edit-dept-desc"></textarea></div>\n      <div class="error-msg" id="edit-dept-error"></div>\n    </div>\n    <div class="modal-footer">\n      <button class="btn btn-ghost btn-sm" onclick="closeModal(\'modal-edit-dept\')">Cancel</button>\n      <button class="btn btn-gold btn-sm" onclick="saveDept()">Save</button>\n    </div>\n  </div>\n</div>\n\n<!-- ADD ITEM MODAL -->\n<div class="modal-overlay" id="modal-add-item">\n  <div class="modal">\n    <div class="modal-header"><span class="modal-title">New Budget Item</span><button class="modal-close" onclick="closeModal(\'modal-add-item\')">✕</button></div>\n    <div class="modal-body">\n      <input type="hidden" id="add-item-dept-id">\n      <div class="form-group"><label class="form-label">Item Name</label><input class="form-input" id="add-item-name" placeholder="e.g. Decorations"></div>\n      <div class="form-group"><label class="form-label">Allocated Budget ($)</label><input class="form-input" type="number" id="add-item-amount" min="0" step="0.01" placeholder="0.00"></div>\n      <div class="error-msg" id="add-item-error"></div>\n    </div>\n    <div class="modal-footer">\n      <button class="btn btn-ghost btn-sm" onclick="closeModal(\'modal-add-item\')">Cancel</button>\n      <button class="btn btn-gold btn-sm" onclick="createItem()">Add Item</button>\n    </div>\n  </div>\n</div>\n\n<!-- EDIT ITEM MODAL -->\n<div class="modal-overlay" id="modal-edit-item">\n  <div class="modal">\n    <div class="modal-header"><span class="modal-title">Edit Budget Item</span><button class="modal-close" onclick="closeModal(\'modal-edit-item\')">✕</button></div>\n    <div class="modal-body">\n      <input type="hidden" id="edit-item-id">\n      <div class="form-group"><label class="form-label">Name</label><input class="form-input" id="edit-item-name"></div>\n      <div class="form-group"><label class="form-label">Allocated Budget ($)</label><input class="form-input" type="number" id="edit-item-amount" min="0" step="0.01"></div>\n      <div class="error-msg" id="edit-item-error"></div>\n    </div>\n    <div class="modal-footer">\n      <button class="btn btn-ghost btn-sm" onclick="closeModal(\'modal-edit-item\')">Cancel</button>\n      <button class="btn btn-gold btn-sm" onclick="saveItem()">Save</button>\n    </div>\n  </div>\n</div>\n\n<!-- REJECT REQUEST MODAL -->\n<div class="modal-overlay" id="modal-reject">\n  <div class="modal">\n    <div class="modal-header"><span class="modal-title">Reject Request</span><button class="modal-close" onclick="closeModal(\'modal-reject\')">✕</button></div>\n    <div class="modal-body">\n      <input type="hidden" id="reject-rid">\n      <div class="form-group"><label class="form-label">Reason</label><textarea class="form-input" id="reject-reason" placeholder="Why is this request being rejected?"></textarea></div>\n    </div>\n    <div class="modal-footer">\n      <button class="btn btn-ghost btn-sm" onclick="closeModal(\'modal-reject\')">Cancel</button>\n      <button class="btn btn-danger btn-sm" onclick="confirmReject()">Reject</button>\n    </div>\n  </div>\n</div>\n\n<script>\nlet currentUser = null;\nlet allDepts = [];\nlet currentDeptId = null;\nlet currentDeptItems = [];\n\n// ── UTILS ──\nconst $ = id => document.getElementById(id);\nfunction toast(msg, type=\'info\') {\n  const c = $(\'toast-container\'), t = document.createElement(\'div\');\n  t.className = `toast ${type}`;\n  t.innerHTML = `<span>${{success:\'✓\',error:\'✕\',info:\'ⓘ\'}[type]||\'ⓘ\'}</span><span>${msg}</span>`;\n  c.appendChild(t); setTimeout(() => t.remove(), 3500);\n}\nfunction openModal(id) { $(id).classList.add(\'show\'); }\nfunction closeModal(id) { $(id).classList.remove(\'show\'); }\nfunction fmt$(n) { return \'$\' + parseFloat(n||0).toLocaleString(\'en-US\',{minimumFractionDigits:2,maximumFractionDigits:2}); }\nfunction fmtDate(d) { if(!d) return \'—\'; return new Date(d).toLocaleDateString(\'en-US\',{month:\'short\',day:\'numeric\',year:\'numeric\'}); }\nfunction showErr(id, msg) { const e=$(id); e.textContent=msg; e.style.display=\'block\'; }\nfunction statusBadge(s) { return `<span class="badge badge-${s}">${s}</span>`; }\nfunction budgetBar(spent, pending, allocated) {\n  const pct = allocated > 0 ? Math.min((spent/allocated)*100,100) : 0;\n  const pendPct = allocated > 0 ? Math.min((pending/allocated)*100, 100-pct) : 0;\n  const cls = pct >= 100 ? \'over\' : pct >= 80 ? \'warn\' : \'\';\n  const remaining = allocated - spent;\n  return `<div class="budget-bar-wrap">\n    <div class="budget-bar-labels">\n      <span>${fmt$(spent)} spent</span>\n      <span class="${remaining < 0 ? \'money red\' : \'money\'}">${fmt$(Math.abs(remaining))} ${remaining < 0 ? \'over\' : \'left\'}</span>\n    </div>\n    <div class="budget-bar-track">\n      <div class="budget-bar-fill ${cls}" style="width:${pct}%"></div>\n      <div class="budget-bar-pending" style="left:${pct}%;width:${pendPct}%"></div>\n    </div>\n  </div>`;\n}\n\n// ── AUTH ──\nasync function doLogin() {\n  const u = $(\'login-username\').value.trim(), p = $(\'login-password\').value;\n  $(\'login-error\').style.display = \'none\';\n  $(\'login-btn\').textContent = \'Signing in…\';\n  try {\n    const r = await fetch(\'/budget/api/login\', {method:\'POST\', headers:{\'Content-Type\':\'application/json\'}, body:JSON.stringify({username:u, password:p})});\n    const d = await r.json();\n    if (d.success) { await loadApp(); }\n    else { $(\'login-error\').style.display=\'block\'; $(\'login-btn\').textContent=\'Sign In to Treasury\'; }\n  } catch(e) {\n    $(\'login-error\').textContent = \'Connection error.\';\n    $(\'login-error\').style.display = \'block\';\n    $(\'login-btn\').textContent = \'Sign In to Treasury\';\n  }\n}\nasync function doLogout() {\n  await fetch(\'/budget/api/logout\', {method:\'POST\'});\n  currentUser = null;\n  $(\'main-app\').style.display = \'none\';\n  $(\'login-screen\').style.display = \'flex\';\n  $(\'login-password\').value = \'\';\n}\n\nasync function loadApp() {\n  const r = await fetch(\'/budget/api/me\');\n  const d = await r.json();\n  if (!d.authenticated) return;\n  currentUser = d;\n  $(\'login-screen\').style.display = \'none\';\n  $(\'main-app\').style.display = \'flex\';\n  $(\'topbar-username\').textContent = d.username.toUpperCase();\n  const rb = $(\'topbar-role\'); rb.textContent = d.role; rb.className = `role-tag role-${d.role}`;\n\n  if (d.role !== \'member\') {\n    $(\'nav-pending\').style.display = \'flex\';\n    $(\'mod-label\').style.display = \'block\';\n  }\n  if (d.role === \'admin\') {\n    $(\'nav-manage\').style.display = \'flex\';\n    $(\'admin-label\').style.display = \'block\';\n    $(\'admin-divider\').style.display = \'block\';\n  }\n\n  await loadDepts();\n  showPage(\'overview\', $(\'nav-overview\'));\n  pollPending();\n}\n\nasync function pollPending() {\n  if (!currentUser || currentUser.role === \'member\') return;\n  try {\n    const r = await fetch(\'/budget/api/requests/pending\');\n    const d = await r.json();\n    const b = $(\'pending-badge\');\n    if (d.length > 0) { b.textContent = d.length; b.style.display = \'inline\'; }\n    else { b.style.display = \'none\'; }\n  } catch(e) {}\n  setTimeout(pollPending, 30000);\n}\n\n// ── NAV ──\nfunction showPage(page, el) {\n  document.querySelectorAll(\'.page\').forEach(p => p.classList.remove(\'active\'));\n  document.querySelectorAll(\'.nav-item, .nav-dept\').forEach(n => n.classList.remove(\'active\'));\n  const pg = $(\'page-\' + page);\n  if (pg) pg.classList.add(\'active\');\n  if (el) el.classList.add(\'active\');\n  if (page === \'overview\') loadOverview();\n  else if (page === \'submit\') loadSubmitForm();\n  else if (page === \'my-requests\') loadMyRequests();\n  else if (page === \'pending\') loadPending();\n  else if (page === \'manage-depts\') loadManageDepts();\n}\n\nfunction showDept(deptId, el) {\n  document.querySelectorAll(\'.page\').forEach(p => p.classList.remove(\'active\'));\n  document.querySelectorAll(\'.nav-item, .nav-dept\').forEach(n => n.classList.remove(\'active\'));\n  $(\'page-dept\').classList.add(\'active\');\n  if (el) el.classList.add(\'active\');\n  currentDeptId = deptId;\n  loadDeptView(deptId);\n}\n\n// ── DEPTS ──\nasync function loadDepts() {\n  const r = await fetch(\'/budget/api/departments\');\n  allDepts = await r.json();\n  renderDeptNav();\n}\n\nfunction renderDeptNav() {\n  const list = $(\'dept-nav-list\');\n  const active = allDepts.filter(d => d.is_active);\n  if (active.length === 0) {\n    list.innerHTML = \'<div style="padding:.5rem 1.5rem;font-size:.8rem;color:var(--text-muted);font-style:italic">No departments yet</div>\';\n    return;\n  }\n  list.innerHTML = active.map(d => `\n    <div class="nav-dept" id="nav-dept-${d.dept_id}" onclick="showDept(${d.dept_id}, this)">\n      <span class="nav-dept-dot"></span>${d.name}\n    </div>`).join(\'\');\n}\n\n// ── OVERVIEW ──\nasync function loadOverview() {\n  const [sumR, deptR] = await Promise.all([fetch(\'/budget/api/summary\'), fetch(\'/budget/api/departments\')]);\n  const sum = await sumR.json();\n  allDepts = await deptR.json();\n  const remaining = sum.total_budget - sum.total_spent;\n\n  $(\'overview-stats\').innerHTML = `\n    <div class="stat-card"><div class="stat-label">Total Budget</div><div class="stat-value">${fmt$(sum.total_budget)}</div><div class="stat-sub">${sum.dept_count} department${sum.dept_count!==1?\'s\':\'\'}</div></div>\n    <div class="stat-card stat-spent"><div class="stat-label">Total Spent</div><div class="stat-value red">${fmt$(sum.total_spent)}</div><div class="stat-sub">approved expenses</div></div>\n    <div class="stat-card stat-remaining"><div class="stat-label">Remaining</div><div class="stat-value green">${fmt$(remaining)}</div><div class="stat-sub">${sum.total_budget > 0 ? Math.round((remaining/sum.total_budget)*100) : 0}% of budget</div></div>\n    <div class="stat-card stat-pending"><div class="stat-label">Pending</div><div class="stat-value">${sum.pending_count}</div><div class="stat-sub">awaiting review</div></div>\n  `;\n\n  const tbody = $(\'overview-depts-body\');\n  const active = allDepts.filter(d => d.is_active);\n  if (active.length === 0) {\n    tbody.innerHTML = `<tr><td colspan="5"><div class="empty-state"><div class="empty-icon">◈</div><div class="empty-text">No departments yet</div></div></td></tr>`;\n    return;\n  }\n  // Fetch spent per dept via individual dept items\n  tbody.innerHTML = active.map(d => {\n    const pct = d.total_allocated > 0 ? 0 : 0; // will load async below\n    return `<tr id="dept-row-${d.dept_id}" onclick="showDept(${d.dept_id}, $(\'nav-dept-${d.dept_id}\'))" style="cursor:pointer">\n      <td style="font-family:\'Cinzel\',serif;font-size:.85rem">${d.name}</td>\n      <td><span class="money">${fmt$(d.total_allocated)}</span></td>\n      <td id="dept-spent-${d.dept_id}"><span class="text-dim">—</span></td>\n      <td id="dept-rem-${d.dept_id}"><span class="text-dim">—</span></td>\n      <td id="dept-bar-${d.dept_id}" style="min-width:140px"></td>\n    </tr>`;\n  }).join(\'\');\n\n  // Load spent amounts for each dept asynchronously\n  active.forEach(async d => {\n    try {\n      const ir = await fetch(`/budget/api/departments/${d.dept_id}/items`);\n      const items = await ir.json();\n      const spent = items.reduce((s,i)=>s+parseFloat(i.spent||0),0);\n      const pending = items.reduce((s,i)=>s+parseFloat(i.pending_amount||0),0);\n      const alloc = parseFloat(d.total_allocated||0);\n      const rem = alloc - spent;\n      const pct = alloc > 0 ? Math.min((spent/alloc)*100,100) : 0;\n      const cls = pct>=100?\'over\':pct>=80?\'warn\':\'\';\n      $(`dept-spent-${d.dept_id}`).innerHTML = `<span class="money">${fmt$(spent)}</span>`;\n      $(`dept-rem-${d.dept_id}`).innerHTML = `<span class="money ${rem<0?\'red\':\'green\'}">${fmt$(Math.abs(rem))}</span>`;\n      $(`dept-bar-${d.dept_id}`).innerHTML = `<div class="budget-bar-track" style="height:6px"><div class="budget-bar-fill ${cls}" style="width:${pct}%"></div></div>`;\n    } catch(e) {}\n  });\n}\n\n// ── SUBMIT FORM ──\nasync function loadSubmitForm() {\n  await loadDepts();\n  const sel = $(\'req-dept\');\n  const active = allDepts.filter(d => d.is_active);\n  sel.innerHTML = \'<option value="">— Select a department —</option>\' +\n    active.map(d => `<option value="${d.dept_id}">${d.name}</option>`).join(\'\');\n  $(\'req-item\').innerHTML = \'<option value="">— Select a budget item —</option>\';\n  $(\'req-item\').disabled = true;\n  $(\'item-budget-preview\').style.display = \'none\';\n}\n\nasync function onDeptChange() {\n  const did = $(\'req-dept\').value;\n  const itemSel = $(\'req-item\');\n  $(\'item-budget-preview\').style.display = \'none\';\n  if (!did) { itemSel.disabled=true; itemSel.innerHTML=\'<option value="">— Select a budget item —</option>\'; return; }\n  const r = await fetch(`/budget/api/departments/${did}/items`);\n  const items = await r.json();\n  currentDeptItems = items;\n  itemSel.innerHTML = \'<option value="">— Select a budget item —</option>\' +\n    items.map(i => {\n      const rem = parseFloat(i.allocated)-parseFloat(i.spent||0);\n      return `<option value="${i.item_id}" data-alloc="${i.allocated}" data-spent="${i.spent||0}" data-pending="${i.pending_amount||0}">${i.name} (${fmt$(rem)} remaining)</option>`;\n    }).join(\'\');\n  itemSel.disabled = false;\n}\n\nfunction onItemChange() {\n  const opt = $(\'req-item\').options[$(\'req-item\').selectedIndex];\n  if (!opt || !opt.value) { $(\'item-budget-preview\').style.display=\'none\'; return; }\n  const alloc = parseFloat(opt.dataset.alloc||0);\n  const spent = parseFloat(opt.dataset.spent||0);\n  const pending = parseFloat(opt.dataset.pending||0);\n  $(\'item-bar-wrap\').innerHTML = budgetBar(spent, pending, alloc);\n  $(\'item-budget-preview\').style.display = \'block\';\n}\n\nasync function submitRequest() {\n  const item_id = parseInt($(\'req-item\').value);\n  const amount = parseFloat($(\'req-amount\').value);\n  const description = $(\'req-desc\').value.trim();\n  const vendor = $(\'req-vendor\').value.trim();\n  if (!item_id) { toast(\'Please select a budget item\', \'error\'); return; }\n  if (!amount || amount <= 0) { toast(\'Please enter a valid amount\', \'error\'); return; }\n  if (!description) { toast(\'Please enter a description\', \'error\'); return; }\n  const r = await fetch(\'/budget/api/requests\', {method:\'POST\', headers:{\'Content-Type\':\'application/json\'},\n    body:JSON.stringify({item_id, amount, description, vendor})});\n  const d = await r.json();\n  if (d.success) {\n    toast(\'Request submitted for approval!\', \'success\');\n    $(\'req-amount\').value=\'\'; $(\'req-desc\').value=\'\'; $(\'req-vendor\').value=\'\';\n    $(\'req-dept\').value=\'\'; $(\'req-item\').disabled=true;\n    $(\'item-budget-preview\').style.display=\'none\';\n  } else toast(d.error||\'Error\', \'error\');\n}\n\n// ── MY REQUESTS ──\nasync function loadMyRequests() {\n  const r = await fetch(\'/budget/api/requests\');\n  const rows = await r.json();\n  const tbody = $(\'my-req-body\');\n  if (!rows.length) {\n    tbody.innerHTML = `<tr><td colspan="7"><div class="empty-state"><div class="empty-icon">📋</div><div class="empty-text">No requests submitted yet</div></div></td></tr>`;\n    return;\n  }\n  tbody.innerHTML = rows.map(r => `\n    <tr>\n      <td class="text-dim">#${r.request_id}</td>\n      <td style="font-size:.85rem">${r.dept_name}</td>\n      <td class="truncate text-dim" style="font-size:.85rem">${r.item_name}</td>\n      <td><span class="money">${fmt$(r.amount)}</span></td>\n      <td class="truncate" style="font-size:.85rem">${r.description}</td>\n      <td>${statusBadge(r.status)}</td>\n      <td class="text-dim" style="font-size:.8rem">${fmtDate(r.created_at)}</td>\n    </tr>`).join(\'\');\n}\n\n// ── PENDING ──\nasync function loadPending() {\n  const r = await fetch(\'/budget/api/requests/pending\');\n  const rows = await r.json();\n  const badge = $(\'pending-badge\');\n  badge.textContent = rows.length;\n  badge.style.display = rows.length > 0 ? \'inline\' : \'none\';\n  const tbody = $(\'pending-body\');\n  if (!rows.length) {\n    tbody.innerHTML = `<tr><td colspan="9"><div class="empty-state"><div class="empty-icon">✓</div><div class="empty-text">All caught up</div></div></td></tr>`;\n    return;\n  }\n  tbody.innerHTML = rows.map(r => {\n    const spent = parseFloat(r.item_spent||0);\n    const alloc = parseFloat(r.allocated||0);\n    const rem = alloc - spent;\n    return `<tr>\n      <td class="text-dim">#${r.request_id}</td>\n      <td style="font-family:\'Cinzel\',serif;font-size:.8rem">${r.submitter_name}</td>\n      <td style="font-size:.85rem">${r.dept_name}</td>\n      <td style="font-size:.85rem">${r.item_name}<div class="row-info">${fmt$(rem)} remaining of ${fmt$(alloc)}</div></td>\n      <td><span class="money">${fmt$(r.amount)}</span></td>\n      <td class="truncate" style="font-size:.85rem" title="${r.description}">${r.description}</td>\n      <td class="text-dim" style="font-size:.85rem">${r.vendor||\'—\'}</td>\n      <td class="text-dim" style="font-size:.8rem">${fmtDate(r.created_at)}</td>\n      <td><div class="action-btns">\n        <button class="btn btn-success btn-sm" onclick="approveRequest(${r.request_id})">✓ Approve</button>\n        <button class="btn btn-danger btn-sm" onclick="openReject(${r.request_id})">✕ Reject</button>\n      </div></td>\n    </tr>`;\n  }).join(\'\');\n}\n\nasync function approveRequest(rid) {\n  const r = await fetch(`/budget/api/requests/${rid}/approve`, {method:\'POST\'});\n  const d = await r.json();\n  if (d.success) { toast(\'Request approved!\',\'success\'); loadPending(); loadOverview(); }\n  else toast(d.error||\'Error\',\'error\');\n}\nfunction openReject(rid) {\n  $(\'reject-rid\').value = rid;\n  $(\'reject-reason\').value = \'\';\n  openModal(\'modal-reject\');\n}\nasync function confirmReject() {\n  const rid = $(\'reject-rid\').value;\n  const reason = $(\'reject-reason\').value.trim();\n  if (!reason) { toast(\'Please provide a reason\',\'error\'); return; }\n  const r = await fetch(`/budget/api/requests/${rid}/reject`, {method:\'POST\', headers:{\'Content-Type\':\'application/json\'}, body:JSON.stringify({reason})});\n  const d = await r.json();\n  if (d.success) { toast(\'Request rejected\',\'info\'); closeModal(\'modal-reject\'); loadPending(); }\n  else toast(d.error||\'Error\',\'error\');\n}\n\n// ── DEPT VIEW ──\nasync function loadDeptView(deptId) {\n  const dept = allDepts.find(d => d.dept_id === deptId);\n  if (!dept) return;\n  $(\'dept-view-name\').textContent = dept.name;\n  $(\'dept-view-desc\').textContent = dept.description || \'\';\n  $(\'dept-tx-title\').textContent = `${dept.name} — Transactions`;\n  if (currentUser.role === \'admin\') $(\'btn-add-item-dept\').style.display = \'inline-flex\';\n\n  const [itemsR, txR] = await Promise.all([\n    fetch(`/budget/api/departments/${deptId}/items`),\n    fetch(`/budget/api/departments/${deptId}/requests`)\n  ]);\n  const items = await itemsR.json();\n  const txs   = await txR.json();\n\n  const totalAlloc   = items.reduce((s,i)=>s+parseFloat(i.allocated||0),0);\n  const totalSpent   = items.reduce((s,i)=>s+parseFloat(i.spent||0),0);\n  const totalPending = items.reduce((s,i)=>s+parseFloat(i.pending_amount||0),0);\n  const remaining = totalAlloc - totalSpent;\n\n  $(\'dept-stats\').innerHTML = `\n    <div class="stat-card"><div class="stat-label">Total Budget</div><div class="stat-value">${fmt$(totalAlloc)}</div><div class="stat-sub">${items.length} item${items.length!==1?\'s\':\'\'}</div></div>\n    <div class="stat-card stat-spent"><div class="stat-label">Spent</div><div class="stat-value red">${fmt$(totalSpent)}</div><div class="stat-sub">approved</div></div>\n    <div class="stat-card stat-remaining"><div class="stat-label">Remaining</div><div class="stat-value green">${fmt$(remaining)}</div><div class="stat-sub">${totalAlloc>0?Math.round((remaining/totalAlloc)*100):0}% left</div></div>\n    <div class="stat-card stat-pending"><div class="stat-label">Pending</div><div class="stat-value">${fmt$(totalPending)}</div><div class="stat-sub">awaiting approval</div></div>\n  `;\n\n  // Item cards\n  $(\'dept-items-grid\').innerHTML = items.length === 0\n    ? `<div class="empty-state"><div class="empty-text">No budget items yet</div></div>`\n    : items.map(i => {\n        const spent = parseFloat(i.spent||0);\n        const pending = parseFloat(i.pending_amount||0);\n        const alloc = parseFloat(i.allocated||0);\n        const rem = alloc - spent;\n        return `<div class="item-card">\n          <div class="item-card-name">${i.name}</div>\n          ${budgetBar(spent, pending, alloc)}\n          <div class="item-figures">\n            <div><div class="item-fig-label">Budget</div><div class="item-fig-val text-gold">${fmt$(alloc)}</div></div>\n            <div><div class="item-fig-label">Spent</div><div class="item-fig-val ${spent>alloc?\'money red\':\'money\'}">${fmt$(spent)}</div></div>\n            <div><div class="item-fig-label">Remaining</div><div class="item-fig-val ${rem<0?\'money red\':\'money green\'}">${fmt$(Math.abs(rem))}</div></div>\n          </div>\n          ${currentUser.role===\'admin\'?`<div style="margin-top:.75rem;display:flex;gap:.5rem"><button class="btn btn-ghost btn-sm" onclick="openEditItem(${i.item_id},event)">Edit</button><button class="btn btn-danger btn-sm" onclick="deleteItem(${i.item_id},event)">Remove</button></div>`:\'\'}\n        </div>`;\n      }).join(\'\');\n\n  // Transactions table\n  const tbody = $(\'dept-tx-body\');\n  if (!txs.length) {\n    tbody.innerHTML = `<tr><td colspan="8"><div class="empty-state"><div class="empty-text">No transactions yet</div></div></td></tr>`;\n    return;\n  }\n  tbody.innerHTML = txs.map(t => `\n    <tr>\n      <td class="text-dim">#${t.request_id}</td>\n      <td style="font-size:.85rem">${t.item_name}</td>\n      <td style="font-family:\'Cinzel\',serif;font-size:.8rem">${t.submitter_name}</td>\n      <td><span class="money ${t.status===\'approved\'?\'red\':\'\'}">${t.status===\'approved\'?\'−\':\'\'}${fmt$(t.amount)}</span></td>\n      <td class="truncate" style="font-size:.85rem" title="${t.description}">${t.description}</td>\n      <td class="text-dim" style="font-size:.85rem">${t.vendor||\'—\'}</td>\n      <td>${statusBadge(t.status)}</td>\n      <td class="text-dim" style="font-size:.8rem">${fmtDate(t.created_at)}</td>\n    </tr>`).join(\'\');\n}\n\n// ── MANAGE DEPTS ──\nasync function loadManageDepts() {\n  const r = await fetch(\'/budget/api/departments\');\n  allDepts = await r.json();\n  const container = $(\'manage-depts-list\');\n  if (!allDepts.length) {\n    container.innerHTML = `<div class="empty-state"><div class="empty-icon">◈</div><div class="empty-text">No departments yet — create one above</div></div>`;\n    return;\n  }\n  container.innerHTML = allDepts.map(dept => `\n    <div class="card" id="manage-dept-${dept.dept_id}">\n      <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:1rem;flex-wrap:wrap;margin-bottom:1rem">\n        <div>\n          <div style="font-family:\'Cinzel\',serif;font-size:1.1rem;color:var(--gold)">${dept.name}</div>\n          ${dept.description?`<div class="text-dim" style="font-style:italic;font-size:.9rem;margin-top:.2rem">${dept.description}</div>`:\'\'}\n        </div>\n        <div style="display:flex;gap:.5rem;flex-wrap:wrap">\n          <button class="btn btn-ghost btn-sm" onclick="openEditDept(${dept.dept_id})">Edit</button>\n          <button class="btn btn-gold btn-sm" onclick="openAddItem(${dept.dept_id})">+ Item</button>\n          ${dept.is_active\n            ? `<button class="btn btn-danger btn-sm" onclick="toggleDept(${dept.dept_id},false)">Archive</button>`\n            : `<button class="btn btn-success btn-sm" onclick="toggleDept(${dept.dept_id},true)">Restore</button>`}\n        </div>\n      </div>\n      <div id="manage-items-${dept.dept_id}">\n        <div class="text-dim" style="font-size:.85rem;font-style:italic">Loading items...</div>\n      </div>\n    </div>`).join(\'\');\n\n  // Load items for each dept\n  allDepts.forEach(async dept => {\n    try {\n      const ir = await fetch(`/budget/api/departments/${dept.dept_id}/items`);\n      const items = await ir.json();\n      const el = $(`manage-items-${dept.dept_id}`);\n      if (!items.length) {\n        el.innerHTML = `<div class="text-dim" style="font-size:.85rem;font-style:italic">No items yet.</div>`;\n        return;\n      }\n      el.innerHTML = `<table style="font-size:.85rem"><thead><tr><th>Item</th><th>Allocated</th><th>Spent</th><th>Remaining</th><th></th></tr></thead><tbody>` +\n        items.map(i => {\n          const rem = parseFloat(i.allocated) - parseFloat(i.spent||0);\n          return `<tr>\n            <td style="font-family:\'Cinzel\',serif">${i.name}</td>\n            <td><span class="money">${fmt$(i.allocated)}</span></td>\n            <td><span class="money">${fmt$(i.spent||0)}</span></td>\n            <td><span class="money ${rem<0?\'red\':\'green\'}">${fmt$(Math.abs(rem))}</span></td>\n            <td><div class="action-btns">\n              <button class="btn btn-ghost btn-sm" onclick="openEditItem(${i.item_id},event)">Edit</button>\n              <button class="btn btn-danger btn-sm" onclick="deleteItem(${i.item_id},event)">Remove</button>\n            </div></td>\n          </tr>`;\n        }).join(\'\') + `</tbody></table>`;\n    } catch(e) {}\n  });\n}\n\n// ── DEPT CRUD ──\nfunction openAddDept() {\n  $(\'add-dept-name\').value=\'\'; $(\'add-dept-desc\').value=\'\';\n  $(\'add-dept-error\').style.display=\'none\';\n  openModal(\'modal-add-dept\');\n}\nasync function createDept() {\n  const name=$(\'add-dept-name\').value.trim(), desc=$(\'add-dept-desc\').value.trim();\n  if(!name){showErr(\'add-dept-error\',\'Name is required\');return;}\n  const r=await fetch(\'/budget/api/departments\',{method:\'POST\',headers:{\'Content-Type\':\'application/json\'},body:JSON.stringify({name,description:desc})});\n  const d=await r.json();\n  if(d.success){toast(\'Department created!\',\'success\');closeModal(\'modal-add-dept\');await loadDepts();loadManageDepts();}\n  else showErr(\'add-dept-error\',d.error||\'Error\');\n}\nfunction openEditDept(id) {\n  const dept=allDepts.find(d=>d.dept_id===id);if(!dept)return;\n  $(\'edit-dept-id\').value=id;$(\'edit-dept-name\').value=dept.name;$(\'edit-dept-desc\').value=dept.description||\'\';\n  $(\'edit-dept-error\').style.display=\'none\';openModal(\'modal-edit-dept\');\n}\nasync function saveDept() {\n  const id=$(\'edit-dept-id\').value,name=$(\'edit-dept-name\').value.trim(),desc=$(\'edit-dept-desc\').value.trim();\n  if(!name){showErr(\'edit-dept-error\',\'Name is required\');return;}\n  const r=await fetch(`/budget/api/departments/${id}`,{method:\'PUT\',headers:{\'Content-Type\':\'application/json\'},body:JSON.stringify({name,description:desc})});\n  const d=await r.json();\n  if(d.success){toast(\'Department updated!\',\'success\');closeModal(\'modal-edit-dept\');await loadDepts();loadManageDepts();}\n  else showErr(\'edit-dept-error\',d.error||\'Error\');\n}\nasync function toggleDept(id, active) {\n  const r=await fetch(`/budget/api/departments/${id}`,{method:\'PUT\',headers:{\'Content-Type\':\'application/json\'},body:JSON.stringify({is_active:active})});\n  const d=await r.json();\n  if(d.success){toast(active?\'Department restored\':\'Department archived\',\'info\');await loadDepts();loadManageDepts();}\n  else toast(\'Error\',\'error\');\n}\n\n// ── ITEM CRUD ──\nfunction openAddItem(deptId) {\n  $(\'add-item-dept-id\').value=deptId;$(\'add-item-name\').value=\'\';$(\'add-item-amount\').value=\'\';\n  $(\'add-item-error\').style.display=\'none\';openModal(\'modal-add-item\');\n}\nfunction openAddItemFromDept() { openAddItem(currentDeptId); }\nasync function createItem() {\n  const did=$(\'add-item-dept-id\').value,name=$(\'add-item-name\').value.trim(),amount=$(\'add-item-amount\').value;\n  if(!name||amount===\'\'){showErr(\'add-item-error\',\'Name and amount are required\');return;}\n  const r=await fetch(`/budget/api/departments/${did}/items`,{method:\'POST\',headers:{\'Content-Type\':\'application/json\'},body:JSON.stringify({name,allocated:parseFloat(amount)})});\n  const d=await r.json();\n  if(d.success){toast(\'Budget item added!\',\'success\');closeModal(\'modal-add-item\');await loadDepts();if(currentDeptId===parseInt(did))loadDeptView(parseInt(did));else loadManageDepts();}\n  else showErr(\'add-item-error\',d.error||\'Error\');\n}\nasync function openEditItem(iid, e) {\n  if(e)e.stopPropagation();\n  // fetch all items across current dept to find this one\n  const r=await fetch(`/budget/api/departments/${currentDeptId||0}/items`);\n  let items=await r.json();\n  let item=items.find(i=>i.item_id===iid);\n  // fallback: search all depts\n  if(!item){\n    for(const d of allDepts){\n      const ir=await fetch(`/budget/api/departments/${d.dept_id}/items`);\n      const its=await ir.json();\n      item=its.find(i=>i.item_id===iid);\n      if(item)break;\n    }\n  }\n  if(!item)return;\n  $(\'edit-item-id\').value=iid;$(\'edit-item-name\').value=item.name;$(\'edit-item-amount\').value=item.allocated;\n  $(\'edit-item-error\').style.display=\'none\';openModal(\'modal-edit-item\');\n}\nasync function saveItem() {\n  const iid=$(\'edit-item-id\').value,name=$(\'edit-item-name\').value.trim(),amount=$(\'edit-item-amount\').value;\n  if(!name||amount===\'\'){showErr(\'edit-item-error\',\'Both fields required\');return;}\n  const r=await fetch(`/budget/api/items/${iid}`,{method:\'PUT\',headers:{\'Content-Type\':\'application/json\'},body:JSON.stringify({name,allocated:parseFloat(amount)})});\n  const d=await r.json();\n  if(d.success){toast(\'Item updated!\',\'success\');closeModal(\'modal-edit-item\');if(currentDeptId)loadDeptView(currentDeptId);else loadManageDepts();}\n  else showErr(\'edit-item-error\',d.error||\'Error\');\n}\nasync function deleteItem(iid, e) {\n  if(e)e.stopPropagation();\n  if(!confirm(\'Remove this budget item?\'))return;\n  const r=await fetch(`/budget/api/items/${iid}`,{method:\'DELETE\'});\n  const d=await r.json();\n  if(d.success){toast(\'Item removed\',\'info\');if(currentDeptId)loadDeptView(currentDeptId);else loadManageDepts();}\n  else toast(\'Error\',\'error\');\n}\n\n// ── INIT ──\ndocument.getElementById(\'login-password\').addEventListener(\'keydown\',e=>{if(e.key===\'Enter\')doLogin();});\ndocument.getElementById(\'login-username\').addEventListener(\'keydown\',e=>{if(e.key===\'Enter\')doLogin();});\ndocument.querySelectorAll(\'.modal-overlay\').forEach(o=>o.addEventListener(\'click\',e=>{if(e.target===o)o.classList.remove(\'show\');}));\n(async()=>{const r=await fetch(\'/budget/api/me\');const d=await r.json();if(d.authenticated)await loadApp();})();\n</script>\n</body>\n</html>'

@app.route('/')
def index():
    return LANDING_HTML

@app.route('/points')
def points_app():
    return POINTS_HTML

@app.route('/budget')
def budget_app_route():
    return BUDGET_HTML

# ============================================================================
# STARTUP
# ============================================================================

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
