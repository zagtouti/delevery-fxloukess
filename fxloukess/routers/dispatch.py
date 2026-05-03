from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from database import get_db
from models import *
from routers.auth import get_current_user
from datetime import datetime, timezone

router = APIRouter()

# ── List ready-to-dispatch packages ─────────────────────────────────────────

@router.get("/ready")
async def ready_for_dispatch(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Packages on shelf ready to be assigned to a driver."""
    pkgs = db.query(Package).filter(
        Package.station_id == current_user.station_id,
        Package.status == PackageStatusEnum.created,
        Package.physical_location == PhysicalLocationEnum.shelf,
        Package.is_archived == False
    ).order_by(Package.created_at.asc()).all()
    return [_fmt_pkg(p) for p in pkgs]

# ── Assign packages to driver ────────────────────────────────────────────────

@router.post("/assign")
async def assign_packages(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Assign a list of package IDs to a driver."""
    body = await request.json()
    driver_id = body.get("driver_id")
    package_ids = body.get("package_ids", [])

    if not driver_id or not package_ids:
        raise HTTPException(status_code=400, detail="driver_id et package_ids requis")

    driver = db.query(Driver).filter(
        Driver.id == driver_id,
        Driver.station_id == current_user.station_id,
        Driver.is_active == True
    ).first()
    if not driver:
        raise HTTPException(status_code=404, detail="Livreur introuvable ou inactif")

    shift = db.query(Shift).filter(
        Shift.station_id == current_user.station_id,
        Shift.is_closed == False
    ).first()

    assigned = []
    for pid in package_ids:
        pkg = db.query(Package).filter(
            Package.id == pid,
            Package.station_id == current_user.station_id
        ).first()
        if not pkg:
            continue
        old_status = pkg.status.value if hasattr(pkg.status, "value") else pkg.status
        pkg.driver_id = driver_id
        pkg.status = PackageStatusEnum.assigned
        pkg.physical_location = PhysicalLocationEnum.dispatch_bag
        db.add(PackageHistory(
            package_id=pkg.id,
            user_id=current_user.id,
            shift_id=shift.id if shift else None,
            old_status=old_status,
            new_status="assigned",
            note=f"Assigné au livreur {driver.full_name}"
        ))
        assigned.append(pkg.tracking_id)

    db.add(AuditLog(
        user_id=current_user.id,
        station_id=current_user.station_id,
        action="packages_assigned",
        entity_type="driver",
        entity_id=driver_id,
        new_value={"count": len(assigned), "tracking_ids": assigned}
    ))
    db.commit()
    return {"success": True, "assigned": len(assigned), "tracking_ids": assigned}

# ── Driver's current bag ─────────────────────────────────────────────────────

@router.get("/driver/{driver_id}/bag")
async def driver_bag(
    driver_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """All packages currently assigned to / out with a driver."""
    pkgs = db.query(Package).filter(
        Package.driver_id == driver_id,
        Package.station_id == current_user.station_id,
        Package.status.in_([PackageStatusEnum.assigned, PackageStatusEnum.out_for_delivery]),
        Package.is_archived == False
    ).all()
    return [_fmt_pkg(p) for p in pkgs]

# ── Mark full bag as out-for-delivery ────────────────────────────────────────

@router.post("/driver/{driver_id}/depart")
async def driver_depart(
    driver_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Move all assigned packages to out_for_delivery when driver leaves."""
    shift = db.query(Shift).filter(
        Shift.station_id == current_user.station_id,
        Shift.is_closed == False
    ).first()

    pkgs = db.query(Package).filter(
        Package.driver_id == driver_id,
        Package.station_id == current_user.station_id,
        Package.status == PackageStatusEnum.assigned
    ).all()

    for pkg in pkgs:
        pkg.status = PackageStatusEnum.out_for_delivery
        pkg.physical_location = PhysicalLocationEnum.with_driver
        pkg.attempts += 1
        if not pkg.first_attempt_at:
            pkg.first_attempt_at = datetime.now(timezone.utc)
        db.add(PackageHistory(
            package_id=pkg.id,
            user_id=current_user.id,
            shift_id=shift.id if shift else None,
            old_status="assigned",
            new_status="out_for_delivery"
        ))

    db.commit()
    return {"success": True, "count": len(pkgs)}

# ── Helpers ──────────────────────────────────────────────────────────────────

def _fmt_pkg(p: Package) -> dict:
    return {
        "id": p.id,
        "tracking_id": p.tracking_id,
        "recipient_name": p.recipient_name,
        "recipient_phone": p.recipient_phone,
        "wilaya": p.wilaya,
        "commune": p.commune,
        "address": p.address,
        "cod_amount": p.cod_amount,
        "is_fragile": p.is_fragile,
        "status": p.status.value if hasattr(p.status, "value") else p.status,
        "physical_location": p.physical_location.value if hasattr(p.physical_location, "value") else p.physical_location,
        "driver_id": p.driver_id,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }
