"""routers/returns.py — v3. Uses utils."""
import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import func

from config import RETURN_FEE_DEFAULT
from database import get_db
from models import (
    LedgerEntryTypeEnum, Package, PackageStatusEnum, PhysicalLocationEnum,
    Seller, SellerLedgerEntry, User,
)
from routers.auth import get_current_user
from utils import audit, ev, fmt_package, log_event, open_shift

logger = logging.getLogger("fxloukess.returns")
router = APIRouter()


@router.get("")
async def list_returns(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    pkgs = db.query(Package).filter(
        Package.station_id        == current_user.station_id,
        Package.physical_location == PhysicalLocationEnum.returns_area,
        Package.is_archived       == False,
    ).order_by(Package.created_at.desc()).all()
    return [fmt_package(p) for p in pkgs]


@router.post("/{package_id}/receive")
async def receive_return(
    package_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    body  = await request.json()
    pkg   = _get_or_404(db, package_id, current_user.station_id)
    shift = open_shift(db, current_user.station_id)
    old   = ev(pkg.status)

    pkg.status            = PackageStatusEnum.returned
    pkg.physical_location = PhysicalLocationEnum.returns_area

    log_event(db, package_id=pkg.id, user_id=current_user.id,
              shift_id=shift.id if shift else None,
              old_status=old, new_status="returned",
              reason=body.get("reason"), note=body.get("note"))

    if pkg.seller_id:
        db.add(SellerLedgerEntry(
            seller_id=pkg.seller_id, package_id=pkg.id,
            entry_type=LedgerEntryTypeEnum.return_fee_debit,
            amount=-RETURN_FEE_DEFAULT,
            note=f"Frais de retour — {pkg.tracking_id}",
            created_by=current_user.id,
            shift_id=shift.id if shift else None,
        ))

    audit(db, action="return_received", user_id=current_user.id,
          station_id=current_user.station_id,
          entity_type="package", entity_id=pkg.id,
          new_value={"reason": body.get("reason")})
    db.commit()
    return fmt_package(pkg)


@router.post("/{package_id}/reschedule")
async def reschedule(
    package_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    body  = await request.json()
    pkg   = _get_or_404(db, package_id, current_user.station_id)
    shift = open_shift(db, current_user.station_id)
    old   = ev(pkg.status)

    pkg.status            = PackageStatusEnum.rescheduled
    pkg.physical_location = PhysicalLocationEnum.shelf

    log_event(db, package_id=pkg.id, user_id=current_user.id,
              shift_id=shift.id if shift else None,
              old_status=old, new_status="rescheduled",
              note=body.get("note"))
    db.commit()
    return fmt_package(pkg)


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
        Seller.id == seller_id, Seller.station_id == current_user.station_id
    ).first()
    if not seller:
        raise HTTPException(status_code=404, detail="Expéditeur introuvable")

    shift = open_shift(db, current_user.station_id)
    db.add(SellerLedgerEntry(
        seller_id=seller_id,
        entry_type=LedgerEntryTypeEnum.payout,
        amount=-float(amount),
        note=note,
        created_by=current_user.id,
        shift_id=shift.id if shift else None,
    ))
    audit(db, action="seller_payout", user_id=current_user.id,
          station_id=current_user.station_id,
          entity_type="seller", entity_id=seller_id,
          new_value={"amount": float(amount)})
    db.commit()
    return {"success": True, "amount": float(amount)}


def _get_or_404(db, package_id, station_id):
    p = db.query(Package).filter(
        Package.id == package_id, Package.station_id == station_id
    ).first()
    if not p:
        raise HTTPException(status_code=404, detail="Colis introuvable")
    return p
