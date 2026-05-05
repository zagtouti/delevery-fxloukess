"""
utils.py — Shared helpers used by every router.
Import from here instead of duplicating logic per file.
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from models import (
    AuditLog, DriverCashLog, Package, PackageHistory,
    Shift, User,
)

logger = logging.getLogger("fxloukess.utils")


# ── Status helpers ────────────────────────────────────────────────────────────

def ev(val: Any) -> Any:
    """Return .value if an enum, else the value itself."""
    return val.value if hasattr(val, "value") else val


# ── Shift ─────────────────────────────────────────────────────────────────────

def open_shift(db: Session, station_id: str) -> Shift | None:
    return db.query(Shift).filter(
        Shift.station_id == station_id,
        Shift.is_closed == False,
    ).first()


# ── Package event log (plugin concept merged here) ────────────────────────────

def log_event(
    db: Session,
    *,
    package_id: str,
    user_id: str,
    old_status: str | None,
    new_status: str,
    reason: str | None = None,
    note: str | None = None,
    shift_id: str | None = None,
    payload: dict | None = None,
) -> PackageHistory:
    """
    Central event logger for all package state changes.
    Merges the 'log_event' plugin concept into PackageHistory.
    payload is stored in the note field as JSON summary when provided.
    """
    note_str = note or ""
    if payload and not note_str:
        note_str = str(payload)

    entry = PackageHistory(
        package_id=package_id,
        user_id=user_id,
        shift_id=shift_id,
        old_status=old_status,
        new_status=new_status,
        reason=reason,
        note=note_str or None,
    )
    db.add(entry)
    return entry


# ── Audit ─────────────────────────────────────────────────────────────────────

def audit(
    db: Session,
    *,
    action: str,
    user_id: str | None = None,
    station_id: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    old_value: dict | None = None,
    new_value: dict | None = None,
    ip_address: str | None = None,
    shift_id: str | None = None,
) -> None:
    db.add(AuditLog(
        user_id=user_id,
        station_id=station_id,
        shift_id=shift_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        old_value=old_value,
        new_value=new_value,
        ip_address=ip_address,
    ))


# ── Driver cash ───────────────────────────────────────────────────────────────

def driver_cash_balance(db: Session, driver_id: str) -> float:
    """Return current cash-on-hand for a driver."""
    log = db.query(DriverCashLog).filter(
        DriverCashLog.driver_id == driver_id
    ).order_by(DriverCashLog.created_at.desc()).first()
    return log.new_balance if log else 0.0


def record_cash_event(
    db: Session,
    *,
    driver_id: str,
    action: str,
    amount: float,          # positive = driver gains, negative = station collects
    package_id: str | None = None,
    confirmed_by: str | None = None,
    shift_id: str | None = None,
    package_ids: list[str] | None = None,   # for bulk collection (plugin Payment concept)
) -> DriverCashLog:
    old_bal = driver_cash_balance(db, driver_id)
    new_bal = old_bal + amount
    entry = DriverCashLog(
        driver_id=driver_id,
        package_id=package_id,
        action=action,
        amount=amount,
        old_balance=old_bal,
        new_balance=new_bal,
        confirmed_by=confirmed_by,
        shift_id=shift_id,
    )
    db.add(entry)
    return entry


# ── Package serialiser ────────────────────────────────────────────────────────

def fmt_package(p: Package, *, full: bool = False, events: bool = False) -> dict:
    d: dict = {
        "id":               p.id,
        "tracking_id":      p.tracking_id,
        "station_id":       p.station_id,
        "seller_id":        p.seller_id,
        "driver_id":        p.driver_id,
        "source":           p.source,
        "walk_in_name":     p.walk_in_name,
        "walk_in_phone":    p.walk_in_phone,
        "recipient_name":   p.recipient_name,
        "recipient_phone":  p.recipient_phone,
        "recipient_phone2": p.recipient_phone2,
        "wilaya":           p.wilaya,
        "commune":          p.commune,
        "address":          p.address,
        "description":      p.description,
        "weight":           p.weight,
        "cod_amount":       p.cod_amount,
        "declared_value":   p.declared_value,
        "insurance_fee":    p.insurance_fee,
        "is_fragile":       p.is_fragile,
        "do_not_bend":      p.do_not_bend,
        "notes":            p.notes,
        "status":           ev(p.status),
        "physical_location": ev(p.physical_location),
        "attempts":         p.attempts,
        "cod_locked":       p.cod_locked,
        "is_archived":      p.is_archived,
        "created_at":       p.created_at.isoformat() if p.created_at else None,
        "first_attempt_at": p.first_attempt_at.isoformat() if p.first_attempt_at else None,
        "delivered_at":     p.delivered_at.isoformat() if p.delivered_at else None,
    }
    if full or events:
        d["history"] = [{
            "old_status": h.old_status,
            "new_status": h.new_status,
            "reason":     h.reason,
            "note":       h.note,
            "user_id":    h.user_id,
            "created_at": h.created_at.isoformat() if h.created_at else None,
        } for h in (p.history or [])]
    return d


# ── Tracking ID generator ─────────────────────────────────────────────────────

def gen_tracking(db: Session, station_code: str) -> str:
    today  = datetime.now().strftime("%Y%m%d")
    prefix = f"{station_code}{today}"
    count  = db.query(Package).filter(
        Package.tracking_id.like(f"{prefix}%")
    ).count()
    return f"{prefix}{str(count + 1).zfill(4)}"


# ── State machine ─────────────────────────────────────────────────────────────

TRANSITIONS: dict[str, list[str]] = {
    "created":             ["assigned", "held_at_station", "lost"],
    "assigned":            ["out_for_delivery", "held_at_station", "created"],
    "out_for_delivery":    ["delivered", "failed", "rescheduled", "address_changed",
                            "waiting_for_client", "partially_delivered"],
    "failed":              ["out_for_delivery", "returned", "held_at_station",
                            "rescheduled", "lost"],
    "rescheduled":         ["out_for_delivery", "returned", "lost"],
    "waiting_for_client":  ["out_for_delivery", "returned", "lost"],
    "address_changed":     ["out_for_delivery", "returned"],
    "held_at_station":     ["assigned", "returned", "lost"],
    "partially_delivered": ["out_for_delivery", "delivered", "returned"],
    "delivered":           [],
    "returned":            [],
    "lost":                [],
    "sync_conflict":       [],
}

NEEDS_REASON: set[str] = {"failed", "returned", "rescheduled", "lost"}

STATUS_FR: dict[str, str] = {
    "created":             "Créé",
    "assigned":            "Assigné",
    "out_for_delivery":    "En livraison",
    "delivered":           "Livré",
    "failed":              "Échoué",
    "returned":            "Retourné",
    "rescheduled":         "Reprogrammé",
    "address_changed":     "Adresse modifiée",
    "waiting_for_client":  "Rappelé",
    "held_at_station":     "En station",
    "partially_delivered": "Partiellement livré",
    "lost":                "Perdu",
    "sync_conflict":       "Conflit",
}
