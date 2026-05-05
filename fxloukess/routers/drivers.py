"""routers/drivers.py — v3. Uses utils.py, adds bulk cash-collection (Payment plugin)."""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from database import get_db
from models import AuditLog, Driver, DriverCashLog, Package, PackageStatusEnum, RoleEnum, User
from routers.auth import get_current_user
from utils import audit, driver_cash_balance, ev, open_shift, record_cash_event

logger = logging.getLogger("fxloukess.drivers")
router = APIRouter()
_pwd   = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _fmt(d: Driver, db: Session, full: bool = False) -> dict:
    cash  = driver_cash_balance(db, d.id)
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    out   = db.query(Package).filter(
        Package.driver_id == d.id,
        Package.status    == PackageStatusEnum.out_for_delivery,
    ).count()
    delivered_today = db.query(Package).filter(
        Package.driver_id   == d.id,
        Package.status      == PackageStatusEnum.delivered,
        Package.delivered_at >= today,
    ).count()
    result: dict = {
        "id":             d.id,
        "user_id":        d.user_id,
        "full_name":      d.full_name,
        "phone":          d.phone,
        "wilaya":         d.wilaya,
        "is_active":      d.is_active,
        "cash_on_hand":   cash,
        "packages_out":   out,
        "delivered_today": delivered_today,
        "created_at":     d.created_at.isoformat() if d.created_at else None,
    }
    if full:
        result["packages"] = [{
            "tracking_id":    p.tracking_id,
            "recipient_name": p.recipient_name,
            "wilaya":         p.wilaya,
            "cod_amount":     p.cod_amount,
            "status":         ev(p.status),
        } for p in d.packages if not p.is_archived]
    return result


@router.get("")
async def list_drivers(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    drivers = db.query(Driver).filter(
        Driver.station_id == current_user.station_id
    ).all()
    return [_fmt(d, db) for d in drivers]


@router.get("/{driver_id}")
async def get_driver(
    driver_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    d = _get_or_404(db, driver_id, current_user.station_id)
    return _fmt(d, db, full=True)


@router.post("")
async def create_driver(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    body = await request.json()
    for f in ["full_name", "phone", "wilaya", "pin"]:
        if not body.get(f):
            raise HTTPException(status_code=400, detail=f"Champ requis: {f}")

    if db.query(User).filter(User.phone == body["phone"]).first():
        raise HTTPException(status_code=400, detail="Numéro déjà utilisé")

    user = User(
        station_id=current_user.station_id,
        full_name=body["full_name"],
        phone=body["phone"],
        hashed_password=_pwd.hash(body["pin"]),
        pin=body["pin"],
        role=RoleEnum.driver,
        is_active=True,
    )
    db.add(user)
    db.flush()

    driver = Driver(
        station_id=current_user.station_id,
        user_id=user.id,
        full_name=body["full_name"],
        phone=body["phone"],
        wilaya=body["wilaya"],
        is_active=True,
    )
    db.add(driver)
    audit(db, action="driver_created", user_id=current_user.id,
          station_id=current_user.station_id, entity_type="driver",
          new_value={"full_name": driver.full_name})
    db.commit()
    db.refresh(driver)
    return _fmt(driver, db)


@router.patch("/{driver_id}/toggle")
async def toggle_driver(
    driver_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    d = _get_or_404(db, driver_id, current_user.station_id)
    d.is_active = not d.is_active
    user = db.query(User).filter(User.id == d.user_id).first()
    if user:
        user.is_active = d.is_active
    audit(db, action="driver_toggled", user_id=current_user.id,
          station_id=current_user.station_id, entity_type="driver",
          entity_id=driver_id, new_value={"is_active": d.is_active})
    db.commit()
    return _fmt(d, db)


@router.get("/{driver_id}/cash")
async def get_driver_cash(
    driver_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    d = _get_or_404(db, driver_id, current_user.station_id)
    logs = db.query(DriverCashLog).filter(
        DriverCashLog.driver_id == driver_id
    ).order_by(DriverCashLog.created_at.desc()).limit(50).all()
    return {
        "balance": driver_cash_balance(db, driver_id),
        "logs": [{
            "action":      l.action,
            "amount":      l.amount,
            "new_balance": l.new_balance,
            "note":        l.note,
            "package_ids": l.package_ids,
            "created_at":  l.created_at.isoformat() if l.created_at else None,
        } for l in logs],
    }


# ── Cash collection (Payment plugin concept — merged here) ────────────────────

@router.post("/{driver_id}/cash-collection")
async def cash_collection(
    driver_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Record cash handed from driver to station.
    Accepts optional package_ids list (from plugin Payment model).
    """
    body        = await request.json()
    amount      = body.get("amount")
    note        = body.get("note", "Versement espèces — station")
    package_ids = body.get("package_ids", [])   # Payment plugin field

    if not amount or float(amount) <= 0:
        raise HTTPException(status_code=400, detail="Montant invalide")

    d = _get_or_404(db, driver_id, current_user.station_id)
    shift = open_shift(db, current_user.station_id)

    log = record_cash_event(
        db,
        driver_id=driver_id,
        action="cash_collected_by_station",
        amount=-float(amount),          # negative = leaves driver's hands
        confirmed_by=current_user.id,
        shift_id=shift.id if shift else None,
    )
    log.note        = note
    log.package_ids = package_ids or None   # store associated packages

    audit(db, action="driver_cash_collected", user_id=current_user.id,
          station_id=current_user.station_id, entity_type="driver",
          entity_id=driver_id,
          new_value={"amount": float(amount), "new_balance": log.new_balance,
                     "package_ids": package_ids})
    db.commit()
    return {
        "success":     True,
        "amount":      float(amount),
        "new_balance": log.new_balance,
        "note":        note,
    }


def _get_or_404(db: Session, driver_id: str, station_id: str) -> Driver:
    d = db.query(Driver).filter(
        Driver.id         == driver_id,
        Driver.station_id == station_id,
    ).first()
    if not d:
        raise HTTPException(status_code=404, detail="Livreur introuvable")
    return d
