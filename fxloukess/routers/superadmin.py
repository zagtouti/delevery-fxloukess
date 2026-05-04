"""routers/superadmin.py — Users, stats, finance, alerts, audit, stations, wilaya prices."""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from sqlalchemy import func

from config import DEFAULT_WILAYA_PRICES
from database import get_db
from models import (
    Alert, AlertSeverityEnum, AuditLog, Driver, DriverCashLog,
    LedgerEntryTypeEnum, Package, PackageStatusEnum, RoleEnum,
    Seller, SellerLedgerEntry, Shift, Station, User, UserSession,
)
from routers.auth import get_current_user, require_role

logger = logging.getLogger("fxloukess.superadmin")
router = APIRouter()
_pwd   = CryptContext(schemes=["bcrypt"], deprecated="auto")

# In-memory price overrides (replace with DB table for persistence)
_wilaya_prices = dict(DEFAULT_WILAYA_PRICES)


# ── Users ─────────────────────────────────────────────────────────────────────

@router.get("/users")
async def list_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.superadmin, RoleEnum.regional_manager)),
):
    users = db.query(User).filter(
        User.station_id == current_user.station_id
    ).order_by(User.full_name).all()
    return [{
        "id":         u.id,
        "full_name":  u.full_name,
        "phone":      u.phone,
        "role":       u.role.value if hasattr(u.role, "value") else u.role,
        "is_active":  u.is_active,
        "last_login": u.last_login.isoformat() if u.last_login else None,
        "created_at": u.created_at.isoformat() if u.created_at else None,
    } for u in users]


@router.post("/users")
async def create_user(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.superadmin)),
):
    body = await request.json()
    for f in ["full_name", "phone", "role", "password"]:
        if not body.get(f):
            raise HTTPException(status_code=400, detail=f"Champ requis: {f}")

    if body["role"] not in [r.value for r in RoleEnum]:
        raise HTTPException(status_code=400, detail="Rôle invalide")

    if db.query(User).filter(User.phone == body["phone"]).first():
        raise HTTPException(status_code=400, detail="Ce numéro est déjà utilisé")

    user = User(
        station_id      = current_user.station_id,
        full_name       = body["full_name"],
        phone           = body["phone"],
        hashed_password = _pwd.hash(body["password"]),
        role            = body["role"],
        is_active       = True,
        language        = body.get("language", "fr"),
    )
    db.add(user)
    db.flush()
    db.add(AuditLog(
        user_id=current_user.id, station_id=current_user.station_id,
        action="user_created", entity_type="user", entity_id=user.id,
        new_value={"full_name": user.full_name, "role": body["role"]},
    ))
    db.commit()
    db.refresh(user)
    return {
        "id": user.id, "full_name": user.full_name,
        "phone": user.phone,
        "role": user.role.value if hasattr(user.role, "value") else user.role,
        "is_active": user.is_active,
    }


@router.patch("/users/{user_id}/toggle")
async def toggle_user(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.superadmin)),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="Impossible de désactiver son propre compte")
    user.is_active = not user.is_active
    db.commit()
    return {"id": user.id, "is_active": user.is_active}


@router.post("/users/{user_id}/force-logout")
async def force_logout(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.superadmin)),
):
    db.query(UserSession).filter(
        UserSession.user_id == user_id
    ).update({"is_active": False})
    db.add(AuditLog(
        user_id=current_user.id, station_id=current_user.station_id,
        action="force_logout", entity_type="user", entity_id=user_id,
    ))
    db.commit()
    return {"success": True}


# ── Dashboard stats ───────────────────────────────────────────────────────────

@router.get("/stats")
async def get_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    sid   = current_user.station_id

    total_today     = db.query(Package).filter(Package.station_id == sid, Package.created_at >= today).count()
    delivered_today = db.query(Package).filter(Package.station_id == sid, Package.status == PackageStatusEnum.delivered, Package.delivered_at >= today).count()
    out             = db.query(Package).filter(Package.station_id == sid, Package.status == PackageStatusEnum.out_for_delivery).count()
    pending_receive = db.query(Package).filter(Package.station_id == sid, Package.status == PackageStatusEnum.created).count()
    failed_today    = db.query(Package).filter(Package.station_id == sid, Package.status == PackageStatusEnum.failed, Package.created_at >= today).count()
    cod_pkgs        = db.query(Package).filter(Package.station_id == sid, Package.status == PackageStatusEnum.delivered, Package.delivered_at >= today).all()
    cod_today       = sum(p.cod_amount for p in cod_pkgs)
    active_drivers  = db.query(Driver).filter(Driver.station_id == sid, Driver.is_active == True).count()
    open_alerts     = db.query(Alert).filter(Alert.station_id == sid, Alert.is_resolved == False).count()

    return {
        "total_today":     total_today,
        "delivered_today": delivered_today,
        "out_for_delivery": out,
        "pending_receive": pending_receive,
        "failed_today":    failed_today,
        "cod_today":       cod_today,
        "active_drivers":  active_drivers,
        "open_alerts":     open_alerts,
    }


# ── Finance ───────────────────────────────────────────────────────────────────

@router.get("/finance")
async def get_finance(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    sid   = current_user.station_id

    delivered = db.query(Package).filter(Package.station_id == sid, Package.status == PackageStatusEnum.delivered, Package.delivered_at >= today).all()
    cod_today = sum(p.cod_amount for p in delivered)

    out_pkgs = db.query(Package).filter(Package.station_id == sid, Package.status == PackageStatusEnum.out_for_delivery).all()
    cod_with_drivers = sum(p.cod_amount for p in out_pkgs)

    # Pending seller payouts (positive balance = owed to seller)
    rows = db.query(
        SellerLedgerEntry.seller_id,
        func.sum(SellerLedgerEntry.amount).label("balance"),
    ).filter(
        SellerLedgerEntry.seller_id.in_(
            db.query(Seller.id).filter(Seller.station_id == sid)
        )
    ).group_by(SellerLedgerEntry.seller_id).having(
        func.sum(SellerLedgerEntry.amount) > 0
    ).all()
    pending_payout = sum(r.balance for r in rows)

    # Per-driver cash
    drivers = db.query(Driver).filter(Driver.station_id == sid, Driver.is_active == True).all()
    driver_cash = []
    for d in drivers:
        log = db.query(DriverCashLog).filter(DriverCashLog.driver_id == d.id).order_by(DriverCashLog.created_at.desc()).first()
        cash = log.new_balance if log else 0.0
        if cash > 0:
            driver_cash.append({"driver_id": d.id, "name": d.full_name, "cash": cash})

    return {
        "cod_today":       cod_today,
        "cod_with_drivers": cod_with_drivers,
        "pending_payout":  round(pending_payout, 2),
        "driver_cash":     driver_cash,
    }


@router.get("/finance/sellers")
async def finance_sellers(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    results = db.query(
        Seller,
        func.sum(SellerLedgerEntry.amount).label("balance"),
    ).outerjoin(SellerLedgerEntry, Seller.id == SellerLedgerEntry.seller_id).filter(
        Seller.station_id == current_user.station_id
    ).group_by(Seller.id).all()

    return [{
        "id":        s.id,
        "full_name": s.full_name,
        "phone":     s.phone,
        "balance":   round(float(balance or 0), 2),
    } for s, balance in results]


# ── Alerts ────────────────────────────────────────────────────────────────────

@router.get("/alerts")
async def list_alerts(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    alerts = db.query(Alert).filter(
        Alert.station_id == current_user.station_id,
        Alert.is_resolved == False,
    ).order_by(Alert.created_at.desc()).all()
    return [_fmt_alert(a) for a in alerts]


@router.post("/alerts")
async def create_alert(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    body = await request.json()
    for f in ["title", "severity", "alert_type"]:
        if not body.get(f):
            raise HTTPException(status_code=400, detail=f"Champ requis: {f}")

    if body["severity"] not in [s.value for s in AlertSeverityEnum]:
        raise HTTPException(status_code=400, detail="Sévérité invalide")

    a = Alert(
        station_id=current_user.station_id,
        severity=body["severity"],
        alert_type=body["alert_type"],
        title=body["title"],
        description=body.get("description"),
        reference_id=body.get("reference_id"),
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return _fmt_alert(a)


@router.patch("/alerts/{alert_id}/resolve")
async def resolve_alert(
    alert_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    body  = await request.json()
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alerte introuvable")
    alert.is_resolved     = True
    alert.resolved_by     = current_user.id
    alert.resolved_at     = datetime.now(timezone.utc)
    alert.resolution_note = body.get("resolution_note")
    db.commit()
    return _fmt_alert(alert)


# ── Audit log ─────────────────────────────────────────────────────────────────

@router.get("/audit")
async def get_audit(
    limit:  int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.superadmin)),
):
    logs = db.query(AuditLog).filter(
        AuditLog.station_id == current_user.station_id
    ).order_by(AuditLog.created_at.desc()).offset(offset).limit(limit).all()
    return [{
        "id":          l.id,
        "action":      l.action,
        "entity_type": l.entity_type,
        "entity_id":   l.entity_id,
        "user_id":     l.user_id,
        "old_value":   l.old_value,
        "new_value":   l.new_value,
        "ip_address":  l.ip_address,
        "created_at":  l.created_at.isoformat() if l.created_at else None,
    } for l in logs]


# ── Stations ──────────────────────────────────────────────────────────────────

@router.get("/stations")
async def list_stations(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.superadmin)),
):
    stations = db.query(Station).filter(Station.is_active == True).all()
    return [{
        "id":        s.id,
        "code":      s.code,
        "name":      s.name,
        "wilaya":    s.wilaya,
        "phone":     s.phone,
        "is_active": s.is_active,
    } for s in stations]


@router.post("/stations")
async def create_station(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.superadmin)),
):
    body = await request.json()
    for f in ["code", "name", "wilaya"]:
        if not body.get(f):
            raise HTTPException(status_code=400, detail=f"Champ requis: {f}")

    if db.query(Station).filter(Station.code == body["code"]).first():
        raise HTTPException(status_code=400, detail="Code station déjà utilisé")

    s = Station(
        code=body["code"], name=body["name"], wilaya=body["wilaya"],
        address=body.get("address"), phone=body.get("phone"), is_active=True,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return {"id": s.id, "code": s.code, "name": s.name}


# ── Wilaya prices ─────────────────────────────────────────────────────────────

@router.get("/wilaya-prices")
async def get_wilaya_prices(current_user: User = Depends(get_current_user)):
    return _wilaya_prices


@router.patch("/wilaya-prices")
async def update_wilaya_prices(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.superadmin)),
):
    body   = await request.json()
    wilaya = body.get("wilaya")
    home   = body.get("home")
    desk   = body.get("desk")

    if not wilaya or home is None or desk is None:
        raise HTTPException(status_code=400, detail="wilaya, home et desk requis")

    _wilaya_prices[wilaya] = {"home": int(home), "desk": int(desk)}
    db.add(AuditLog(
        user_id=current_user.id, station_id=current_user.station_id,
        action="wilaya_price_updated", entity_type="config",
        new_value={"wilaya": wilaya, "home": home, "desk": desk},
    ))
    db.commit()
    return {"success": True, "wilaya": wilaya, "home": home, "desk": desk}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt_alert(a: Alert) -> dict:
    return {
        "id":              a.id,
        "severity":        a.severity.value if hasattr(a.severity, "value") else a.severity,
        "alert_type":      a.alert_type,
        "title":           a.title,
        "description":     a.description,
        "is_resolved":     a.is_resolved,
        "resolution_note": a.resolution_note,
        "created_at":      a.created_at.isoformat() if a.created_at else None,
        "resolved_at":     a.resolved_at.isoformat() if a.resolved_at else None,
    }
