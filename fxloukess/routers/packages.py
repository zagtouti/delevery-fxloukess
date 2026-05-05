"""
routers/packages.py  — v3
Full package lifecycle: create, list, get, edit, status machine,
history, public tracking. All helpers from utils.py.
"""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import or_

from config import DELIVERY_FEE_DEFAULT, MAX_DELIVERY_ATTEMPTS
from database import get_db
from models import (
    Alert, AlertSeverityEnum, AuditLog,
    LedgerEntryTypeEnum, Package, PackageStatusEnum, PhysicalLocationEnum,
    Seller, SellerLedgerEntry, Station, User,
)
from routers.auth import get_current_user
from utils import (
    NEEDS_REASON, TRANSITIONS, audit, driver_cash_balance,
    ev, fmt_package, gen_tracking, log_event, open_shift, record_cash_event,
)

logger = logging.getLogger("fxloukess.packages")
router = APIRouter()


# ── List ──────────────────────────────────────────────────────────────────────

@router.get("")
async def list_packages(
    q:         str = Query(""),
    status:    str = Query(""),
    wilaya:    str = Query(""),
    driver_id: str = Query(""),
    seller_id: str = Query(""),
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
    if seller_id:
        qry = qry.filter(Package.seller_id == seller_id)

    total = qry.count()
    items = qry.order_by(Package.created_at.desc()).offset(offset).limit(limit).all()
    return {"total": total, "items": [fmt_package(p) for p in items]}


# ── Public tracking (no auth) ─────────────────────────────────────────────────

@router.get("/track/{tracking_id}")
async def public_track(tracking_id: str, db: Session = Depends(get_db)):
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
        "status":         ev(p.status),
        "attempts":       p.attempts,
        "created_at":     p.created_at.isoformat() if p.created_at else None,
        "delivered_at":   p.delivered_at.isoformat() if p.delivered_at else None,
        "history": [{
            "new_status": h.new_status,
            "reason":     h.reason,
            "created_at": h.created_at.isoformat() if h.created_at else None,
        } for h in p.history],
    }


# ── Get one ───────────────────────────────────────────────────────────────────

@router.get("/{package_id}")
async def get_package(
    package_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    p = _get_or_404(db, package_id, current_user.station_id)
    return fmt_package(p, full=True)


# ── Create ────────────────────────────────────────────────────────────────────

@router.post("")
async def create_package(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    body = await request.json()

    required = ["recipient_name", "recipient_phone", "wilaya",
                "commune", "address", "description", "cod_amount"]
    missing = [f for f in required if not body.get(f)]
    if missing:
        raise HTTPException(status_code=400,
                            detail=f"Champs requis: {', '.join(missing)}")

    source = body.get("source", "seller")
    if source == "seller" and not body.get("seller_id"):
        raise HTTPException(status_code=400,
                            detail="seller_id requis pour source=seller")

    station = db.query(Station).filter(
        Station.id == current_user.station_id
    ).first()
    shift = open_shift(db, current_user.station_id)

    dup = db.query(Package).filter(
        Package.recipient_phone == body["recipient_phone"],
        Package.wilaya          == body["wilaya"],
        Package.cod_amount      == float(body["cod_amount"]),
        Package.status.in_(["created", "assigned", "out_for_delivery"]),
    ).first()

    declared      = body.get("declared_value")
    insurance_fee = round(float(declared) * 0.02, 2) if declared else None

    pkg = Package(
        tracking_id       = gen_tracking(db, station.code),
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
        is_fragile        = bool(body.get("is_fragile", False)),
        do_not_bend       = bool(body.get("do_not_bend", False)),
        notes             = body.get("notes"),
        status            = PackageStatusEnum.created,
        physical_location = PhysicalLocationEnum.receiving,
    )
    db.add(pkg)
    db.flush()

    log_event(db, package_id=pkg.id, user_id=current_user.id,
              old_status=None, new_status="created",
              note="Colis créé", shift_id=shift.id if shift else None)
    audit(db, action="package_created", user_id=current_user.id,
          station_id=current_user.station_id, entity_type="package",
          entity_id=pkg.id, new_value={"tracking_id": pkg.tracking_id})
    db.commit()
    db.refresh(pkg)

    result = fmt_package(pkg)
    if dup:
        result["warning"] = f"Colis similaire existant: {dup.tracking_id}"
    return result


# ── Edit (NEW v3) ─────────────────────────────────────────────────────────────

@router.patch("/{package_id}")
async def edit_package(
    package_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Edit mutable fields. Delivered/returned/lost packages are locked."""
    pkg = _get_or_404(db, package_id, current_user.station_id)
    current_status = ev(pkg.status)

    if current_status in ("delivered", "returned", "lost"):
        raise HTTPException(
            status_code=400,
            detail=f"Colis {current_status} — modification impossible",
        )

    body = await request.json()
    old_snapshot = {f: getattr(pkg, f) for f in [
        "recipient_name", "recipient_phone", "wilaya", "commune",
        "address", "cod_amount", "description", "notes",
        "is_fragile", "do_not_bend",
    ]}

    EDITABLE = [
        "recipient_name", "recipient_phone", "recipient_phone2",
        "wilaya", "commune", "address", "description",
        "cod_amount", "weight", "notes", "is_fragile", "do_not_bend",
    ]
    for field in EDITABLE:
        if field in body and body[field] is not None:
            if field == "cod_amount":
                if pkg.cod_locked:
                    raise HTTPException(status_code=400,
                                        detail="COD verrouillé après livraison")
                setattr(pkg, field, float(body[field]))
            elif field in ("is_fragile", "do_not_bend"):
                setattr(pkg, field, bool(body[field]))
            else:
                setattr(pkg, field, body[field])

    shift = open_shift(db, current_user.station_id)
    log_event(db, package_id=pkg.id, user_id=current_user.id,
              old_status=current_status, new_status=current_status,
              note="Colis modifié", shift_id=shift.id if shift else None)
    audit(db, action="package_edited", user_id=current_user.id,
          station_id=current_user.station_id, entity_type="package",
          entity_id=pkg.id, old_value=old_snapshot,
          new_value={k: body[k] for k in EDITABLE if k in body})
    db.commit()
    db.refresh(pkg)
    return fmt_package(pkg)


# ── Status (state machine) ────────────────────────────────────────────────────

@router.patch("/{package_id}/status")
async def update_status(
    package_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    body       = await request.json()
    new_status = body.get("status", "").strip().lower()
    reason     = body.get("reason")
    note       = body.get("note")

    pkg     = _get_or_404(db, package_id, current_user.station_id)
    current = ev(pkg.status)

    if current == "sync_conflict":
        raise HTTPException(status_code=400,
                            detail="Conflit de sync — résolvez d'abord")

    allowed = TRANSITIONS.get(current, [])
    if new_status not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Transition interdite: {current} → {new_status}. "
                   f"Autorisées: {allowed or 'aucune'}",
        )
    if new_status in NEEDS_REASON and not reason:
        raise HTTPException(status_code=400,
                            detail="Une raison est requise pour ce statut")

    shift      = open_shift(db, current_user.station_id)
    old_status = current
    pkg.status = new_status
    now        = datetime.now(timezone.utc)

    if new_status == "assigned":
        pkg.physical_location = PhysicalLocationEnum.dispatch_bag
        if body.get("driver_id"):
            pkg.driver_id = body["driver_id"]

    elif new_status == "out_for_delivery":
        pkg.attempts         += 1
        pkg.physical_location = PhysicalLocationEnum.with_driver
        if not pkg.first_attempt_at:
            pkg.first_attempt_at = now
        if body.get("driver_id"):
            pkg.driver_id = body["driver_id"]
        if pkg.attempts >= MAX_DELIVERY_ATTEMPTS:
            _raise_max_attempts_alert(db, pkg, current_user.station_id)

    elif new_status == "delivered":
        pkg.delivered_at      = now
        pkg.cod_locked        = True
        pkg.physical_location = PhysicalLocationEnum.with_driver
        _post_deliver(db, pkg, current_user, shift)

    elif new_status in ("failed", "returned"):
        pkg.physical_location = PhysicalLocationEnum.returns_area

    elif new_status == "held_at_station":
        pkg.physical_location = PhysicalLocationEnum.shelf

    log_event(db, package_id=pkg.id, user_id=current_user.id,
              old_status=old_status, new_status=new_status,
              reason=reason, note=note,
              shift_id=shift.id if shift else None)
    audit(db, action="status_changed", user_id=current_user.id,
          station_id=current_user.station_id, entity_type="package",
          entity_id=pkg.id,
          old_value={"status": old_status},
          new_value={"status": new_status, "reason": reason})

    db.commit()
    db.refresh(pkg)
    return fmt_package(pkg, full=True)


# ── History ───────────────────────────────────────────────────────────────────

@router.get("/{package_id}/history")
async def get_history(
    package_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    pkg = _get_or_404(db, package_id, current_user.station_id)
    return [{
        "old_status": h.old_status,
        "new_status": h.new_status,
        "reason":     h.reason,
        "note":       h.note,
        "user_id":    h.user_id,
        "created_at": h.created_at.isoformat() if h.created_at else None,
    } for h in pkg.history]


# ── Private helpers ───────────────────────────────────────────────────────────

def _get_or_404(db: Session, package_id: str, station_id: str) -> Package:
    p = db.query(Package).filter(
        Package.id         == package_id,
        Package.station_id == station_id,
    ).first()
    if not p:
        raise HTTPException(status_code=404, detail="Colis introuvable")
    return p


def _post_deliver(db: Session, pkg: Package, user: User, shift) -> None:
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
        record_cash_event(
            db,
            driver_id=pkg.driver_id,
            action="delivery_collected",
            amount=pkg.cod_amount,
            package_id=pkg.id,
            shift_id=shift.id if shift else None,
        )


def _raise_max_attempts_alert(db: Session, pkg: Package, station_id: str) -> None:
    existing = db.query(Alert).filter(
        Alert.reference_id == pkg.id,
        Alert.alert_type   == "max_attempts",
        Alert.is_resolved  == False,
    ).first()
    if not existing:
        db.add(Alert(
            station_id   = station_id,
            severity     = AlertSeverityEnum.high,
            alert_type   = "max_attempts",
            title        = f"Tentatives max atteintes — {pkg.tracking_id}",
            description  = (f"{pkg.recipient_name} — {pkg.wilaya} — "
                            f"{pkg.attempts} tentatives"),
            reference_id = pkg.id,
        ))
