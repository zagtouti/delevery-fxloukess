"""
routers/packages.py
Full package lifecycle: create, list, get, update status, history, public tracking.
"""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import or_

from config import DELIVERY_FEE_DEFAULT, RETURN_FEE_DEFAULT
from database import get_db
from models import (
    AuditLog, Driver, DriverCashLog, Package, PackageHistory, PackageStatusEnum,
    PhysicalLocationEnum, LedgerEntryTypeEnum, Seller, SellerLedgerEntry,
    Shift, Station, User,
)
from routers.auth import get_current_user

logger = logging.getLogger("fxloukess.packages")
router = APIRouter()

# Allowed status transitions
_TRANSITIONS: dict[str, list[str]] = {
    "created":             ["assigned", "held_at_station", "lost"],
    "assigned":            ["out_for_delivery", "held_at_station", "created"],
    "out_for_delivery":    ["delivered", "failed", "rescheduled", "address_changed",
                            "waiting_for_client", "partially_delivered", "out_for_delivery"],
    "failed":              ["out_for_delivery", "returned", "held_at_station",
                            "rescheduled", "lost"],
    "rescheduled":         ["out_for_delivery", "returned", "lost"],
    "waiting_for_client":  ["out_for_delivery", "returned", "lost"],
    "address_changed":     ["out_for_delivery", "returned"],
    "held_at_station":     ["assigned", "returned", "lost"],
    "partially_delivered": ["out_for_delivery", "delivered", "returned"],
    "delivered":           [],
    "returned":            [],
    "lost":                [],
    "sync_conflict":       [],
}
_NEEDS_REASON = {"failed", "returned", "rescheduled", "lost"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _active_shift(db: Session, station_id: str) -> Shift | None:
    return db.query(Shift).filter(
        Shift.station_id == station_id,
        Shift.is_closed == False,
    ).first()


def _cash_on_hand(db: Session, driver_id: str) -> float:
    log = db.query(DriverCashLog).filter(
        DriverCashLog.driver_id == driver_id
    ).order_by(DriverCashLog.created_at.desc()).first()
    return log.new_balance if log else 0.0


def _fmt(p: Package, full: bool = False) -> dict:
    d = {
        "id":               p.id,
        "tracking_id":      p.tracking_id,
        "recipient_name":   p.recipient_name,
        "recipient_phone":  p.recipient_phone,
        "recipient_phone2": p.recipient_phone2,
        "wilaya":           p.wilaya,
        "commune":          p.commune,
        "address":          p.address,
        "description":      p.description,
        "weight":           p.weight,
        "cod_amount":       p.cod_amount,
        "declared_value":   p.declared_value,
        "insurance_fee":    p.insurance_fee,
        "is_fragile":       p.is_fragile,
        "do_not_bend":      p.do_not_bend,
        "notes":            p.notes,
        "status":           p.status.value if hasattr(p.status, "value") else p.status,
        "physical_location": p.physical_location.value if hasattr(p.physical_location, "value") else p.physical_location,
        "attempts":         p.attempts,
        "cod_locked":       p.cod_locked,
        "seller_id":        p.seller_id,
        "driver_id":        p.driver_id,
        "source":           p.source,
        "walk_in_name":     p.walk_in_name,
        "created_at":       p.created_at.isoformat() if p.created_at else None,
        "delivered_at":     p.delivered_at.isoformat() if p.delivered_at else None,
    }
    if full and p.history:
        d["history"] = [{
            "old_status": h.old_status,
            "new_status": h.new_status,
            "reason":     h.reason,
            "note":       h.note,
            "created_at": h.created_at.isoformat() if h.created_at else None,
        } for h in p.history]
    return d


def _gen_tracking(db: Session, station_code: str) -> str:
    today  = datetime.now().strftime("%Y%m%d")
    prefix = f"{station_code}{today}"
    count  = db.query(Package).filter(Package.tracking_id.like(f"{prefix}%")).count()
    return f"{prefix}{str(count + 1).zfill(4)}"


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("")
async def list_packages(
    q:         str = Query(""),
    status:    str = Query(""),
    wilaya:    str = Query(""),
    driver_id: str = Query(""),
    limit:     int = Query(50, le=200),
    offset:    int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    qry = db.query(Package).filter(
        Package.station_id == current_user.station_id,
        Package.is_archived == False,
    )
    if q:
        qry = qry.filter(or_(
            Package.tracking_id.ilike(f"%{q}%"),
            Package.recipient_name.ilike(f"%{q}%"),
            Package.recipient_phone.ilike(f"%{q}%"),
        ))
    if status:
        qry = qry.filter(Package.status == status)
    if wilaya:
        qry = qry.filter(Package.wilaya == wilaya)
    if driver_id:
        qry = qry.filter(Package.driver_id == driver_id)

    total = qry.count()
    items = qry.order_by(Package.created_at.desc()).offset(offset).limit(limit).all()
    return {"total": total, "items": [_fmt(p) for p in items]}


@router.get("/track/{tracking_id}")
async def public_track(tracking_id: str, db: Session = Depends(get_db)):
    """Public — no auth. Returns limited info for recipient."""
    p = db.query(Package).filter(
        Package.tracking_id == tracking_id.upper().strip()
    ).first()
    if not p:
        raise HTTPException(status_code=404, detail="Colis introuvable")
    return {
        "tracking_id":    p.tracking_id,
        "recipient_name": p.recipient_name,
        "wilaya":         p.wilaya,
        "commune":        p.commune,
        "status":         p.status.value if hasattr(p.status, "value") else p.status,
        "attempts":       p.attempts,
        "created_at":     p.created_at.isoformat() if p.created_at else None,
        "delivered_at":   p.delivered_at.isoformat() if p.delivered_at else None,
        "history": [{
            "new_status": h.new_status,
            "reason":     h.reason,
            "created_at": h.created_at.isoformat() if h.created_at else None,
        } for h in p.history],
    }


@router.get("/{package_id}")
async def get_package(
    package_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    p = db.query(Package).filter(
        Package.id == package_id,
        Package.station_id == current_user.station_id,
    ).first()
    if not p:
        raise HTTPException(status_code=404, detail="Colis introuvable")
    return _fmt(p, full=True)


@router.post("")
async def create_package(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    body = await request.json()

    required = ["recipient_name", "recipient_phone", "wilaya", "commune",
                "address", "description", "cod_amount"]
    missing = [f for f in required if not body.get(f)]
    if missing:
        raise HTTPException(status_code=400, detail=f"Champs requis: {', '.join(missing)}")

    source = body.get("source", "seller")
    if source == "seller" and not body.get("seller_id"):
        raise HTTPException(status_code=400, detail="seller_id requis pour source=seller")

    station = db.query(Station).filter(Station.id == current_user.station_id).first()
    shift   = _active_shift(db, current_user.station_id)

    # Duplicate detection
    dup = db.query(Package).filter(
        Package.recipient_phone == body["recipient_phone"],
        Package.wilaya == body["wilaya"],
        Package.cod_amount == float(body["cod_amount"]),
        Package.status.in_(["created", "assigned", "out_for_delivery"]),
    ).first()
    warning = f"Colis similaire: {dup.tracking_id}" if dup else None

    # Insurance
    declared = body.get("declared_value")
    insurance_fee = round(float(declared) * 0.02, 2) if declared else None

    pkg = Package(
        tracking_id       = _gen_tracking(db, station.code),
        station_id        = current_user.station_id,
        seller_id         = body.get("seller_id"),
        shift_id          = shift.id if shift else None,
        source            = source,
        walk_in_name      = body.get("walk_in_name"),
        walk_in_phone     = body.get("walk_in_phone"),
        recipient_name    = body["recipient_name"],
        recipient_phone   = body["recipient_phone"],
        recipient_phone2  = body.get("recipient_phone2"),
        wilaya            = body["wilaya"],
        commune           = body["commune"],
        address           = body["address"],
        description       = body["description"],
        weight            = body.get("weight"),
        cod_amount        = float(body["cod_amount"]),
        declared_value    = float(declared) if declared else None,
        insurance_fee     = insurance_fee,
        is_fragile        = body.get("is_fragile", False),
        do_not_bend       = body.get("do_not_bend", False),
        notes             = body.get("notes"),
        status            = PackageStatusEnum.created,
        physical_location = PhysicalLocationEnum.receiving,
    )
    db.add(pkg)
    db.flush()

    db.add(PackageHistory(
        package_id=pkg.id, user_id=current_user.id,
        shift_id=shift.id if shift else None,
        old_status=None, new_status="created", note="Colis créé",
    ))
    db.add(AuditLog(
        user_id=current_user.id, station_id=current_user.station_id,
        action="package_created", entity_type="package", entity_id=pkg.id,
        new_value={"tracking_id": pkg.tracking_id},
    ))
    db.commit()
    db.refresh(pkg)

    result = _fmt(pkg)
    if warning:
        result["warning"] = warning
    return result


@router.patch("/{package_id}/status")
async def update_status(
    package_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    body       = await request.json()
    new_status = body.get("status", "").strip()
    reason     = body.get("reason")
    note       = body.get("note")

    pkg = db.query(Package).filter(
        Package.id == package_id,
        Package.station_id == current_user.station_id,
    ).first()
    if not pkg:
        raise HTTPException(status_code=404, detail="Colis introuvable")

    current = pkg.status.value if hasattr(pkg.status, "value") else pkg.status
    if current == "sync_conflict":
        raise HTTPException(status_code=400, detail="Conflit de sync — résolvez d'abord")

    allowed = _TRANSITIONS.get(current, [])
    if new_status not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Transition interdite: {current} → {new_status}"
        )
    if new_status in _NEEDS_REASON and not reason:
        raise HTTPException(status_code=400, detail="Une raison est requise pour ce statut")

    shift = _active_shift(db, current_user.station_id)
    old_status = current
    pkg.status = new_status

    # Side-effects per new status
    if new_status == "out_for_delivery":
        pkg.attempts += 1
        if not pkg.first_attempt_at:
            pkg.first_attempt_at = datetime.now(timezone.utc)
        pkg.physical_location = PhysicalLocationEnum.with_driver
        if body.get("driver_id"):
            pkg.driver_id = body["driver_id"]

    elif new_status == "assigned":
        pkg.physical_location = PhysicalLocationEnum.dispatch_bag
        if body.get("driver_id"):
            pkg.driver_id = body["driver_id"]

    elif new_status == "delivered":
        pkg.delivered_at      = datetime.now(timezone.utc)
        pkg.cod_locked        = True
        pkg.physical_location = PhysicalLocationEnum.with_driver
        _post_deliver(db, pkg, current_user, shift)

    elif new_status in ("failed", "returned"):
        pkg.physical_location = PhysicalLocationEnum.returns_area

    db.add(PackageHistory(
        package_id=pkg.id, user_id=current_user.id,
        shift_id=shift.id if shift else None,
        old_status=old_status, new_status=new_status,
        reason=reason, note=note,
    ))
    db.add(AuditLog(
        user_id=current_user.id, station_id=current_user.station_id,
        action="status_changed", entity_type="package", entity_id=pkg.id,
        old_value={"status": old_status},
        new_value={"status": new_status, "reason": reason},
    ))
    db.commit()
    db.refresh(pkg)
    return _fmt(pkg)


def _post_deliver(db: Session, pkg: Package, user: User, shift: Shift | None) -> None:
    """Create ledger entries and driver cash log when a package is delivered."""
    if pkg.seller_id:
        db.add(SellerLedgerEntry(
            seller_id=pkg.seller_id, package_id=pkg.id,
            entry_type=LedgerEntryTypeEnum.cod_credit,
            amount=pkg.cod_amount,
            note=f"COD collecté – {pkg.tracking_id}",
            created_by=user.id,
            shift_id=shift.id if shift else None,
        ))
        db.add(SellerLedgerEntry(
            seller_id=pkg.seller_id, package_id=pkg.id,
            entry_type=LedgerEntryTypeEnum.delivery_fee_debit,
            amount=-DELIVERY_FEE_DEFAULT,
            note=f"Frais livraison – {pkg.tracking_id}",
            created_by=user.id,
            shift_id=shift.id if shift else None,
        ))

    if pkg.driver_id:
        old_bal = _cash_on_hand(db, pkg.driver_id)
        db.add(DriverCashLog(
            driver_id=pkg.driver_id, package_id=pkg.id,
            action="delivery_collected",
            amount=pkg.cod_amount,
            old_balance=old_bal,
            new_balance=old_bal + pkg.cod_amount,
            shift_id=shift.id if shift else None,
        ))


@router.get("/{package_id}/history")
async def get_history(
    package_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    pkg = db.query(Package).filter(
        Package.id == package_id,
        Package.station_id == current_user.station_id,
    ).first()
    if not pkg:
        raise HTTPException(status_code=404, detail="Colis introuvable")
    return [{
        "old_status": h.old_status,
        "new_status": h.new_status,
        "reason":     h.reason,
        "note":       h.note,
        "created_at": h.created_at.isoformat() if h.created_at else None,
    } for h in pkg.history]
