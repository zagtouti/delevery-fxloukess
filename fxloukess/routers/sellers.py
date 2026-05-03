from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import func
from database import get_db
from models import *
from routers.auth import get_current_user
from passlib.context import CryptContext

router = APIRouter()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

@router.get("")
async def list_sellers(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    sellers = db.query(Seller).filter(
        Seller.station_id == current_user.station_id
    ).all()
    return [format_seller(s, db) for s in sellers]

@router.get("/{seller_id}")
async def get_seller(
    seller_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    s = db.query(Seller).filter(
        Seller.id == seller_id,
        Seller.station_id == current_user.station_id
    ).first()
    if not s:
        raise HTTPException(status_code=404, detail="Expéditeur introuvable")
    return format_seller(s, db, full=True)

@router.post("")
async def create_seller(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    body = await request.json()

    required = ["full_name", "phone", "wilaya"]
    for field in required:
        if not body.get(field):
            raise HTTPException(
                status_code=400,
                detail=f"Champ requis: {field}"
            )

    existing = db.query(Seller).filter(
        Seller.phone == body["phone"]
    ).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail="Ce numéro est déjà utilisé"
        )

    seller = Seller(
        station_id=current_user.station_id,
        full_name=body["full_name"],
        business_name=body.get("business_name"),
        phone=body["phone"],
        wilaya=body["wilaya"],
        address=body.get("address"),
        id_number=body.get("id_number"),
        bank_account=body.get("bank_account"),
        pricing_tier=body.get("pricing_tier", "standard"),
        language=body.get("language", "fr"),
        is_active=True
    )
    db.add(seller)

    db.add(AuditLog(
        user_id=current_user.id,
        station_id=current_user.station_id,
        action="seller_created",
        entity_type="seller",
        entity_id=seller.id,
        new_value={"full_name": seller.full_name}
    ))

    db.commit()
    db.refresh(seller)
    return format_seller(seller, db)

@router.get("/{seller_id}/ledger")
async def get_ledger(
    seller_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    seller = db.query(Seller).filter(
        Seller.id == seller_id,
        Seller.station_id == current_user.station_id
    ).first()
    if not seller:
        raise HTTPException(status_code=404, detail="Expéditeur introuvable")

    entries = db.query(SellerLedgerEntry).filter(
        SellerLedgerEntry.seller_id == seller_id
    ).order_by(SellerLedgerEntry.created_at.asc()).all()

    running = 0.0
    result = []
    for e in entries:
        running += e.amount
        result.append({
            "id": e.id,
            "entry_type": e.entry_type.value if hasattr(e.entry_type, 'value') else e.entry_type,
            "amount": e.amount,
            "running_balance": round(running, 2),
            "note": e.note,
            "package_id": e.package_id,
            "created_at": e.created_at.isoformat()
        })
    return result

@router.patch("/{seller_id}/toggle")
async def toggle_seller(
    seller_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    seller = db.query(Seller).filter(
        Seller.id == seller_id,
        Seller.station_id == current_user.station_id
    ).first()
    if not seller:
        raise HTTPException(status_code=404, detail="Expéditeur introuvable")
    seller.is_active = not seller.is_active
    db.commit()
    return format_seller(seller, db)

def get_seller_balance(db: Session, seller_id: str) -> float:
    entries = db.query(SellerLedgerEntry).filter(
        SellerLedgerEntry.seller_id == seller_id
    ).all()
    return round(sum(e.amount for e in entries), 2)

def format_seller(s: Seller, db: Session, full: bool = False) -> dict:
    balance = get_seller_balance(db, s.id)
    total_packages = db.query(Package).filter(
        Package.seller_id == s.id
    ).count()
    total_delivered = db.query(Package).filter(
        Package.seller_id == s.id,
        Package.status == PackageStatusEnum.delivered
    ).count()
    total_returned = db.query(Package).filter(
        Package.seller_id == s.id,
        Package.status == PackageStatusEnum.returned
    ).count()
    result = {
        "id": s.id,
        "full_name": s.full_name,
        "business_name": s.business_name,
        "phone": s.phone,
        "wilaya": s.wilaya,
        "address": s.address,
        "bank_account": s.bank_account,
        "pricing_tier": s.pricing_tier,
        "is_active": s.is_active,
        "language": s.language,
        "balance": balance,
        "total_packages": total_packages,
        "total_delivered": total_delivered,
        "total_returned": total_returned,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }
    return result