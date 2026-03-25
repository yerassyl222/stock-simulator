import os
import sqlite3

# ---------------------------------------------------------------------------
# DB detection
# ---------------------------------------------------------------------------

_DATABASE_URL = os.environ.get('DATABASE_URL', '')

# Render provides 'postgres://' but psycopg2 requires 'postgresql://'
if _DATABASE_URL.startswith('postgres://'):
    _DATABASE_URL = 'postgresql://' + _DATABASE_URL[len('postgres://'):]

IS_POSTGRES = bool(_DATABASE_URL)
SQLITE_FILE = 'stock_simulator.db'


# ---------------------------------------------------------------------------
# Unified connection wrapper
# ---------------------------------------------------------------------------

class Connection:
    """
    Thin wrapper that gives psycopg2 the same interface as sqlite3:
      - .execute(sql, params)  using '?' placeholders in sql
      - .commit() / .rollback() / .close()

    Row objects from both backends support row['column_name'] access:
      - sqlite3 uses sqlite3.Row  (set via row_factory)
      - psycopg2 uses RealDictRow (set via RealDictCursor)
    """

    def __init__(self, raw_conn):
        self._conn = raw_conn

    def execute(self, sql, params=()):
        if IS_POSTGRES:
            sql = sql.replace('?', '%s')
            cur = self._conn.cursor()
            cur.execute(sql, params if params else None)
            return cur
        return self._conn.execute(sql, params)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()


# ---------------------------------------------------------------------------
# Connection factories
# ---------------------------------------------------------------------------

def get_connection() -> Connection:
    """Open a fresh DB connection. Caller is responsible for closing it."""
    if IS_POSTGRES:
        import psycopg2
        import psycopg2.extras
        raw = psycopg2.connect(
            _DATABASE_URL,
            cursor_factory=psycopg2.extras.RealDictCursor,
        )
        raw.autocommit = False
    else:
        raw = sqlite3.connect(SQLITE_FILE)
        raw.row_factory = sqlite3.Row

    return Connection(raw)


def get_db() -> Connection:
    """Return a request-scoped connection stored in Flask's g."""
    from flask import g
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = get_connection()
    return db


def close_db(e=None):
    from flask import g
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()


# ---------------------------------------------------------------------------
# Schema — separate DDL for each backend
# ---------------------------------------------------------------------------

_SQLITE_SCHEMA = '''
    CREATE TABLE IF NOT EXISTS users (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        username      TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        cash_balance  REAL DEFAULT 10000.0,
        created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS holdings (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id   INTEGER NOT NULL,
        ticker    TEXT NOT NULL,
        shares    REAL NOT NULL DEFAULT 0,
        avg_price REAL NOT NULL DEFAULT 0,
        FOREIGN KEY (user_id) REFERENCES users(id),
        UNIQUE(user_id, ticker)
    );
    CREATE TABLE IF NOT EXISTS stock_prices (
        ticker     TEXT PRIMARY KEY,
        name       TEXT,
        price      REAL DEFAULT 0,
        prev_close REAL DEFAULT 0,
        change_pct REAL DEFAULT 0,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS transactions (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id    INTEGER NOT NULL,
        ticker     TEXT NOT NULL,
        shares     REAL NOT NULL,
        price      REAL NOT NULL,
        type       TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS portfolio_history (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id     INTEGER NOT NULL,
        total_value REAL NOT NULL,
        cash        REAL NOT NULL,
        created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    );
'''

# Each string is one statement (psycopg2 doesn't support multi-statement scripts)
_POSTGRES_STATEMENTS = [
    '''CREATE TABLE IF NOT EXISTS users (
        id            SERIAL PRIMARY KEY,
        username      TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        cash_balance  DOUBLE PRECISION DEFAULT 10000.0,
        created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''',
    '''CREATE TABLE IF NOT EXISTS holdings (
        id        SERIAL PRIMARY KEY,
        user_id   INTEGER NOT NULL REFERENCES users(id),
        ticker    TEXT NOT NULL,
        shares    DOUBLE PRECISION NOT NULL DEFAULT 0,
        avg_price DOUBLE PRECISION NOT NULL DEFAULT 0,
        UNIQUE(user_id, ticker)
    )''',
    '''CREATE TABLE IF NOT EXISTS stock_prices (
        ticker     TEXT PRIMARY KEY,
        name       TEXT,
        price      DOUBLE PRECISION DEFAULT 0,
        prev_close DOUBLE PRECISION DEFAULT 0,
        change_pct DOUBLE PRECISION DEFAULT 0,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''',
    '''CREATE TABLE IF NOT EXISTS transactions (
        id         SERIAL PRIMARY KEY,
        user_id    INTEGER NOT NULL REFERENCES users(id),
        ticker     TEXT NOT NULL,
        shares     DOUBLE PRECISION NOT NULL,
        price      DOUBLE PRECISION NOT NULL,
        type       TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''',
    '''CREATE TABLE IF NOT EXISTS portfolio_history (
        id          SERIAL PRIMARY KEY,
        user_id     INTEGER NOT NULL REFERENCES users(id),
        total_value DOUBLE PRECISION NOT NULL,
        cash        DOUBLE PRECISION NOT NULL,
        created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''',
]


def init_db(app):
    """Create all tables if they don't exist."""
    with app.app_context():
        if IS_POSTGRES:
            conn = get_connection()
            try:
                for stmt in _POSTGRES_STATEMENTS:
                    conn.execute(stmt)
                conn.commit()
            finally:
                conn.close()
        else:
            # sqlite3.executescript is not on our wrapper — use the raw connection
            raw = sqlite3.connect(SQLITE_FILE)
            raw.executescript(_SQLITE_SCHEMA)
            raw.close()
