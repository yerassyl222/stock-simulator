import json
import sqlite3
from datetime import datetime, timedelta, date

try:
    from psycopg2.errors import UniqueViolation as _PgUniqueViolation
except ImportError:
    _PgUniqueViolation = type('_Never', (Exception,), {})


def _parse_dt(value):
    """Parse a timestamp that is either a string (SQLite) or datetime (PostgreSQL)."""
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    return value  # already a datetime object from psycopg2


def _fmt_dt(value):
    """Format a timestamp for chart labels — works for both backends."""
    if isinstance(value, str):
        return value[:16].replace('T', ' ')
    if value is not None:
        return value.strftime('%Y-%m-%d %H:%M')
    return ''

from flask import Flask, render_template, redirect, url_for, request, jsonify, flash, session
from flask_login import (
    LoginManager, login_user, logout_user,
    login_required, current_user, UserMixin,
)
from werkzeug.security import generate_password_hash, check_password_hash

from database import init_db, get_db, close_db
from stocks import TICKERS, TICKER_NAMES, ensure_prices_loaded

app = Flask(__name__)
app.secret_key = 'stock-sim-secret-change-in-prod-2024'

login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Пожалуйста, войдите в систему.'

app.teardown_appcontext(close_db)

# ---------------------------------------------------------------------------
# User model
# ---------------------------------------------------------------------------

class User(UserMixin):
    def __init__(self, id, username, cash_balance):
        self.id = id
        self.username = username
        self.cash_balance = cash_balance

    def get_id(self):
        return str(self.id)


@login_manager.user_loader
def load_user(user_id):
    row = get_db().execute(
        'SELECT id, username, cash_balance FROM users WHERE id = ?', (user_id,)
    ).fetchone()
    if row:
        return User(row['id'], row['username'], row['cash_balance'])
    return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def record_portfolio_value(user_id, db):
    """Snapshot the user's total portfolio value into history."""
    user = db.execute(
        'SELECT cash_balance FROM users WHERE id = ?', (user_id,)
    ).fetchone()
    holdings = db.execute(
        'SELECT ticker, shares FROM holdings WHERE user_id = ? AND shares > 0',
        (user_id,),
    ).fetchall()
    prices = {
        r['ticker']: r['price']
        for r in db.execute('SELECT ticker, price FROM stock_prices').fetchall()
    }
    stocks_value = sum(h['shares'] * prices.get(h['ticker'], 0) for h in holdings)
    total = user['cash_balance'] + stocks_value

    db.execute(
        'INSERT INTO portfolio_history (user_id, total_value, cash) VALUES (?, ?, ?)',
        (user_id, total, user['cash_balance']),
    )
    db.commit()


def calc_portfolio(user_id, db):
    """Return (cash, stocks_value, total, pnl, pnl_pct, holdings_list)."""
    user = db.execute(
        'SELECT cash_balance FROM users WHERE id = ?', (user_id,)
    ).fetchone()
    cash = user['cash_balance']

    holdings_rows = db.execute(
        'SELECT ticker, shares, avg_price FROM holdings WHERE user_id = ? AND shares > 0',
        (user_id,),
    ).fetchall()
    prices = {
        r['ticker']: dict(r)
        for r in db.execute('SELECT * FROM stock_prices').fetchall()
    }

    holdings_list = []
    stocks_value = 0.0
    for h in holdings_rows:
        t = h['ticker']
        p = prices.get(t, {})
        cur_price = p.get('price', 0) or 0
        value = h['shares'] * cur_price
        stocks_value += value
        cost = h['shares'] * h['avg_price']
        gain = value - cost
        gain_pct = (gain / cost * 100) if cost else 0
        holdings_list.append({
            'ticker': t,
            'name': TICKER_NAMES.get(t, t),
            'shares': h['shares'],
            'avg_price': h['avg_price'],
            'current_price': cur_price,
            'value': value,
            'gain': gain,
            'gain_pct': gain_pct,
            'change_pct': p.get('change_pct', 0) or 0,
        })

    total = cash + stocks_value
    pnl = total - 10_000
    pnl_pct = pnl / 10_000 * 100
    return cash, stocks_value, total, pnl, pnl_pct, holdings_list


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        action = request.form.get('action')
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        db = get_db()

        if action == 'register':
            if len(username) < 3:
                flash('Имя пользователя должно быть не менее 3 символов.', 'error')
            elif len(password) < 4:
                flash('Пароль должен быть не менее 4 символов.', 'error')
            elif db.execute('SELECT id FROM users WHERE username = ?', (username,)).fetchone():
                flash('Такое имя пользователя уже занято.', 'error')
            else:
                pw_hash = generate_password_hash(password, method='pbkdf2:sha256')
                try:
                    db.execute(
                        'INSERT INTO users (username, password_hash) VALUES (?, ?)',
                        (username, pw_hash),
                    )
                    db.commit()
                except (sqlite3.IntegrityError, _PgUniqueViolation):
                    db.rollback()
                    flash('This username is already taken. Please choose another one.', 'error')
                else:
                    row = db.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
                    user = User(row['id'], row['username'], row['cash_balance'])
                    # Seed history with starting balance
                    record_portfolio_value(user.id, db)
                    login_user(user)
                    flash('Добро пожаловать! Вам начислено $10,000.', 'success')
                    return redirect(url_for('dashboard'))

        elif action == 'login':
            row = db.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
            if row and check_password_hash(row['password_hash'], password):
                user = User(row['id'], row['username'], row['cash_balance'])
                login_user(user)
                return redirect(url_for('dashboard'))
            else:
                flash('Неверное имя пользователя или пароль.', 'error')

    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


@app.route('/dashboard')
@login_required
def dashboard():
    db = get_db()
    cash, stocks_value, total, pnl, pnl_pct, holdings_list = calc_portfolio(current_user.id, db)

    # Record snapshot at most once per hour
    last = db.execute(
        'SELECT created_at FROM portfolio_history WHERE user_id = ? ORDER BY id DESC LIMIT 1',
        (current_user.id,),
    ).fetchone()
    should_record = True
    if last:
        try:
            last_dt = _parse_dt(last['created_at'])
            if datetime.now() - last_dt < timedelta(hours=1):
                should_record = False
        except Exception:
            pass
    if should_record:
        record_portfolio_value(current_user.id, db)

    # Chart data — last 30 snapshots
    history = db.execute(
        'SELECT total_value, created_at FROM portfolio_history '
        'WHERE user_id = ? ORDER BY id DESC LIMIT 30',
        (current_user.id,),
    ).fetchall()
    history = list(reversed(history))

    chart_labels = [_fmt_dt(h['created_at']) for h in history]
    chart_data = [round(h['total_value'], 2) for h in history]

    if not chart_data:
        chart_labels = ['Старт']
        chart_data = [10000.0]

    top_holdings = sorted(holdings_list, key=lambda x: x['value'], reverse=True)[:5]

    return render_template(
        'dashboard.html',
        cash=cash,
        stocks_value=stocks_value,
        total=total,
        pnl=pnl,
        pnl_pct=pnl_pct,
        top_holdings=top_holdings,
        chart_labels=json.dumps(chart_labels),
        chart_data=json.dumps(chart_data),
    )


@app.route('/market')
@login_required
def market():
    db = get_db()
    rows = db.execute('SELECT * FROM stock_prices ORDER BY ticker').fetchall()
    stocks = [dict(r) for r in rows]
    # Add any tickers missing from cache
    cached = {r['ticker'] for r in rows}
    for t in TICKERS:
        if t not in cached:
            stocks.append({
                'ticker': t, 'name': TICKER_NAMES.get(t, t),
                'price': None, 'change_pct': None,
            })
    stocks.sort(key=lambda x: x['ticker'])
    return render_template('market.html', stocks=stocks)


@app.route('/portfolio')
@login_required
def portfolio():
    db = get_db()
    cash, stocks_value, total, pnl, pnl_pct, holdings_list = calc_portfolio(current_user.id, db)
    holdings_list.sort(key=lambda x: x['value'], reverse=True)
    return render_template(
        'portfolio.html',
        cash=cash,
        stocks_value=stocks_value,
        total=total,
        pnl=pnl,
        pnl_pct=pnl_pct,
        holdings=holdings_list,
    )


@app.route('/leaderboard')
@login_required
def leaderboard():
    db = get_db()
    users = db.execute('SELECT id, username, cash_balance FROM users').fetchall()
    prices = {
        r['ticker']: r['price']
        for r in db.execute('SELECT ticker, price FROM stock_prices').fetchall()
    }

    board = []
    for u in users:
        holdings = db.execute(
            'SELECT ticker, shares FROM holdings WHERE user_id = ? AND shares > 0',
            (u['id'],),
        ).fetchall()
        stocks_val = sum(h['shares'] * prices.get(h['ticker'], 0) for h in holdings)
        total = u['cash_balance'] + stocks_val
        pnl = total - 10_000
        pnl_pct = pnl / 10_000 * 100
        board.append({
            'username': u['username'],
            'total': total,
            'pnl': pnl,
            'pnl_pct': pnl_pct,
            'is_me': u['id'] == current_user.id,
        })

    board.sort(key=lambda x: x['pnl_pct'], reverse=True)
    return render_template('leaderboard.html', board=board)


# ---------------------------------------------------------------------------
# Admin dashboard
# ---------------------------------------------------------------------------

ADMIN_PASSWORD = 'admin123'


@app.route('/admin', methods=['GET', 'POST'])
def admin():
    # Logout
    if request.args.get('logout'):
        session.pop('admin_ok', None)
        return redirect(url_for('admin'))

    # Login attempt
    error = None
    if request.method == 'POST':
        if request.form.get('password') == ADMIN_PASSWORD:
            session['admin_ok'] = True
        else:
            error = 'Incorrect password.'

    if not session.get('admin_ok'):
        return render_template('admin.html', authenticated=False, error=error)

    db = get_db()
    today     = date.today()
    week_ago  = today - timedelta(days=7)

    # User counts
    total_users = db.execute(
        'SELECT COUNT(*) AS cnt FROM users'
    ).fetchone()['cnt']

    new_today = db.execute(
        'SELECT COUNT(*) AS cnt FROM users WHERE created_at >= ?',
        (today.isoformat(),),
    ).fetchone()['cnt']

    new_week = db.execute(
        'SELECT COUNT(*) AS cnt FROM users WHERE created_at >= ?',
        (week_ago.isoformat(),),
    ).fetchone()['cnt']

    # Transaction counts by type
    buys = sells = 0
    for row in db.execute(
        'SELECT type, COUNT(*) AS cnt FROM transactions GROUP BY type'
    ).fetchall():
        if row['type'] == 'buy':
            buys = row['cnt']
        elif row['type'] == 'sell':
            sells = row['cnt']

    # Top 5 most active users
    top_users = [dict(r) for r in db.execute('''
        SELECT u.username, COUNT(t.id) AS cnt
        FROM transactions t
        JOIN users u ON t.user_id = u.id
        GROUP BY u.id, u.username
        ORDER BY cnt DESC
        LIMIT 5
    ''').fetchall()]

    # Top 5 most purchased stocks
    top_stocks = [dict(r) for r in db.execute('''
        SELECT ticker, COUNT(*) AS cnt
        FROM transactions
        WHERE type = 'buy'
        GROUP BY ticker
        ORDER BY cnt DESC
        LIMIT 5
    ''').fetchall()]

    # Total virtual money in circulation (cash + stock holdings)
    total_cash = db.execute(
        'SELECT COALESCE(SUM(cash_balance), 0) AS s FROM users'
    ).fetchone()['s'] or 0

    total_stocks_value = db.execute('''
        SELECT COALESCE(SUM(h.shares * sp.price), 0) AS s
        FROM holdings h
        JOIN stock_prices sp ON h.ticker = sp.ticker
        WHERE h.shares > 0
    ''').fetchone()['s'] or 0

    total_in_circulation = total_cash + total_stocks_value

    # All users with portfolio value
    prices = {
        r['ticker']: r['price']
        for r in db.execute('SELECT ticker, price FROM stock_prices').fetchall()
    }
    users_list = []
    for u in db.execute(
        'SELECT id, username, cash_balance, created_at FROM users ORDER BY created_at DESC'
    ).fetchall():
        holdings = db.execute(
            'SELECT ticker, shares FROM holdings WHERE user_id = ? AND shares > 0',
            (u['id'],),
        ).fetchall()
        stocks_val = sum(h['shares'] * (prices.get(h['ticker']) or 0) for h in holdings)
        total = u['cash_balance'] + stocks_val
        reg = u['created_at']
        users_list.append({
            'username':   u['username'],
            'registered': reg.strftime('%Y-%m-%d') if hasattr(reg, 'strftime') else str(reg)[:10],
            'cash':       u['cash_balance'],
            'total':      total,
            'pnl_pct':    (total - 10_000) / 10_000 * 100,
        })

    return render_template('admin.html',
        authenticated       = True,
        total_users         = total_users,
        new_today           = new_today,
        new_week            = new_week,
        buys                = buys,
        sells               = sells,
        top_users           = top_users,
        top_stocks          = top_stocks,
        total_in_circulation= total_in_circulation,
        users_list          = users_list,
    )


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

@app.route('/api/cash')
@login_required
def api_cash():
    user = get_db().execute(
        'SELECT cash_balance FROM users WHERE id = ?', (current_user.id,)
    ).fetchone()
    return jsonify({'cash': user['cash_balance']})


@app.route('/api/prices')
@login_required
def api_prices():
    db = get_db()
    rows = db.execute('SELECT * FROM stock_prices').fetchall()
    return jsonify({r['ticker']: dict(r) for r in rows})


@app.route('/api/buy', methods=['POST'])
@login_required
def api_buy():
    data = request.get_json()
    ticker = (data.get('ticker') or '').upper().strip()
    try:
        shares = float(data.get('shares', 0))
    except (ValueError, TypeError):
        return jsonify({'error': 'Некорректное количество акций'}), 400

    if shares <= 0:
        return jsonify({'error': 'Количество должно быть больше 0'}), 400
    if ticker not in TICKERS:
        return jsonify({'error': 'Тикер не найден'}), 400

    db = get_db()
    price_row = db.execute(
        'SELECT price FROM stock_prices WHERE ticker = ?', (ticker,)
    ).fetchone()
    if not price_row or not price_row['price']:
        return jsonify({'error': 'Цена недоступна, попробуйте позже'}), 400

    price = price_row['price']
    total_cost = price * shares

    user = db.execute(
        'SELECT cash_balance FROM users WHERE id = ?', (current_user.id,)
    ).fetchone()
    if user['cash_balance'] < total_cost:
        return jsonify({'error': f'Недостаточно средств. Нужно ${total_cost:,.2f}, доступно ${user["cash_balance"]:,.2f}'}), 400

    # Deduct cash
    db.execute(
        'UPDATE users SET cash_balance = cash_balance - ? WHERE id = ?',
        (total_cost, current_user.id),
    )

    # Update holdings (upsert with weighted avg price)
    existing = db.execute(
        'SELECT shares, avg_price FROM holdings WHERE user_id = ? AND ticker = ?',
        (current_user.id, ticker),
    ).fetchone()
    if existing:
        new_shares = existing['shares'] + shares
        new_avg = (existing['shares'] * existing['avg_price'] + shares * price) / new_shares
        db.execute(
            'UPDATE holdings SET shares = ?, avg_price = ? WHERE user_id = ? AND ticker = ?',
            (new_shares, new_avg, current_user.id, ticker),
        )
    else:
        db.execute(
            'INSERT INTO holdings (user_id, ticker, shares, avg_price) VALUES (?, ?, ?, ?)',
            (current_user.id, ticker, shares, price),
        )

    # Record transaction
    db.execute(
        'INSERT INTO transactions (user_id, ticker, shares, price, type) VALUES (?, ?, ?, ?, ?)',
        (current_user.id, ticker, shares, price, 'buy'),
    )
    db.commit()
    record_portfolio_value(current_user.id, db)

    return jsonify({
        'success': True,
        'message': f'Куплено {shares:g} акций {ticker} по ${price:,.2f}',
        'new_cash': db.execute('SELECT cash_balance FROM users WHERE id = ?', (current_user.id,)).fetchone()['cash_balance'],
    })


@app.route('/api/sell', methods=['POST'])
@login_required
def api_sell():
    data = request.get_json()
    ticker = (data.get('ticker') or '').upper().strip()
    try:
        shares = float(data.get('shares', 0))
    except (ValueError, TypeError):
        return jsonify({'error': 'Некорректное количество акций'}), 400

    if shares <= 0:
        return jsonify({'error': 'Количество должно быть больше 0'}), 400

    db = get_db()
    holding = db.execute(
        'SELECT shares FROM holdings WHERE user_id = ? AND ticker = ?',
        (current_user.id, ticker),
    ).fetchone()
    if not holding or holding['shares'] < shares:
        owned = holding['shares'] if holding else 0
        return jsonify({'error': f'Недостаточно акций. У вас {owned:g} шт.'}), 400

    price_row = db.execute(
        'SELECT price FROM stock_prices WHERE ticker = ?', (ticker,)
    ).fetchone()
    if not price_row or not price_row['price']:
        return jsonify({'error': 'Цена недоступна'}), 400

    price = price_row['price']
    proceeds = price * shares

    # Add cash
    db.execute(
        'UPDATE users SET cash_balance = cash_balance + ? WHERE id = ?',
        (proceeds, current_user.id),
    )

    # Update or remove holding
    new_shares = holding['shares'] - shares
    if new_shares < 1e-9:
        db.execute(
            'DELETE FROM holdings WHERE user_id = ? AND ticker = ?',
            (current_user.id, ticker),
        )
    else:
        db.execute(
            'UPDATE holdings SET shares = ? WHERE user_id = ? AND ticker = ?',
            (new_shares, current_user.id, ticker),
        )

    db.execute(
        'INSERT INTO transactions (user_id, ticker, shares, price, type) VALUES (?, ?, ?, ?, ?)',
        (current_user.id, ticker, shares, price, 'sell'),
    )
    db.commit()
    record_portfolio_value(current_user.id, db)

    return jsonify({
        'success': True,
        'message': f'Продано {shares:g} акций {ticker} по ${price:,.2f}',
        'new_cash': db.execute('SELECT cash_balance FROM users WHERE id = ?', (current_user.id,)).fetchone()['cash_balance'],
    })


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    init_db(app)
    with app.app_context():
        ensure_prices_loaded()
    from scheduler import start_scheduler
    start_scheduler(app)
    app.run(debug=True, use_reloader=False, host='0.0.0.0', port=5000)
