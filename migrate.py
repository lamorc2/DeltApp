#!/usr/bin/env python3
"""
Migration script: brotherhood_system.db (SQLite) → Railway PostgreSQL
Run once locally:
    pip install psycopg2-binary
    python migrate.py
"""

import sqlite3
import hashlib
import sys

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    print("ERROR: psycopg2 not installed. Run: pip install psycopg2-binary")
    sys.exit(1)

# ── CONFIG ──────────────────────────────────────────────────────────────────

SQLITE_PATH  = "brotherhood_system.db"  # path to your local .db file
DATABASE_URL = input("Paste your Railway DATABASE_URL: ").strip()

# ── CONNECT ──────────────────────────────────────────────────────────────────

print("\nConnecting to SQLite...")
sq = sqlite3.connect(SQLITE_PATH)
sq.row_factory = sqlite3.Row

print("Connecting to PostgreSQL...")
pg = psycopg2.connect(DATABASE_URL)
pg.autocommit = False
pgc = pg.cursor()

# ── CREATE TABLES (safe — won't overwrite existing data) ─────────────────────

print("Ensuring tables exist in Postgres...")

pgc.execute('''CREATE TABLE IF NOT EXISTS users (
    user_id SERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    role TEXT NOT NULL,
    brotherhood_points INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)''')

pgc.execute('''CREATE TABLE IF NOT EXISTS transactions (
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

pgc.execute('''CREATE TABLE IF NOT EXISTS point_actions (
    action_id SERIAL PRIMARY KEY,
    label TEXT NOT NULL,
    points INTEGER NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)''')

pgc.execute('''CREATE TABLE IF NOT EXISTS audit_log (
    log_id SERIAL PRIMARY KEY,
    action TEXT NOT NULL,
    user_id INTEGER,
    details TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)''')

pgc.execute('''CREATE TABLE IF NOT EXISTS budget_departments (
    dept_id SERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    description TEXT DEFAULT '',
    is_active BOOLEAN DEFAULT TRUE,
    created_by INTEGER REFERENCES users(user_id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)''')

pgc.execute('''CREATE TABLE IF NOT EXISTS budget_items (
    item_id SERIAL PRIMARY KEY,
    dept_id INTEGER NOT NULL REFERENCES budget_departments(dept_id),
    name TEXT NOT NULL,
    allocated NUMERIC(12,2) NOT NULL DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)''')

pgc.execute('''CREATE TABLE IF NOT EXISTS budget_requests (
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

pg.commit()

# ── HELPER ───────────────────────────────────────────────────────────────────

def table_exists(conn, name):
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
    return row is not None

def count_pg(table):
    pgc.execute(f"SELECT COUNT(*) FROM {table}")
    return pgc.fetchone()[0]

# ── MIGRATE USERS ─────────────────────────────────────────────────────────────

print("\nMigrating users...")
users = sq.execute("SELECT * FROM users ORDER BY user_id").fetchall()
skipped = 0
migrated = 0
id_map = {}  # old sqlite user_id → new postgres user_id

for u in users:
    try:
        pgc.execute('''
            INSERT INTO users (username, password_hash, email, role, brotherhood_points, is_active, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (username) DO NOTHING
            RETURNING user_id
        ''', (u['username'], u['password_hash'], u['email'], u['role'],
              u['brotherhood_points'], bool(u['is_active']), u['created_at']))
        row = pgc.fetchone()
        if row:
            id_map[u['user_id']] = row[0]
            migrated += 1
        else:
            # Already existed — look up the pg id
            pgc.execute("SELECT user_id FROM users WHERE username=%s", (u['username'],))
            existing = pgc.fetchone()
            if existing:
                id_map[u['user_id']] = existing[0]
            skipped += 1
    except Exception as e:
        print(f"  WARNING: Could not migrate user {u['username']}: {e}")
        pg.rollback()

pg.commit()
print(f"  Users: {migrated} migrated, {skipped} already existed")

# ── MIGRATE TRANSACTIONS ──────────────────────────────────────────────────────

print("Migrating transactions...")
if table_exists(sq, 'transactions'):
    txs = sq.execute("SELECT * FROM transactions ORDER BY transaction_id").fetchall()
    migrated = 0
    skipped = 0
    for t in txs:
        new_member_id = id_map.get(t['member_id'])
        if not new_member_id:
            skipped += 1
            continue
        try:
            pgc.execute('''
                INSERT INTO transactions (member_id, points, description, status, created_at, reviewed_by, reviewed_at, rejection_reason)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ''', (new_member_id, t['points'], t['description'], t['status'],
                  t['created_at'], t['reviewed_by'], t['reviewed_at'], t['rejection_reason']))
            migrated += 1
        except Exception as e:
            print(f"  WARNING: Could not migrate transaction {t['transaction_id']}: {e}")
    pg.commit()
    print(f"  Transactions: {migrated} migrated, {skipped} skipped (unknown member)")
else:
    print("  No transactions table found in SQLite, skipping.")

# ── MIGRATE POINT ACTIONS ─────────────────────────────────────────────────────

print("Migrating point actions...")
if table_exists(sq, 'point_actions'):
    actions = sq.execute("SELECT * FROM point_actions ORDER BY action_id").fetchall()
    migrated = 0
    for a in actions:
        try:
            pgc.execute('''
                INSERT INTO point_actions (label, points, is_active, created_at)
                VALUES (%s, %s, %s, %s)
            ''', (a['label'], a['points'], bool(a['is_active']), a['created_at']))
            migrated += 1
        except Exception as e:
            print(f"  WARNING: Could not migrate action {a['label']}: {e}")
    pg.commit()
    print(f"  Point actions: {migrated} migrated")
else:
    print("  No point_actions table found in SQLite, skipping.")

# ── MIGRATE AUDIT LOG ─────────────────────────────────────────────────────────

print("Migrating audit log...")
if table_exists(sq, 'audit_log'):
    logs = sq.execute("SELECT * FROM audit_log ORDER BY log_id").fetchall()
    migrated = 0
    for l in logs:
        new_user_id = id_map.get(l['user_id']) if l['user_id'] else None
        try:
            pgc.execute('''
                INSERT INTO audit_log (action, user_id, details, timestamp)
                VALUES (%s, %s, %s, %s)
            ''', (l['action'], new_user_id, l['details'], l['timestamp']))
            migrated += 1
        except Exception as e:
            print(f"  WARNING: Could not migrate log entry: {e}")
    pg.commit()
    print(f"  Audit log: {migrated} entries migrated")
else:
    print("  No audit_log table found in SQLite, skipping.")

# ── RESET SEQUENCES ───────────────────────────────────────────────────────────

print("Resetting Postgres sequences...")
for table, col, seq in [
    ('users',         'user_id',        'users_user_id_seq'),
    ('transactions',  'transaction_id', 'transactions_transaction_id_seq'),
    ('point_actions', 'action_id',      'point_actions_action_id_seq'),
    ('audit_log',     'log_id',         'audit_log_log_id_seq'),
]:
    pgc.execute(f"SELECT setval('{seq}', COALESCE((SELECT MAX({col}) FROM {table}), 1))")
pg.commit()

# ── SUMMARY ───────────────────────────────────────────────────────────────────

sq.close()
pg.close()

print("\n✓ Migration complete!")
print(f"  Users in Postgres:        {count_pg('users') if False else '(committed)'}")
print("\nYou can verify by logging into your app at your Railway URL.")
print("The local SQLite file has NOT been modified.\n")
