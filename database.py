import sqlite3

DATABASE = 'stock_simulator.db'


def get_connection():
    """Create and return a new database connection (caller must close)."""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def get_db():
    """Get connection bound to the current Flask request context."""
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


def init_db(app):
    """Create all tables if they don't exist."""
    with app.app_context():
        conn = get_connection()
        conn.executescript('''
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
        ''')
        conn.commit()
        conn.close()
