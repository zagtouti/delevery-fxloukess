"""
migrate.py  — run once to create tables + seed a superadmin user
Usage: python migrate.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from database import create_tables, SessionLocal
from models import User, Station, RoleEnum
from passlib.context import CryptContext
from config import STATION_CODE, STATION_NAME

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def seed():
    create_tables()
    db = SessionLocal()
    try:
        station = db.query(Station).filter(Station.code == STATION_CODE).first()
        if not station:
            station = Station(code=STATION_CODE, name=STATION_NAME, wilaya="Oran", is_active=True)
            db.add(station)
            db.flush()
            print(f"Station created: {STATION_CODE} — {STATION_NAME}")
        else:
            print(f"Station exists: {station.code}")

        admin = db.query(User).filter(User.phone == "0555000000").first()
        if not admin:
            admin = User(
                station_id=station.id, full_name="Super Admin",
                phone="0555000000", hashed_password=pwd_context.hash("admin1234"),
                role=RoleEnum.superadmin, is_active=True, language="fr"
            )
            db.add(admin)
            print("Superadmin created — phone: 0555000000 / password: admin1234")
            print("WARNING: Change this password immediately!")
        else:
            print("Superadmin already exists.")

        db.commit()
        print("Migration complete.")
    finally:
        db.close()

if __name__ == "__main__":
    seed()
