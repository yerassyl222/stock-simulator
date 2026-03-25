# StockSim — Симулятор фондового рынка

Учебный симулятор для школьников и студентов. Торгуй 50 реальными акциями с виртуальными $10,000.

## Быстрый старт

### 1. Установить зависимости

```bash
pip install -r requirements.txt
```

### 2. Запустить приложение

```bash
python app.py
```

При первом запуске:
- автоматически создаётся база данных `stock_simulator.db`
- загружаются актуальные котировки через yfinance (занимает ~20-30 секунд)

### 3. Открыть в браузере

```
http://localhost:5000
```

---

## Что умеет приложение

| Страница | Описание |
|----------|----------|
| `/login` | Регистрация и вход. При регистрации выдаётся **$10,000** |
| `/dashboard` | Баланс, стоимость портфеля, график, топ-5 позиций |
| `/market` | Список 50 акций с ценами. Поиск, кнопка «Купить» |
| `/portfolio` | Все открытые позиции с прибылью/убытком |
| `/leaderboard` | Рейтинг всех участников по доходности |

## Доступные акции (50 штук)

`AAPL` `MSFT` `GOOGL` `AMZN` `TSLA` `META` `NVDA` `NFLX`
`JPM` `V` `WMT` `DIS` `PYPL` `INTC` `AMD` `BABA` `UBER`
`LYFT` `SNAP` `ABNB` `SPOT` `SHOP` `SQ` `COIN` `HOOD`
`NKE` `MCD` `SBUX` `KO` `PEP` `JNJ` `PFE` `MRNA` `ABBV`
`XOM` `CVX` `BA` `GE` `F` `GM` `RIVN` `LCID` `PLTR` `RBLX`
`U` `DKNG` `PENN` `MGM` `WYNN` `LVS`

## Требования

- Python 3.9+
- Интернет-соединение (для загрузки котировок)

## Структура проекта

```
stock-simulator/
├── app.py           # Flask-приложение, все маршруты
├── database.py      # Инициализация SQLite
├── stocks.py        # Работа с yfinance, список тикеров
├── scheduler.py     # Обновление цен каждый день в 09:00
├── templates/
│   ├── base.html
│   ├── login.html
│   ├── dashboard.html
│   ├── market.html
│   ├── portfolio.html
│   └── leaderboard.html
├── static/
│   ├── style.css
│   └── script.js
├── requirements.txt
└── README.md
```

## Технологии

- **Backend**: Python + Flask + Flask-Login
- **База данных**: SQLite (файл `stock_simulator.db`)
- **Котировки**: yfinance (обновляются ежедневно в 09:00)
- **Frontend**: HTML + CSS + JavaScript (без фреймворков)
- **Графики**: Chart.js
