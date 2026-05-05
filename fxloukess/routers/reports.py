"""
routers/reports.py — v3 NEW
Daily / shift / driver reports returned as JSON (frontend renders them,
or the caller can request CSV via ?format=csv).
"""
import csv
import io
import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import get_db
from models import (
    Driver, DriverCashLog, Package, PackageStatusEnum,
    PettyCashEntry, Seller, SellerLedgerEntry, Shift, User,
)
from routers.auth import get_current_user
from utils import ev

logger = logging.getLogger("fxloukess.reports")
router = APIRouter()


# ── Daily summary ─────────────────────────────────────────────────────────────

@router.get("/daily")
async def daily_report(
    date:   str = Query("", description="YYYY-MM-DD, defaults to today"),
    format: str = Query("json", description="json | csv"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Full daily summary — packages, COD, failures, petty cash, driver stats."""
    if date:
        try:
            day_start = datetime.fromisoformat(date).replace(
                hour=0, minute=0, second=0, microsecond=0,
                tzinfo=timezone.utc,
            )
        except ValueError:
            day_start = _today_start()
    else:
        day_start = _today_start()

    day_end = day_start + timedelta(days=1)
    sid     = current_user.station_id

    # Packages created today
    pkgs = db.query(Package).filter(
        Package.station_id == sid,
        Package.created_at >= day_start,
        Package.created_at <  day_end,
    ).all()

    # Delivered today
    delivered = [p for p in pkgs if ev(p.status) == "delivered"]

    # Status breakdown
    status_counts: dict[str, int] = {}
    for p in pkgs:
        s = ev(p.status)
        status_counts[s] = status_counts.get(s, 0) + 1

    # Wilaya breakdown (delivered)
    wilaya_counts: dict[str, dict] = {}
    for p in delivered:
        w = p.wilaya
        if w not in wilaya_counts:
            wilaya_counts[w] = {"delivered": 0, "cod": 0.0}
        wilaya_counts[w]["delivered"] += 1
        wilaya_counts[w]["cod"]       += p.cod_amount

    # COD
    cod_total = sum(p.cod_amount for p in delivered)

    # Petty cash
    petty = db.query(func.sum(PettyCashEntry.amount)).filter(
        PettyCashEntry.station_id == sid,
        PettyCashEntry.created_at >= day_start,
        PettyCashEntry.created_at <  day_end,
    ).scalar() or 0.0

    # Driver performance
    drivers = db.query(Driver).filter(
        Driver.station_id == sid, Driver.is_active == True
    ).all()
    driver_rows = []
    for d in drivers:
        d_delivered = db.query(Package).filter(
            Package.driver_id   == d.id,
            Package.status      == PackageStatusEnum.delivered,
            Package.delivered_at >= day_start,
            Package.delivered_at <  day_end,
        ).count()
        d_failed = db.query(Package).filter(
            Package.driver_id == d.id,
            Package.status    == PackageStatusEnum.failed,
            Package.created_at >= day_start,
            Package.created_at <  day_end,
        ).count()
        d_cod = db.query(func.sum(Package.cod_amount)).filter(
            Package.driver_id   == d.id,
            Package.status      == PackageStatusEnum.delivered,
            Package.delivered_at >= day_start,
            Package.delivered_at <  day_end,
        ).scalar() or 0.0
        driver_rows.append({
            "driver_id":   d.id,
            "name":        d.full_name,
            "delivered":   d_delivered,
            "failed":      d_failed,
            "cod":         round(d_cod, 2),
        })

    report = {
        "date":          day_start.strftime("%Y-%m-%d"),
        "station_id":    sid,
        "total_created": len(pkgs),
        "total_delivered": len(delivered),
        "total_failed":  status_counts.get("failed", 0),
        "total_returned": status_counts.get("returned", 0),
        "cod_total":     round(cod_total, 2),
        "petty_cash":    round(float(petty), 2),
        "net_cash":      round(cod_total - float(petty), 2),
        "status_breakdown": status_counts,
        "wilaya_breakdown": wilaya_counts,
        "drivers":       driver_rows,
        "packages": [{
            "tracking_id":    p.tracking_id,
            "recipient_name": p.recipient_name,
            "wilaya":         p.wilaya,
            "cod_amount":     p.cod_amount,
            "status":         ev(p.status),
            "driver_id":      p.driver_id,
            "created_at":     p.created_at.isoformat() if p.created_at else None,
        } for p in pkgs],
    }

    if format == "csv":
        return _to_csv(report)
    return report


# ── Shift report ──────────────────────────────────────────────────────────────

@router.get("/shift/{shift_id}")
async def shift_report(
    shift_id: str,
    format:   str = Query("json"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    shift = db.query(Shift).filter(Shift.id == shift_id).first()
    if not shift:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Shift introuvable")

    pkgs = db.query(Package).filter(Package.shift_id == shift_id).all()
    delivered = [p for p in pkgs if ev(p.status) == "delivered"]
    cod       = sum(p.cod_amount for p in delivered)

    petty = db.query(func.sum(PettyCashEntry.amount)).filter(
        PettyCashEntry.shift_id == shift_id
    ).scalar() or 0.0

    report = {
        "shift_id":        shift_id,
        "shift_type":      ev(shift.shift_type),
        "opened_at":       shift.opened_at.isoformat() if shift.opened_at else None,
        "closed_at":       shift.closed_at.isoformat() if shift.closed_at else None,
        "is_closed":       shift.is_closed,
        "total_packages":  len(pkgs),
        "delivered":       len(delivered),
        "failed":          sum(1 for p in pkgs if ev(p.status) == "failed"),
        "cod_total":       round(cod, 2),
        "petty_cash":      round(float(petty), 2),
        "net_cash":        round(cod - float(petty), 2),
    }
    if format == "csv":
        return _to_csv(report)
    return report


# ── Driver report ─────────────────────────────────────────────────────────────

@router.get("/driver/{driver_id}")
async def driver_report(
    driver_id: str,
    days:      int = Query(7, le=90),
    format:    str = Query("json"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    since = datetime.now(timezone.utc) - timedelta(days=days)

    pkgs = db.query(Package).filter(
        Package.driver_id  == driver_id,
        Package.created_at >= since,
    ).all()

    delivered = [p for p in pkgs if ev(p.status) == "delivered"]
    cod       = sum(p.cod_amount for p in delivered)

    # Cash movements
    cash_logs = db.query(DriverCashLog).filter(
        DriverCashLog.driver_id  == driver_id,
        DriverCashLog.created_at >= since,
    ).order_by(DriverCashLog.created_at.desc()).all()

    collections = [l for l in cash_logs if l.action == "cash_collected_by_station"]
    total_collected = abs(sum(l.amount for l in collections))

    report = {
        "driver_id":       driver_id,
        "days":            days,
        "total_packages":  len(pkgs),
        "delivered":       len(delivered),
        "failed":          sum(1 for p in pkgs if ev(p.status) == "failed"),
        "returned":        sum(1 for p in pkgs if ev(p.status) == "returned"),
        "cod_total":       round(cod, 2),
        "cash_collected":  round(total_collected, 2),
        "current_balance": cash_logs[0].new_balance if cash_logs else 0.0,
        "success_rate":    round(len(delivered) / len(pkgs) * 100, 1) if pkgs else 0,
        "cash_movements": [{
            "action":      l.action,
            "amount":      l.amount,
            "new_balance": l.new_balance,
            "note":        l.note,
            "created_at":  l.created_at.isoformat() if l.created_at else None,
        } for l in cash_logs],
    }
    if format == "csv":
        return _to_csv(report)
    return report


# ── Helpers ───────────────────────────────────────────────────────────────────

def _today_start() -> datetime:
    return datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )


def _to_csv(data: dict) -> StreamingResponse:
    """Convert flat report dict to CSV (non-list fields only)."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["champ", "valeur"])
    for k, v in data.items():
        if not isinstance(v, (list, dict)):
            writer.writerow([k, v])
    output.seek(0)
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode("utf-8-sig")),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=rapport_{data.get('date','export')}.csv"},
    )
