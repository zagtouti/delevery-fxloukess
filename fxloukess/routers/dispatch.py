"""routers/dispatch.py — v3. Uses utils. Adds wilaya grouping."""
import logging
from datetime import datetime, timezone
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from database import get_db
from models import Driver, Package, PackageStatusEnum, PhysicalLocationEnum, User
from routers.auth import get_current_user
from utils import audit, ev, fmt_package, log_event, open_shift

logger = logging.getLogger("fxloukess.dispatch")
router = APIRouter()


@router.get("/ready")
async def ready_for_dispatch(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    pkgs = db.query(Package).filter(
        Package.station_id        == current_user.station_id,
        Package.status            == PackageStatusEnum.created,
        Package.physical_location == PhysicalLocationEnum.shelf,
        Package.is_archived       == False,
    ).order_by(Package.wilaya, Package.created_at.asc()).all()
    return [fmt_package(p) for p in pkgs]


@router.get("/ready/grouped")
async def ready_grouped_by_wilaya(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """NEW v3 — packages grouped by wilaya for easier bag building."""
    pkgs = db.query(Package).filter(
        Package.station_id        == current_user.station_id,
        Package.status            == PackageStatusEnum.created,
        Package.physical_location == PhysicalLocationEnum.shelf,
        Package.is_archived       == False,
    ).order_by(Package.wilaya, Package.created_at.asc()).all()

    groups: dict[str, dict] = defaultdict(lambda: {"wilaya": "", "count": 0, "cod_total": 0.0, "packages": []})
    for p in pkgs:
        w = p.wilaya
        groups[w]["wilaya"]    = w
        groups[w]["count"]    += 1
        groups[w]["cod_total"] = round(groups[w]["cod_total"] + p.cod_amount, 2)
        groups[w]["packages"].append(fmt_package(p))

    return sorted(groups.values(), key=lambda g: g["count"], reverse=True)


@router.post("/assign")
async def assign_packages(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    body        = await request.json()
    driver_id   = body.get("driver_id")
    package_ids = body.get("package_ids", [])

    if not driver_id or not package_ids:
        raise HTTPException(status_code=400, detail="driver_id et package_ids requis")

    driver = db.query(Driver).filter(
        Driver.id == driver_id,
        Driver.station_id == current_user.station_id,
        Driver.is_active  == True,
    ).first()
    if not driver:
        raise HTTPException(status_code=404, detail="Livreur introuvable ou inactif")

    shift    = open_shift(db, current_user.station_id)
    assigned = []

    for pid in package_ids:
        pkg = db.query(Package).filter(
            Package.id         == pid,
            Package.station_id == current_user.station_id,
            Package.is_archived == False,
        ).first()
        if not pkg:
            continue
        old = ev(pkg.status)
        pkg.driver_id         = driver_id
        pkg.status            = PackageStatusEnum.assigned
        pkg.physical_location = PhysicalLocationEnum.dispatch_bag
        log_event(db, package_id=pkg.id, user_id=current_user.id,
                  shift_id=shift.id if shift else None,
                  old_status=old, new_status="assigned",
                  note=f"Assigné — {driver.full_name}")
        assigned.append(pkg.tracking_id)

    audit(db, action="packages_assigned", user_id=current_user.id,
          station_id=current_user.station_id,
          entity_type="driver", entity_id=driver_id,
          new_value={"count": len(assigned), "tracking_ids": assigned})
    db.commit()
    return {"success": True, "assigned": len(assigned), "tracking_ids": assigned}


@router.get("/driver/{driver_id}/bag")
async def driver_bag(
    driver_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    pkgs = db.query(Package).filter(
        Package.driver_id  == driver_id,
        Package.station_id == current_user.station_id,
        Package.status.in_([PackageStatusEnum.assigned, PackageStatusEnum.out_for_delivery]),
        Package.is_archived == False,
    ).order_by(Package.wilaya).all()
    return [fmt_package(p) for p in pkgs]


@router.post("/driver/{driver_id}/depart")
async def driver_depart(
    driver_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Bulk move all assigned packages to out_for_delivery."""
    shift = open_shift(db, current_user.station_id)
    pkgs  = db.query(Package).filter(
        Package.driver_id  == driver_id,
        Package.station_id == current_user.station_id,
        Package.status     == PackageStatusEnum.assigned,
    ).all()

    now = datetime.now(timezone.utc)
    for pkg in pkgs:
        pkg.status            = PackageStatusEnum.out_for_delivery
        pkg.physical_location = PhysicalLocationEnum.with_driver
        pkg.attempts         += 1
        if not pkg.first_attempt_at:
            pkg.first_attempt_at = now
        log_event(db, package_id=pkg.id, user_id=current_user.id,
                  shift_id=shift.id if shift else None,
                  old_status="assigned", new_status="out_for_delivery")

    audit(db, action="driver_departed", user_id=current_user.id,
          station_id=current_user.station_id,
          entity_type="driver", entity_id=driver_id,
          new_value={"count": len(pkgs)})
    db.commit()
    return {"success": True, "count": len(pkgs)}
