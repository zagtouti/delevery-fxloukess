import os
from dotenv import load_dotenv

load_dotenv()

# =========================
# Helpers
# =========================
def _env_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _cookie_samesite(value: str | None = None) -> str:
    if not value:
        return "lax"
    normalized = value.strip().lower()
    return normalized if normalized in {"lax", "strict", "none"} else "lax"


def _cookie_path(value: str | None = None) -> str:
    if not value:
        return "/"
    normalized = value.strip()
    return normalized if normalized.startswith("/") else "/"


def _cors_origins(value: str | None = None) -> list[str]:
    if not value:
        return ["http://localhost:3000", "http://127.0.0.1:3000"]
    origins = [v.strip() for v in value.split(",") if v.strip()]
    return origins or ["http://localhost:3000", "http://127.0.0.1:3000"]


# ── Database ──────────────────────────────────────────────────────────────────
DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:fxloukess123@localhost:5432/fxloukess"
)

# ── Security ──────────────────────────────────────────────────────────────────
SECRET_KEY: str = os.getenv(
    "SECRET_KEY",
    "CHANGE-THIS-IN-PRODUCTION-USE-DOTENV"
)
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 480       # 8 hours
DRIVER_TOKEN_EXPIRE_DAYS    = 365       # Drivers get long-lived tokens

# Rate limiting (login)
LOGIN_RATE_LIMIT = "10/minute"

# CORS (comma-separated origins; default is local dev only)
CORS_ORIGINS: list[str] = _cors_origins(os.getenv("CORS_ORIGINS"))
COOKIE_SAMESITE: str = _cookie_samesite(os.getenv("COOKIE_SAMESITE"))
COOKIE_SECURE: bool = _env_bool(os.getenv("COOKIE_SECURE"), default=False)
CSRF_PROTECT: bool = _env_bool(os.getenv("CSRF_PROTECT"), default=True)
COOKIE_PATH: str = _cookie_path(os.getenv("COOKIE_PATH"))

if COOKIE_SAMESITE == "none":
    COOKIE_SECURE = True


# ── Station ───────────────────────────────────────────────────────────────────
STATION_CODE: str = os.getenv("STATION_CODE", "ORA")
STATION_NAME: str = os.getenv("STATION_NAME", "PDEX Oran")

# ── Business rules ────────────────────────────────────────────────────────────
DRIVER_CASH_ALERT_THRESHOLD = 5_000    # DZD — auto-alert when driver exceeds this
MAX_DELIVERY_ATTEMPTS       = 3
DELIVERY_FEE_DEFAULT        = 400.0    # DZD
RETURN_FEE_DEFAULT          = 200.0    # DZD

# Payout thresholds
PAYOUT_SINGLE_ADMIN_LIMIT      = 50_000    # DZD
PAYOUT_REGIONAL_APPROVAL_LIMIT = 200_000   # DZD

# ── Archive ───────────────────────────────────────────────────────────────────
ARCHIVE_AFTER_DAYS = 90

# ── Storage ───────────────────────────────────────────────────────────────────
PHOTO_MAX_SIZE_KB = 500

# ── Shifts ────────────────────────────────────────────────────────────────────
SHIFTS = {
    "morning":   {"start": "06:00", "end": "14:00"},
    "afternoon": {"start": "14:00", "end": "22:00"},
    "night":     {"start": "22:00", "end": "06:00"},
}

# ── Wilaya pricing (default — overridable via admin UI) ───────────────────────
DEFAULT_WILAYA_PRICES: dict[str, dict[str, int]] = {
    "Adrar": {"home": 700, "desk": 500}, "Chlef": {"home": 500, "desk": 400},
    "Laghouat": {"home": 600, "desk": 500}, "Oum El Bouaghi": {"home": 500, "desk": 400},
    "Batna": {"home": 500, "desk": 400}, "Béjaïa": {"home": 500, "desk": 400},
    "Biskra": {"home": 550, "desk": 450}, "Béchar": {"home": 700, "desk": 500},
    "Blida": {"home": 400, "desk": 350}, "Bouira": {"home": 500, "desk": 400},
    "Tamanrasset": {"home": 800, "desk": 600}, "Tébessa": {"home": 550, "desk": 450},
    "Tlemcen": {"home": 500, "desk": 400}, "Tiaret": {"home": 500, "desk": 400},
    "Tizi Ouzou": {"home": 500, "desk": 400}, "Alger": {"home": 400, "desk": 350},
    "Djelfa": {"home": 550, "desk": 450}, "Jijel": {"home": 500, "desk": 400},
    "Sétif": {"home": 500, "desk": 400}, "Saïda": {"home": 500, "desk": 400},
    "Skikda": {"home": 500, "desk": 400}, "Sidi Bel Abbès": {"home": 500, "desk": 400},
    "Annaba": {"home": 500, "desk": 400}, "Guelma": {"home": 500, "desk": 400},
    "Constantine": {"home": 450, "desk": 350}, "Médéa": {"home": 450, "desk": 350},
    "Mostaganem": {"home": 500, "desk": 400}, "M'Sila": {"home": 500, "desk": 400},
    "Mascara": {"home": 500, "desk": 400}, "Ouargla": {"home": 650, "desk": 500},
    "Oran": {"home": 400, "desk": 350}, "El Bayadh": {"home": 650, "desk": 500},
    "Illizi": {"home": 800, "desk": 600}, "Bordj Bou Arréridj": {"home": 500, "desk": 400},
    "Boumerdès": {"home": 400, "desk": 350}, "El Tarf": {"home": 500, "desk": 400},
    "Tindouf": {"home": 800, "desk": 600}, "Tissemsilt": {"home": 550, "desk": 450},
    "El Oued": {"home": 650, "desk": 500}, "Khenchela": {"home": 550, "desk": 450},
    "Souk Ahras": {"home": 550, "desk": 450}, "Tipaza": {"home": 400, "desk": 350},
    "Mila": {"home": 500, "desk": 400}, "Aïn Defla": {"home": 450, "desk": 350},
    "Naâma": {"home": 650, "desk": 500}, "Aïn Témouchent": {"home": 500, "desk": 400},
    "Ghardaïa": {"home": 650, "desk": 500}, "Relizane": {"home": 500, "desk": 400},
    "Timimoun": {"home": 750, "desk": 550}, "Bordj Badji Mokhtar": {"home": 850, "desk": 650},
    "Ouled Djellal": {"home": 650, "desk": 500}, "Béni Abbès": {"home": 750, "desk": 550},
    "In Salah": {"home": 800, "desk": 600}, "In Guezzam": {"home": 850, "desk": 650},
    "Touggourt": {"home": 650, "desk": 500}, "Djanet": {"home": 850, "desk": 650},
    "El M'Ghair": {"home": 650, "desk": 500}, "El Meniaa": {"home": 700, "desk": 550},
}

# Status → hex colour (for frontend badges)
STATUS_COLORS = {
    "created": "#3b82f6", "assigned": "#8b5cf6",
    "out_for_delivery": "#f97316", "delivered": "#22c55e",
    "failed": "#ef4444", "returned": "#a855f7",
    "rescheduled": "#eab308", "address_changed": "#06b6d4",
    "waiting_for_client": "#f59e0b", "held_at_station": "#6b7280",
    "partially_delivered": "#84cc16", "lost": "#1f2937",
    "sync_conflict": "#dc2626",
}
