from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from database import get_db
from models import *
from routers.auth import get_current_user
from routers.packages import driver_cash_on_hand
from passlib.context import CryptContext

router = APIRouter()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

@router.get("")
async def list_drivers(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    drivers = db.query(Driver).filter(
        Driver.station_id == current_user.station_id
    ).all()
    return [format_driver(d, db) for d in drivers]

@router.get("/{driver_id}")
async def get_driver(
    driver_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    d = db.query(Driver).filter(
        Driver.id == driver_id,
        Driver.station_id == current_user.station_id
    ).first()
    if not d:
        raise HTTPException(status_code=404, detail="Livreur introuvable")
    return format_driver(d, db, full=True)

@router.post("")
async def create_driver(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    body = await request.json()

    required = ["full_name", "phone", "wilaya", "pin"]
    for field in required:
        if not body.get(field):
            raise HTTPException(
                status_code=400,
                detail=f"Champ requis: {field}"
            )

    existing = db.query(User).filter(
        User.phone == body["phone"]
    ).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail="Ce numéro est déjà utilisé"
        )

    user = User(
        station_id=current_user.station_id,
        full_name=body["full_name"],
        phone=body["phone"],
        hashed_password=pwd_context.hash(body["pin"]),
        pin=body["pin"],
        role=RoleEnum.driver,
        is_active=True
    )
    db.add(user)
    db.flush()

    driver = Driver(
        station_id=current_user.station_id,
        user_id=user.id,
        full_name=body["full_name"],
        phone=body["phone"],
        wilaya=body["wilaya"],
        is_active=True
    )
    db.add(driver)

    db.add(AuditLog(
        user_id=current_user.id,
        station_id=current_user.station_id,
        action="driver_created",
        entity_type="driver",
        entity_id=driver.id,
        new_value={"full_name": driver.full_name}
    ))

    db.commit()
    db.refresh(driver)
    return format_driver(driver, db)

@router.patch("/{driver_id}/toggle")
async def toggle_driver(
    driver_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    driver = db.query(Driver).filter(
        Driver.id == driver_id,
        Driver.station_id == current_user.station_id
    ).first()
    if not driver:
        raise HTTPException(status_code=404, detail="Livreur introuvable")
    driver.is_active = not driver.is_active
    db.commit()
    return format_driver(driver, db)

def format_driver(d: Driver, db: Session, full: bool = False) -> dict:
    cash = driver_cash_on_hand(db, d.id)
    packages_out = db.query(Package).filter(
        Package.driver_id == d.id,
        Package.status == PackageStatusEnum.out_for_delivery
    ).count()
    delivered_today = db.query(Package).filter(
        Package.driver_id == d.id,
        Package.status == PackageStatusEnum.delivered,
        Package.delivered_at >= datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    ).count()
    result = {
        "id": d.id,
        "full_name": d.full_name,
        "phone": d.phone,
        "wilaya": d.wilaya,
        "is_active": d.is_active,
        "cash_on_hand": cash,
        "packages_out": packages_out,
        "delivered_today": delivered_today,
        "created_at": d.created_at.isoformat() if d.created_at else None,
    }
    if full:
        result["packages"] = [
            {
                "tracking_id": p.tracking_id,
                "recipient_name": p.recipient_name,
                "wilaya": p.wilaya,
                "cod_amount": p.cod_amount,
                "status": p.status.value if hasattr(p.status, 'value') else p.status
            }
            for p in d.packages
        ]
    return result

from datetime import datetime, timezone