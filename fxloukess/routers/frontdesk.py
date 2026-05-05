"""routers/frontdesk.py — v3. Uses utils. Adds package search + cash-collection UI endpoint."""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import or_

from database import get_db
from models import (
    AuditLog, Driver, Package, PackageStatusEnum, PhysicalLocationEnum,
    PettyCashEntry, Shift, ShiftTypeEnum, User,
)
from routers.auth import get_current_user
from utils import audit, driver_cash_balance, ev, fmt_package, log_event, open_shift, record_cash_event

logger = logging.getLogger("fxloukess.frontdesk")
router = APIRouter()


def _fmt_shift(s: Shift) -> dict:
    return {
        "id":         s.id,
        "shift_type": ev(s.shift_type),
        "is_closed":  s.is_closed,
        "opened_at":  s.opened_at.isoformat() if s.opened_at else None,
        "closed_at":  s.closed_at.isoformat() if s.closed_at else None,
        "notes":      s.notes,
    }


# ── Shift ─────────────────────────────────────────────────────────────────────

@router.get("/shift")
async def get_shift(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    shift = open_shift(db, current_user.station_id)
    return {"shift": _fmt_shift(shift) if shift else None}


@router.post("/shift/open")
async def open_shift_ep(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if open_shift(db, current_user.station_id):
        raise HTTPException(status_code=400, detail="Un shift est déjà ouvert")
    body       = await request.json()
    shift_type = body.get("shift_type", "morning")
    if shift_type not in ShiftTypeEnum._value2member_map_:
        raise HTTPException(status_code=400, detail="Type de shift invalide")
    shift = Shift(station_id=current_user.station_id, shift_type=shift_type,
                  opened_by=current_user.id, is_closed=False)
    db.add(shift)
    db.flush()
    audit(db, action="shift_opened", user_id=current_user.id,
          station_id=current_user.station_id, shift_id=shift.id,
          entity_type="shift", entity_id=shift.id)
    db.commit()
    db.refresh(shift)
    return {"shift": _fmt_shift(shift)}


@router.post("/shift/close")
async def close_shift(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    shift = open_shift(db, current_user.station_id)
    if not shift:
        raise HTTPException(status_code=400, detail="Aucun shift ouvert")
    body            = await request.json()
    shift.is_closed = True
    shift.closed_by = current_user.id
    shift.closed_at = datetime.now(timezone.utc)
    shift.notes     = body.get("notes")
    audit(db, action="shift_closed", user_id=current_user.id,
          station_id=current_user.station_id, shift_id=shift.id,
          entity_type="shift", entity_id=shift.id)
    db.commit()
    return {"success": True, "shift": _fmt_shift(shift)}


@router.get("/shift/summary")
async def shift_summary(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    shift = open_shift(db, current_user.station_id)
    if not shift:
        return {"shift": None, "packages": 0, "delivered": 0, "cod": 0}
    pkgs      = db.query(Package).filter(Package.station_id == current_user.station_id, Package.shift_id == shift.id)
    total     = pkgs.count()
    delivered = pkgs.filter(Package.status == PackageStatusEnum.delivered).count()
    cod       = sum(p.cod_amount for p in pkgs.filter(Package.status == PackageStatusEnum.delivered).all())
    return {"shift": _fmt_shift(shift), "packages": total, "delivered": delivered, "cod": cod}


# ── Receiving ─────────────────────────────────────────────────────────────────

@router.get("/receive/pending")
async def receive_pending(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    pkgs = db.query(Package).filter(
        Package.station_id        == current_user.station_id,
        Package.physical_location == PhysicalLocationEnum.receiving,
        Package.is_archived       == False,
    ).order_by(Package.created_at.desc()).all()
    return [fmt_package(p) for p in pkgs]


@router.patch("/receive/{package_id}/shelve")
async def shelve_package(
    package_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    pkg = db.query(Package).filter(
        Package.id == package_id, Package.station_id == current_user.station_id
    ).first()
    if not pkg:
        raise HTTPException(status_code=404, detail="Colis introuvable")
    pkg.physical_location = PhysicalLocationEnum.shelf
    shift = open_shift(db, current_user.station_id)
    audit(db, action="package_shelved", user_id=current_user.id,
          station_id=current_user.station_id, shift_id=shift.id if shift else None,
          entity_type="package", entity_id=pkg.id)
    db.commit()
    return {"success": True, "id": pkg.id}


# ── Package search (NEW v3) ───────────────────────────────────────────────────

@router.get("/search")
async def search_package(
    q: str = Query(..., min_length=3),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Scan or type tracking ID / phone to find any package."""
    pkgs = db.query(Package).filter(
        Package.station_id == current_user.station_id,
        or_(
            Package.tracking_id.ilike(f"%{q}%"),
            Package.recipient_phone.ilike(f"%{q}%"),
            Package.recipient_name.ilike(f"%{q}%"),
        ),
    ).limit(10).all()
    return [fmt_package(p) for p in pkgs]


# ── Cash collection from driver (NEW v3 UI endpoint) ─────────────────────────

@router.post("/collect-cash/{driver_id}")
async def collect_cash(
    driver_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Frontdesk collects cash from a driver at end of shift."""
    body        = await request.json()
    amount      = body.get("amount")
    note        = body.get("note", "Versement fin de shift")
    package_ids = body.get("package_ids", [])

    if not amount or float(amount) <= 0:
        raise HTTPException(status_code=400, detail="Montant invalide")

    driver = db.query(Driver).filter(
        Driver.id == driver_id, Driver.station_id == current_user.station_id
    ).first()
    if not driver:
        raise HTTPException(status_code=404, detail="Livreur introuvable")

    shift = open_shift(db, current_user.station_id)
    log   = record_cash_event(
        db,
        driver_id=driver_id,
        action="cash_collected_by_station",
        amount=-float(amount),
        confirmed_by=current_user.id,
        shift_id=shift.id if shift else None,
        package_ids=package_ids or None,
    )
    log.note = note
    audit(db, action="driver_cash_collected", user_id=current_user.id,
          station_id=current_user.station_id, shift_id=shift.id if shift else None,
          entity_type="driver", entity_id=driver_id,
          new_value={"amount": float(amount), "new_balance": log.new_balance})
    db.commit()
    return {
        "success":     True,
        "driver":      driver.full_name,
        "amount":      float(amount),
        "new_balance": log.new_balance,
    }


# ── Petty cash ────────────────────────────────────────────────────────────────

@router.get("/petty-cash")
async def get_petty_cash(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    shift   = open_shift(db, current_user.station_id)
    filters = [PettyCashEntry.station_id == current_user.station_id]
    if shift:
        filters.append(PettyCashEntry.shift_id == shift.id)
    entries = db.query(PettyCashEntry).filter(*filters).order_by(PettyCashEntry.created_at.desc()).all()
    return [{"id": e.id, "category": e.category, "amount": e.amount,
             "note": e.note, "created_at": e.created_at.isoformat() if e.created_at else None}
            for e in entries]


@router.post("/petty-cash")
async def add_petty_cash(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    body = await request.json()
    for f in ["category", "amount", "note"]:
        if body.get(f) is None or body.get(f) == "":
            raise HTTPException(status_code=400, detail=f"Champ requis: {f}")
    shift = open_shift(db, current_user.station_id)
    entry = PettyCashEntry(
        station_id=current_user.station_id,
        shift_id=shift.id if shift else None,
        category=body["category"],
        amount=float(body["amount"]),
        note=body["note"],
        created_by=current_user.id,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return {"id": entry.id, "category": entry.category, "amount": entry.amount,
            "note": entry.note, "created_at": entry.created_at.isoformat() if entry.created_at else None}
