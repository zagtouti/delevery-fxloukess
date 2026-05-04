"""
migrate.py — Create all tables and seed a default superadmin.
Run once: python migrate.py
Safe to re-run (idempotent).
"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))

from database import create_tables, SessionLocal
from models import RoleEnum, Station, User
from passlib.context import CryptContext
from config import STATION_CODE, STATION_NAME

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


def seed() -> None:
    print("Creating tables…")
    create_tables()

    db = SessionLocal()
    try:
        # ── Station
        station = db.query(Station).filter(Station.code == STATION_CODE).first()
        if not station:
            station = Station(code=STATION_CODE, name=STATION_NAME,
                              wilaya="Oran", is_active=True)
            db.add(station)
            db.flush()
            print(f"  Station created: {STATION_CODE} — {STATION_NAME}")
        else:
            print(f"  Station exists:  {station.code}")

        # ── Superadmin
        admin = db.query(User).filter(User.phone == "0555000000").first()
        if not admin:
            admin = User(
                station_id      = station.id,
                full_name       = "Super Admin",
                phone           = "0555000000",
                hashed_password = _pwd.hash("admin1234"),
                role            = RoleEnum.superadmin,
                is_active       = True,
                language        = "fr",
            )
            db.add(admin)
            print("  Superadmin created:")
            print("    Phone:    0555000000")
            print("    Password: admin1234")
            print("  ⚠  CHANGE THIS PASSWORD IMMEDIATELY!")
        else:
            print(f"  Superadmin exists: {admin.phone}")

        db.commit()
        print("Migration complete ✓")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
