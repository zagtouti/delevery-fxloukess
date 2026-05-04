"""routers/sellers.py — Seller CRUD + ledger."""
import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import get_db
from models import AuditLog, Package, PackageStatusEnum, Seller, SellerLedgerEntry, User
from routers.auth import get_current_user

logger = logging.getLogger("fxloukess.sellers")
router = APIRouter()


def _balance(db: Session, seller_id: str) -> float:
    row = db.query(func.sum(SellerLedgerEntry.amount)).filter(
        SellerLedgerEntry.seller_id == seller_id
    ).scalar()
    return round(float(row or 0), 2)


def _fmt(s: Seller, db: Session) -> dict:
    total     = db.query(Package).filter(Package.seller_id == s.id).count()
    delivered = db.query(Package).filter(
        Package.seller_id == s.id,
        Package.status == PackageStatusEnum.delivered,
    ).count()
    return {
        "id":            s.id,
        "full_name":     s.full_name,
        "business_name": s.business_name,
        "phone":         s.phone,
        "wilaya":        s.wilaya,
        "address":       s.address,
        "pricing_tier":  s.pricing_tier,
        "is_active":     s.is_active,
        "balance":       _balance(db, s.id),
        "total_packages":   total,
        "total_delivered":  delivered,
        "created_at":    s.created_at.isoformat() if s.created_at else None,
    }


@router.get("")
async def list_sellers(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    sellers = db.query(Seller).filter(
        Seller.station_id == current_user.station_id
    ).order_by(Seller.full_name).all()
    return [_fmt(s, db) for s in sellers]


@router.get("/{seller_id}")
async def get_seller(
    seller_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    s = db.query(Seller).filter(
        Seller.id == seller_id,
        Seller.station_id == current_user.station_id,
    ).first()
    if not s:
        raise HTTPException(status_code=404, detail="Expéditeur introuvable")
    return _fmt(s, db)


@router.post("")
async def create_seller(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    body = await request.json()
    for f in ["full_name", "phone", "wilaya"]:
        if not body.get(f):
            raise HTTPException(status_code=400, detail=f"Champ requis: {f}")

    if db.query(Seller).filter(Seller.phone == body["phone"]).first():
        raise HTTPException(status_code=400, detail="Numéro déjà utilisé")

    s = Seller(
        station_id    = current_user.station_id,
        full_name     = body["full_name"],
        business_name = body.get("business_name"),
        phone         = body["phone"],
        wilaya        = body["wilaya"],
        address       = body.get("address"),
        id_number     = body.get("id_number"),
        bank_account  = body.get("bank_account"),
        pricing_tier  = body.get("pricing_tier", "standard"),
        is_active     = True,
    )
    db.add(s)
    db.add(AuditLog(
        user_id=current_user.id, station_id=current_user.station_id,
        action="seller_created", entity_type="seller",
        new_value={"full_name": s.full_name, "phone": s.phone},
    ))
    db.commit()
    db.refresh(s)
    return _fmt(s, db)


@router.patch("/{seller_id}/toggle")
async def toggle_seller(
    seller_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    s = db.query(Seller).filter(
        Seller.id == seller_id,
        Seller.station_id == current_user.station_id,
    ).first()
    if not s:
        raise HTTPException(status_code=404, detail="Expéditeur introuvable")
    s.is_active = not s.is_active
    db.commit()
    return _fmt(s, db)


@router.get("/{seller_id}/ledger")
async def get_ledger(
    seller_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    s = db.query(Seller).filter(Seller.id == seller_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Expéditeur introuvable")

    entries = db.query(SellerLedgerEntry).filter(
        SellerLedgerEntry.seller_id == seller_id
    ).order_by(SellerLedgerEntry.created_at.asc()).all()

    running = 0.0
    result  = []
    for e in entries:
        running += e.amount
        result.append({
            "id":              e.id,
            "entry_type":      e.entry_type.value if hasattr(e.entry_type, "value") else e.entry_type,
            "amount":          e.amount,
            "running_balance": round(running, 2),
            "note":            e.note,
            "package_id":      e.package_id,
            "created_at":      e.created_at.isoformat() if e.created_at else None,
        })
    return result
