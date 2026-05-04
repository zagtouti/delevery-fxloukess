"""routers/returns.py — Returns zone, reschedule, seller payouts."""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from config import RETURN_FEE_DEFAULT
from database import get_db
from models import (
    AuditLog, LedgerEntryTypeEnum, Package, PackageHistory,
    PackageStatusEnum, PhysicalLocationEnum, Seller, SellerLedgerEntry,
    Shift, User,
)
from routers.auth import get_current_user

logger = logging.getLogger("fxloukess.returns")
router = APIRouter()


def _open_shift(db: Session, station_id: str) -> Shift | None:
    return db.query(Shift).filter(
        Shift.station_id == station_id, Shift.is_closed == False
    ).first()


def _fmt(p: Package) -> dict:
    return {
        "id":              p.id,
        "tracking_id":     p.tracking_id,
        "recipient_name":  p.recipient_name,
        "wilaya":          p.wilaya,
        "cod_amount":      p.cod_amount,
        "status":          p.status.value if hasattr(p.status, "value") else p.status,
        "physical_location": p.physical_location.value if hasattr(p.physical_location, "value") else p.physical_location,
        "seller_id":       p.seller_id,
        "driver_id":       p.driver_id,
        "attempts":        p.attempts,
        "created_at":      p.created_at.isoformat() if p.created_at else None,
    }


# ── Returns list ──────────────────────────────────────────────────────────────

@router.get("")
async def list_returns(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    pkgs = db.query(Package).filter(
        Package.station_id == current_user.station_id,
        Package.physical_location == PhysicalLocationEnum.returns_area,
        Package.is_archived == False,
    ).order_by(Package.created_at.desc()).all()
    return [_fmt(p) for p in pkgs]


# ── Confirm return from driver ────────────────────────────────────────────────

@router.post("/{package_id}/receive")
async def receive_return(
    package_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    body = await request.json()
    pkg  = db.query(Package).filter(
        Package.id == package_id,
        Package.station_id == current_user.station_id,
    ).first()
    if not pkg:
        raise HTTPException(status_code=404, detail="Colis introuvable")

    shift  = _open_shift(db, current_user.station_id)
    old    = pkg.status.value if hasattr(pkg.status, "value") else pkg.status
    pkg.status            = PackageStatusEnum.returned
    pkg.physical_location = PhysicalLocationEnum.returns_area

    db.add(PackageHistory(
        package_id=pkg.id, user_id=current_user.id,
        shift_id=shift.id if shift else None,
        old_status=old, new_status="returned",
        reason=body.get("reason"), note=body.get("note"),
    ))

    # Return fee
    if pkg.seller_id:
        db.add(SellerLedgerEntry(
            seller_id=pkg.seller_id, package_id=pkg.id,
            entry_type=LedgerEntryTypeEnum.return_fee_debit,
            amount=-RETURN_FEE_DEFAULT,
            note=f"Frais de retour — {pkg.tracking_id}",
            created_by=current_user.id,
            shift_id=shift.id if shift else None,
        ))

    db.add(AuditLog(
        user_id=current_user.id, station_id=current_user.station_id,
        action="return_received", entity_type="package", entity_id=pkg.id,
        new_value={"reason": body.get("reason")},
    ))
    db.commit()
    return _fmt(pkg)


# ── Reschedule ────────────────────────────────────────────────────────────────

@router.post("/{package_id}/reschedule")
async def reschedule(
    package_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    body = await request.json()
    pkg  = db.query(Package).filter(
        Package.id == package_id,
        Package.station_id == current_user.station_id,
    ).first()
    if not pkg:
        raise HTTPException(status_code=404, detail="Colis introuvable")

    shift  = _open_shift(db, current_user.station_id)
    old    = pkg.status.value if hasattr(pkg.status, "value") else pkg.status
    pkg.status            = PackageStatusEnum.rescheduled
    pkg.physical_location = PhysicalLocationEnum.shelf

    db.add(PackageHistory(
        package_id=pkg.id, user_id=current_user.id,
        shift_id=shift.id if shift else None,
        old_status=old, new_status="rescheduled",
        note=body.get("note"),
    ))
    db.commit()
    return _fmt(pkg)


# ── Seller payout ─────────────────────────────────────────────────────────────

@router.post("/payout/{seller_id}")
async def payout_seller(
    seller_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    body   = await request.json()
    amount = body.get("amount")
    note   = body.get("note", "Versement COD")

    if not amount or float(amount) <= 0:
        raise HTTPException(status_code=400, detail="Montant invalide")

    seller = db.query(Seller).filter(
        Seller.id == seller_id,
        Seller.station_id == current_user.station_id,
    ).first()
    if not seller:
        raise HTTPException(status_code=404, detail="Expéditeur introuvable")

    shift = _open_shift(db, current_user.station_id)
    db.add(SellerLedgerEntry(
        seller_id=seller_id,
        entry_type=LedgerEntryTypeEnum.payout,
        amount=-float(amount),
        note=note,
        created_by=current_user.id,
        shift_id=shift.id if shift else None,
    ))
    db.add(AuditLog(
        user_id=current_user.id, station_id=current_user.station_id,
        action="seller_payout", entity_type="seller", entity_id=seller_id,
        new_value={"amount": float(amount), "note": note},
    ))
    db.commit()
    return {"success": True, "amount": float(amount)}
