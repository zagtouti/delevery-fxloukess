from database import create_tables, check_connection
from models import *
from sqlalchemy.orm import Session
from database import SessionLocal
from passlib.context import CryptContext
from config import STATION_CODE, STATION_NAME

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def setup():
    print("Starting fxloukess setup...")

    # Step 1 - Check database connection
    if not check_connection():
        print("Cannot connect to database. Check PostgreSQL is running.")
        return

    # Step 2 - Create all tables
    create_tables()

    # Step 3 - Create first station
    db: Session = SessionLocal()

    try:
        existing_station = db.query(Station).first()
        if existing_station:
            print("Station already exists - skipping station creation")
            station = existing_station
        else:
            station = Station(
                code=STATION_CODE,
                name=STATION_NAME,
                wilaya="Oran",
                address="Bir Djir, Oran",
                phone="0550000000"
            )
            db.add(station)
            db.commit()
            db.refresh(station)
            print(f"Station created: {station.name}")

        # Step 4 - Create superadmin account
        existing_admin = db.query(User).filter(
            User.role == RoleEnum.superadmin
        ).first()

        if existing_admin:
            print("Superadmin already exists - skipping")
        else:
            superadmin = User(
                station_id=station.id,
                full_name="Super Admin",
                phone="0550000001",
                hashed_password=pwd_context.hash("admin123"),
                role=RoleEnum.superadmin,
                is_active=True
            )
            db.add(superadmin)
            db.commit()
            print("Superadmin created")
            print("  Phone: 0550000001")
            print("  Password: admin123")
            print("  !! Change this password immediately after first login !!")

        # Step 5 - Create first shift
        existing_shift = db.query(Shift).first()
        if existing_shift:
            print("Shift already exists - skipping")
        else:
            admin = db.query(User).filter(
                User.role == RoleEnum.superadmin
            ).first()
            shift = Shift(
                station_id=station.id,
                shift_type=ShiftTypeEnum.morning,
                opened_by=admin.id,
                is_closed=False
            )
            db.add(shift)
            db.commit()
            print("First shift created: morning")

        print("")
        print("Setup complete. Run main.py to start the server.")

    except Exception as e:
        print(f"Setup failed: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    setup()