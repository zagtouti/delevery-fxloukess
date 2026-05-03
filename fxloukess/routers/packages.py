from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_
from database import get_db
from models import *
from routers.auth import get_current_user, require_role
from datetime import datetime, timezone
import uuid

router = APIRouter()

def generate_tracking_id(db: Session, station_code: str) -> str:
    today = datetime.now().strftime("%Y%m%d")
    prefix = f"{station_code}{today}"
    count = db.query(Package).filter(
        Package.tracking_id.like(f"{prefix}%")
    ).count()
    return f"{prefix}{str(count + 1).zfill(4)}"

@router.get("")
async def list_packages(
    q: str = Query(""),
    status: str = Query(""),
    wilaya: str = Query(""),
    driver_id: str = Query(""),
    limit: int = Query(50),
    offset: int = Query(0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    query = db.query(Package).filter(
        Package.station_id == current_user.station_id,
        Package.is_archived == False
    )

    if q:
        query = query.filter(or_(
            Package.tracking_id.ilike(f"%{q}%"),
            Package.recipient_name.ilike(f"%{q}%"),
            Package.recipient_phone.ilike(f"%{q}%"),
            Package.recipient_phone2.ilike(f"%{q}%"),
        ))

    if status:
        query = query.filter(Package.status == status)

    if wilaya:
        query = query.filter(Package.wilaya == wilaya)

    if driver_id:
        query = query.filter(Package.driver_id == driver_id)

    total = query.count()
    packages = query.order_by(
        Package.created_at.desc()
    ).offset(offset).limit(limit).all()

    return [format_package(p) for p in packages]

@router.get("/{package_id}")
async def get_package(
    package_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    p = db.query(Package).filter(
        Package.id == package_id,
        Package.station_id == current_user.station_id
    ).first()
    if not p:
        raise HTTPException(status_code=404, detail="Colis introuvable")
    return format_package(p, full=True)

@router.post("")
async def create_package(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    body = await request.json()

    required = [
        "seller_id", "recipient_name", "recipient_phone",
        "wilaya", "commune", "address", "description", "cod_amount"
    ]
    for field in required:
        if not body.get(field):
            raise HTTPException(
                status_code=400,
                detail=f"Champ requis manquant: {field}"
            )

    station = db.query(Station).filter(
        Station.id == current_user.station_id
    ).first()

    # Check for duplicate
    duplicate = db.query(Package).filter(
        Package.recipient_phone == body["recipient_phone"],
        Package.wilaya == body["wilaya"],
        Package.cod_amount == float(body["cod_amount"]),
        Package.status.in_(["created", "assigned", "out_for_delivery"])
    ).first()

    warning = None
    if duplicate:
        warning = f"Colis similaire existe déjà: {duplicate.tracking_id}"

    # Get active shift
    shift = db.query(Shift).filter(
        Shift.station_id == current_user.station_id,
        Shift.is_closed == False
    ).first()

    # Insurance fee
    insurance_fee = None
    declared_value = body.get("declared_value")
    if declared_value:
        insurance_fee = float(declared_value) * 0.02

    package = Package(
        tracking_id=generate_tracking_id(db, station.code),
        station_id=current_user.station_id,
        seller_id=body["seller_id"],
        shift_id=shift.id if shift else None,
        recipient_name=body["recipient_name"],
        recipient_phone=body["recipient_phone"],
        recipient_phone2=body.get("recipient_phone2"),
        wilaya=body["wilaya"],
        commune=body["commune"],
        address=body["address"],
        description=body["description"],
        weight=body.get("weight"),
        cod_amount=float(body["cod_amount"]),
        declared_value=float(declared_value) if declared_value else None,
        insurance_fee=insurance_fee,
        is_fragile=body.get("is_fragile", False),
        do_not_bend=body.get("do_not_bend", False),
        notes=body.get("notes"),
        status=PackageStatusEnum.created,
        physical_location=PhysicalLocationEnum.receiving
    )
    db.add(package)
    db.flush()
    db.add(PackageHistory(
        package_id=package.id,
        user_id=current_user.id,
        shift_id=shift.id if shift else None,
        old_status=None,
        new_status="created",
        note="Colis créé"
    ))

    db.add(AuditLog(
        user_id=current_user.id,
        station_id=current_user.station_id,
        shift_id=shift.id if shift else None,
        action="package_created",
        entity_type="package",
        entity_id=package.id,
        new_value={"tracking_id": package.tracking_id}
    ))

    db.commit()
    db.refresh(package)

    result = format_package(package)
    if warning:
        result["warning"] = warning
    return result

@router.patch("/{package_id}/status")
async def update_status(
    package_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    body = await request.json()
    new_status = body.get("status")
    reason = body.get("reason")
    note = body.get("note")

    package = db.query(Package).filter(
        Package.id == package_id,
        Package.station_id == current_user.station_id
    ).first()

    if not package:
        raise HTTPException(status_code=404, detail="Colis introuvable")

    if package.status == PackageStatusEnum.sync_conflict:
        raise HTTPException(
            status_code=400,
            detail="Ce colis est en conflit de synchronisation. Résolvez le conflit d'abord."
        )

    # Validate allowed transitions
    allowed = {
        "created":             ["assigned", "held_at_station", "lost"],
        "assigned":            ["out_for_delivery", "held_at_station", "created"],
        "out_for_delivery":    ["delivered", "failed", "rescheduled", "address_changed", "waiting_for_client", "partially_delivered", "out_for_delivery"],
        "failed":              ["out_for_delivery", "returned", "held_at_station", "rescheduled", "lost"],
        "rescheduled":         ["out_for_delivery", "returned", "lost"],
        "waiting_for_client":  ["out_for_delivery", "returned", "lost"],
        "address_changed":     ["out_for_delivery", "returned"],
        "held_at_station":     ["assigned", "returned", "lost"],
        "partially_delivered": ["out_for_delivery", "delivered", "returned"],
        "delivered":           [],
        "returned":            [],
        "lost":                [],
    }

    current = package.status.value if hasattr(package.status, 'value') else package.status
    if new_status not in allowed.get(current, []):
        raise HTTPException(
            status_code=400,
            detail=f"Transition non autorisée: {current} → {new_status}"
        )

    needs_reason = ["failed", "returned", "rescheduled", "lost"]
    if new_status in needs_reason and not reason:
        raise HTTPException(
            status_code=400,
            detail="Une raison est requise pour ce statut"
        )

    old_status = current
    package.status = new_status

    if new_status == "out_for_delivery":
        package.attempts += 1
        if not package.first_attempt_at:
            package.first_attempt_at = datetime.now(timezone.utc)
        if body.get("driver_id"):
            package.driver_id = body["driver_id"]

    if new_status == "delivered":
        package.delivered_at = datetime.now(timezone.utc)
        package.cod_locked = True
        package.physical_location = PhysicalLocationEnum.with_driver

    if new_status in ["failed", "returned"]:
        package.physical_location = PhysicalLocationEnum.returns_area

    if new_status == "assigned":
        package.physical_location = PhysicalLocationEnum.dispatch_bag
        if body.get("driver_id"):
            package.driver_id = body["driver_id"]

    shift = db.query(Shift).filter(
        Shift.station_id == current_user.station_id,
        Shift.is_closed == False
    ).first()

    db.add(PackageHistory(
        package_id=package.id,
        user_id=current_user.id,
        shift_id=shift.id if shift else None,
        old_status=old_status,
        new_status=new_status,
        reason=reason,
        note=note
    ))

    db.add(AuditLog(
        user_id=current_user.id,
        station_id=current_user.station_id,
        action="status_changed",
        entity_type="package",
        entity_id=package.id,
        old_value={"status": old_status},
        new_value={"status": new_status, "reason": reason}
    ))

    # If delivered — create ledger entry for seller
    if new_status == "delivered":
        seller = db.query(Seller).filter(
            Seller.id == package.seller_id
        ).first()
        if seller:
            delivery_fee = 400.0
            cod_credit = package.cod_amount
            db.add(SellerLedgerEntry(
                seller_id=seller.id,
                package_id=package.id,
                entry_type=LedgerEntryTypeEnum.cod_credit,
                amount=cod_credit,
                note=f"COD collecté - {package.tracking_id}",
                created_by=current_user.id,
                shift_id=shift.id if shift else None
            ))
            db.add(SellerLedgerEntry(
                seller_id=seller.id,
                package_id=package.id,
                entry_type=LedgerEntryTypeEnum.delivery_fee_debit,
                amount=-delivery_fee,
                note=f"Frais de livraison - {package.tracking_id}",
                created_by=current_user.id,
                shift_id=shift.id if shift else None
            ))

        # Add to driver cash
        if package.driver_id:
            driver = db.query(Driver).filter(
                Driver.id == package.driver_id
            ).first()
            if driver:
                old_cash = driver_cash_on_hand(db, driver.id)
                db.add(DriverCashLog(
                    driver_id=driver.id,
                    package_id=package.id,
                    action="delivery_collected",
                    amount=package.cod_amount,
                    old_balance=old_cash,
                    new_balance=old_cash + package.cod_amount,
                    shift_id=shift.id if shift else None
                ))

    db.commit()
    return format_package(package)

@router.get("/{package_id}/history")
async def get_history(
    package_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    package = db.query(Package).filter(
        Package.id == package_id
    ).first()
    if not package:
        raise HTTPException(status_code=404, detail="Colis introuvable")

    history = db.query(PackageHistory).filter(
        PackageHistory.package_id == package_id
    ).order_by(PackageHistory.created_at.asc()).all()

    return [{
        "id": h.id,
        "old_status": h.old_status,
        "new_status": h.new_status,
        "reason": h.reason,
        "note": h.note,
        "created_at": h.created_at.isoformat()
    } for h in history]

def driver_cash_on_hand(db: Session, driver_id: str) -> float:
    logs = db.query(DriverCashLog).filter(
        DriverCashLog.driver_id == driver_id
    ).order_by(DriverCashLog.created_at.desc()).first()
    return logs.new_balance if logs else 0.0

def format_package(p: Package, full: bool = False) -> dict:
    result = {
        "id": p.id,
        "tracking_id": p.tracking_id,
        "recipient_name": p.recipient_name,
        "recipient_phone": p.recipient_phone,
        "recipient_phone2": p.recipient_phone2,
        "wilaya": p.wilaya,
        "commune": p.commune,
        "address": p.address,
        "description": p.description,
        "weight": p.weight,
        "cod_amount": p.cod_amount,
        "declared_value": p.declared_value,
        "insurance_fee": p.insurance_fee,
        "is_fragile": p.is_fragile,
        "do_not_bend": p.do_not_bend,
        "notes": p.notes,
        "status": p.status.value if hasattr(p.status, 'value') else p.status,
        "physical_location": p.physical_location.value if hasattr(p.physical_location, 'value') else p.physical_location,
        "attempts": p.attempts,
        "cod_locked": p.cod_locked,
        "seller_id": p.seller_id,
        "driver_id": p.driver_id,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "delivered_at": p.delivered_at.isoformat() if p.delivered_at else None,
    }
    if full and p.history:
        result["history"] = [{
            "old_status": h.old_status,
            "new_status": h.new_status,
            "reason": h.reason,
            "note": h.note,
            "created_at": h.created_at.isoformat()
        } for h in p.history]
    return result