# fxloukess v2.0

Système de gestion de station de livraison — FastAPI + PostgreSQL.

## Structure

```
fxloukess/
├── main.py              # Entry point, routers, error handlers
├── config.py            # Settings (loads from .env)
├── models.py            # All SQLAlchemy models
├── database.py          # Engine, session, helpers
├── migrate.py           # Create tables + seed superadmin
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── routers/
│   ├── auth.py          # Login, logout, JWT, sessions
│   ├── packages.py      # Full package lifecycle + public tracking
│   ├── drivers.py       # Driver CRUD, cash management
│   ├── sellers.py       # Seller CRUD, ledger
│   ├── frontdesk.py     # Shift, receiving, petty cash
│   ├── dispatch.py      # Assign, depart
│   ├── returns.py       # Returns zone, reschedule, payouts
│   └── superadmin.py    # Users, stats, finance, alerts, audit, prices
└── templates/
    ├── login.html        # All roles
    ├── superadmin.html   # Superadmin / regional manager
    ├── frontdesk.html    # Front desk agent
    ├── dispatch.html     # Dispatch agent
    ├── returns.html      # Returns agent
    ├── driver.html       # Mobile view for drivers
    └── track.html        # Public tracking (no auth)
```

## Quick Start (Docker)

```bash
# 1. Copy env file
cp .env.example .env
# Edit .env — set a real SECRET_KEY!

# 2. Start services
docker compose up -d

# 3. Create tables + seed superadmin
docker compose exec app python migrate.py

# 4. Open http://localhost:8000
# Login: 0555000000 / admin1234
# CHANGE THE PASSWORD IMMEDIATELY
```

## Quick Start (local)

```bash
# 1. Python 3.12+
pip install -r requirements.txt

# 2. Set up PostgreSQL and create .env
cp .env.example .env  # fill in DATABASE_URL and SECRET_KEY

# 3. Migrate
python migrate.py

# 4. Run
uvicorn main:app --reload --port 8000
```

## API Docs

Open http://localhost:8000/api/docs (Swagger UI)

## Role → Page mapping

| Role              | URL           |
|-------------------|---------------|
| superadmin        | /superadmin   |
| regional_manager  | /superadmin   |
| frontdesk         | /frontdesk    |
| dispatch          | /dispatch     |
| returns           | /returns      |
| driver            | /driver       |
| Public            | /track        |

## Security notes

- `SECRET_KEY` must be a long random string — never commit it to git
- Change the default superadmin password immediately after setup
- In production: set `allow_origins` to your actual domain in `main.py`
- Rate limiting on `/api/auth/login`: 10 requests/minute per IP
- All sessions are tracked in DB — force-logout available from superadmin panel
