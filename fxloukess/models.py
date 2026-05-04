"""
models.py — All SQLAlchemy ORM models for fxloukess.
Single source of truth. Every table, enum, and relationship defined here.
"""
from __future__ import annotations
import enum
import uuid

from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, Enum, Float,
    ForeignKey, Integer, JSON, String, Text,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

Base = declarative_base()


def _uuid() -> str:
    return str(uuid.uuid4())


# ─────────────────────────── ENUMS ──────────────────────────────────────────

class RoleEnum(str, enum.Enum):
    superadmin       = "superadmin"
    regional_manager = "regional_manager"
    frontdesk        = "frontdesk"
    dispatch         = "dispatch"
    returns          = "returns"
    driver           = "driver"
    seller           = "seller"


class PackageStatusEnum(str, enum.Enum):
    created             = "created"
    assigned            = "assigned"
    out_for_delivery    = "out_for_delivery"
    delivered           = "delivered"
    failed              = "failed"
    returned            = "returned"
    rescheduled         = "rescheduled"
    address_changed     = "address_changed"
    waiting_for_client  = "waiting_for_client"
    held_at_station     = "held_at_station"
    partially_delivered = "partially_delivered"
    lost                = "lost"
    sync_conflict       = "sync_conflict"


class PhysicalLocationEnum(str, enum.Enum):
    receiving    = "receiving"
    shelf        = "shelf"
    dispatch_bag = "dispatch_bag"
    with_driver  = "with_driver"
    returns_area = "returns_area"
    unknown      = "unknown"


class LedgerEntryTypeEnum(str, enum.Enum):
    cod_credit         = "cod_credit"
    delivery_fee_debit = "delivery_fee_debit"
    return_fee_debit   = "return_fee_debit"
    manual_adjustment  = "manual_adjustment"
    payout             = "payout"
    insurance_credit   = "insurance_credit"
    compensation       = "compensation"


class AlertSeverityEnum(str, enum.Enum):
    low      = "low"
    medium   = "medium"
    high     = "high"
    critical = "critical"


class ShiftTypeEnum(str, enum.Enum):
    morning   = "morning"
    afternoon = "afternoon"
    night     = "night"


class TransferStatusEnum(str, enum.Enum):
    pending    = "pending"
    in_transit = "in_transit"
    confirmed  = "confirmed"
    disputed   = "disputed"


class DisputeStatusEnum(str, enum.Enum):
    open          = "open"
    investigating = "investigating"
    resolved      = "resolved"
    closed        = "closed"


class PrintJobStatusEnum(str, enum.Enum):
    queued     = "queued"
    generating = "generating"
    ready      = "ready"
    failed     = "failed"


# ─────────────────────────── STATIONS ───────────────────────────────────────

class Station(Base):
    __tablename__ = "stations"

    id         = Column(String, primary_key=True, default=_uuid)
    code       = Column(String(10),  unique=True, nullable=False)
    name       = Column(String(100), nullable=False)
    wilaya     = Column(String(50),  nullable=False)
    address    = Column(Text)
    phone      = Column(String(20))
    is_active  = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ─────────────────────────── USERS & SESSIONS ───────────────────────────────

class User(Base):
    __tablename__ = "users"

    id              = Column(String, primary_key=True, default=_uuid)
    station_id      = Column(String, ForeignKey("stations.id"), nullable=True)
    full_name       = Column(String(100), nullable=False)
    phone           = Column(String(20),  unique=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    pin             = Column(String, nullable=True)   # drivers only
    role            = Column(Enum(RoleEnum), nullable=False)
    is_active       = Column(Boolean, default=True)
    language        = Column(String(5), default="fr")
    created_at      = Column(DateTime(timezone=True), server_default=func.now())
    last_login      = Column(DateTime(timezone=True), nullable=True)

    station  = relationship("Station")
    sessions = relationship("UserSession", back_populates="user",
                            cascade="all, delete-orphan")


class UserSession(Base):
    __tablename__ = "user_sessions"

    id                 = Column(String, primary_key=True, default=_uuid)
    user_id            = Column(String, ForeignKey("users.id"), nullable=False)
    token              = Column(String, unique=True, nullable=False)
    device_fingerprint = Column(String, nullable=True)
    created_at         = Column(DateTime(timezone=True), server_default=func.now())
    last_active        = Column(DateTime(timezone=True), server_default=func.now())
    is_active          = Column(Boolean, default=True)

    user = relationship("User", back_populates="sessions")


# ─────────────────────────── SHIFTS ─────────────────────────────────────────

class Shift(Base):
    __tablename__ = "shifts"

    id         = Column(String, primary_key=True, default=_uuid)
    station_id = Column(String, ForeignKey("stations.id"), nullable=False)
    shift_type = Column(Enum(ShiftTypeEnum), nullable=False)
    opened_by  = Column(String, ForeignKey("users.id"), nullable=False)
    closed_by  = Column(String, ForeignKey("users.id"), nullable=True)
    opened_at  = Column(DateTime(timezone=True), server_default=func.now())
    closed_at  = Column(DateTime(timezone=True), nullable=True)
    is_closed  = Column(Boolean, default=False)
    notes      = Column(Text, nullable=True)


# ─────────────────────────── SELLERS ────────────────────────────────────────

class Seller(Base):
    __tablename__ = "sellers"

    id            = Column(String, primary_key=True, default=_uuid)
    station_id    = Column(String, ForeignKey("stations.id"), nullable=False)
    user_id       = Column(String, ForeignKey("users.id"), nullable=True)
    full_name     = Column(String(100), nullable=False)
    business_name = Column(String(100), nullable=True)
    phone         = Column(String(20), unique=True, nullable=False)
    wilaya        = Column(String(50), nullable=False)
    address       = Column(Text, nullable=True)
    id_number     = Column(String(50), nullable=True)
    bank_account  = Column(String(100), nullable=True)
    pricing_tier  = Column(String(50), default="standard")
    is_active     = Column(Boolean, default=True)
    language      = Column(String(5), default="fr")
    created_at    = Column(DateTime(timezone=True), server_default=func.now())

    packages       = relationship("Package", back_populates="seller")
    ledger_entries = relationship("SellerLedgerEntry", back_populates="seller",
                                  cascade="all, delete-orphan")


class SellerLedgerEntry(Base):
    __tablename__ = "seller_ledger_entries"

    id         = Column(String, primary_key=True, default=_uuid)
    seller_id  = Column(String, ForeignKey("sellers.id"), nullable=False)
    package_id = Column(String, ForeignKey("packages.id"), nullable=True)
    entry_type = Column(Enum(LedgerEntryTypeEnum), nullable=False)
    amount     = Column(Float, nullable=False)
    note       = Column(Text, nullable=False)
    created_by = Column(String, ForeignKey("users.id"), nullable=False)
    shift_id   = Column(String, ForeignKey("shifts.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    seller = relationship("Seller", back_populates="ledger_entries")


# ─────────────────────────── DRIVERS ────────────────────────────────────────

class Driver(Base):
    __tablename__ = "drivers"

    id         = Column(String, primary_key=True, default=_uuid)
    station_id = Column(String, ForeignKey("stations.id"), nullable=False)
    user_id    = Column(String, ForeignKey("users.id"), nullable=False)
    full_name  = Column(String(100), nullable=False)
    phone      = Column(String(20),  nullable=False)
    wilaya     = Column(String(50),  nullable=False)
    is_active  = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    packages  = relationship("Package", back_populates="driver")
    cash_logs = relationship("DriverCashLog", back_populates="driver",
                             cascade="all, delete-orphan")


class DriverCashLog(Base):
    __tablename__ = "driver_cash_logs"

    id            = Column(String, primary_key=True, default=_uuid)
    driver_id     = Column(String, ForeignKey("drivers.id"), nullable=False)
    package_id    = Column(String, ForeignKey("packages.id"), nullable=True)
    action        = Column(String(50), nullable=False)
    amount        = Column(Float, nullable=False)
    old_balance   = Column(Float, nullable=False)
    new_balance   = Column(Float, nullable=False)
    confirmed_by  = Column(String, ForeignKey("users.id"), nullable=True)
    shift_id      = Column(String, ForeignKey("shifts.id"), nullable=True)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())

    driver = relationship("Driver", back_populates="cash_logs")


# ─────────────────────────── PACKAGES ───────────────────────────────────────

class Package(Base):
    __tablename__ = "packages"

    id          = Column(String, primary_key=True, default=_uuid)
    tracking_id = Column(String(30), unique=True, nullable=False)
    station_id  = Column(String, ForeignKey("stations.id"), nullable=False)
    seller_id   = Column(String, ForeignKey("sellers.id"), nullable=True)
    driver_id   = Column(String, ForeignKey("drivers.id"), nullable=True)
    shift_id    = Column(String, ForeignKey("shifts.id"), nullable=True)

    # Walk-in sender (no seller account)
    source        = Column(String(20), default="seller")   # "seller" | "walk_in"
    walk_in_name  = Column(String(100), nullable=True)
    walk_in_phone = Column(String(20),  nullable=True)

    # Recipient
    recipient_name   = Column(String(100), nullable=False)
    recipient_phone  = Column(String(20),  nullable=False)
    recipient_phone2 = Column(String(20),  nullable=True)
    wilaya           = Column(String(50),  nullable=False)
    commune          = Column(String(50),  nullable=False)
    address          = Column(Text, nullable=False)

    # Product
    description   = Column(Text,  nullable=False)
    weight        = Column(Float, nullable=True)
    cod_amount    = Column(Float, nullable=False)
    declared_value = Column(Float, nullable=True)
    insurance_fee  = Column(Float, nullable=True)
    is_fragile     = Column(Boolean, default=False)
    do_not_bend    = Column(Boolean, default=False)
    notes          = Column(Text, nullable=True)

    # Status
    status            = Column(Enum(PackageStatusEnum),
                               default=PackageStatusEnum.created)
    physical_location = Column(Enum(PhysicalLocationEnum),
                               default=PhysicalLocationEnum.receiving)
    attempts  = Column(Integer, default=0)
    cod_locked = Column(Boolean, default=False)

    # Timestamps
    created_at       = Column(DateTime(timezone=True), server_default=func.now())
    first_attempt_at = Column(DateTime(timezone=True), nullable=True)
    delivered_at     = Column(DateTime(timezone=True), nullable=True)
    archived_at      = Column(DateTime(timezone=True), nullable=True)
    is_archived      = Column(Boolean, default=False)

    seller   = relationship("Seller", back_populates="packages")
    driver   = relationship("Driver", back_populates="packages")
    history  = relationship("PackageHistory", back_populates="package",
                            cascade="all, delete-orphan",
                            order_by="PackageHistory.created_at")
    proof    = relationship("DeliveryProof", back_populates="package",
                            cascade="all, delete-orphan")
    disputes = relationship("Dispute", back_populates="package",
                            cascade="all, delete-orphan")


class PackageHistory(Base):
    __tablename__ = "package_history"

    id         = Column(String, primary_key=True, default=_uuid)
    package_id = Column(String, ForeignKey("packages.id"), nullable=False)
    user_id    = Column(String, ForeignKey("users.id"), nullable=False)
    shift_id   = Column(String, ForeignKey("shifts.id"), nullable=True)
    old_status = Column(String, nullable=True)
    new_status = Column(String, nullable=False)
    reason     = Column(Text, nullable=True)
    note       = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    package = relationship("Package", back_populates="history")


class DeliveryProof(Base):
    __tablename__ = "delivery_proofs"

    id         = Column(String, primary_key=True, default=_uuid)
    package_id = Column(String, ForeignKey("packages.id"), nullable=False)
    driver_id  = Column(String, ForeignKey("drivers.id"), nullable=False)
    proof_type = Column(String(20), nullable=False)   # "photo" | "otp" | "signature"
    otp_code   = Column(String(10), nullable=True)
    photo_path = Column(String, nullable=True)
    gps_lat    = Column(Float, nullable=True)
    gps_lng    = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    package = relationship("Package", back_populates="proof")


# ─────────────────────────── TRANSFERS ──────────────────────────────────────

class Transfer(Base):
    __tablename__ = "transfers"

    id             = Column(String, primary_key=True, default=_uuid)
    transfer_code  = Column(String(30), unique=True, nullable=False)
    origin_station = Column(String, ForeignKey("stations.id"), nullable=False)
    dest_station   = Column(String, ForeignKey("stations.id"), nullable=False)
    transport_name = Column(String(100), nullable=True)
    status         = Column(Enum(TransferStatusEnum),
                            default=TransferStatusEnum.pending)
    created_by     = Column(String, ForeignKey("users.id"), nullable=False)
    confirmed_by   = Column(String, ForeignKey("users.id"), nullable=True)
    created_at     = Column(DateTime(timezone=True), server_default=func.now())
    confirmed_at   = Column(DateTime(timezone=True), nullable=True)

    items = relationship("TransferItem", back_populates="transfer",
                         cascade="all, delete-orphan")


class TransferItem(Base):
    __tablename__ = "transfer_items"

    id          = Column(String, primary_key=True, default=_uuid)
    transfer_id = Column(String, ForeignKey("transfers.id"), nullable=False)
    package_id  = Column(String, ForeignKey("packages.id"), nullable=False)
    scanned     = Column(Boolean, default=False)
    scanned_at  = Column(DateTime(timezone=True), nullable=True)

    transfer = relationship("Transfer", back_populates="items")


# ─────────────────────────── DISPUTES ───────────────────────────────────────

class Dispute(Base):
    __tablename__ = "disputes"

    id              = Column(String, primary_key=True, default=_uuid)
    package_id      = Column(String, ForeignKey("packages.id"), nullable=False)
    opened_by       = Column(String, ForeignKey("users.id"), nullable=False)
    assigned_to     = Column(String, ForeignKey("users.id"), nullable=True)
    dispute_type    = Column(String(50), nullable=False)
    description     = Column(Text, nullable=False)
    status          = Column(Enum(DisputeStatusEnum),
                             default=DisputeStatusEnum.open)
    resolution_note = Column(Text, nullable=True)
    resolved_by     = Column(String, ForeignKey("users.id"), nullable=True)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())
    resolved_at     = Column(DateTime(timezone=True), nullable=True)

    package = relationship("Package", back_populates="disputes")


# ─────────────────────────── ALERTS ─────────────────────────────────────────

class Alert(Base):
    __tablename__ = "alerts"

    id              = Column(String, primary_key=True, default=_uuid)
    station_id      = Column(String, ForeignKey("stations.id"), nullable=False)
    severity        = Column(Enum(AlertSeverityEnum), nullable=False)
    alert_type      = Column(String(50), nullable=False)
    title           = Column(String(200), nullable=False)
    description     = Column(Text, nullable=True)
    reference_id    = Column(String, nullable=True)
    is_resolved     = Column(Boolean, default=False)
    resolved_by     = Column(String, ForeignKey("users.id"), nullable=True)
    resolved_at     = Column(DateTime(timezone=True), nullable=True)
    resolution_note = Column(Text, nullable=True)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())
    sla_deadline    = Column(DateTime(timezone=True), nullable=True)


# ─────────────────────────── PETTY CASH ─────────────────────────────────────

class PettyCashEntry(Base):
    __tablename__ = "petty_cash_entries"

    id         = Column(String, primary_key=True, default=_uuid)
    station_id = Column(String, ForeignKey("stations.id"), nullable=False)
    shift_id   = Column(String, ForeignKey("shifts.id"), nullable=True)
    category   = Column(String(50), nullable=False)
    amount     = Column(Float, nullable=False)
    note       = Column(Text, nullable=False)
    photo_path = Column(String, nullable=True)
    created_by = Column(String, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ─────────────────────────── AUDIT LOG ──────────────────────────────────────

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id          = Column(String, primary_key=True, default=_uuid)
    user_id     = Column(String, ForeignKey("users.id"), nullable=True)
    station_id  = Column(String, ForeignKey("stations.id"), nullable=True)
    shift_id    = Column(String, ForeignKey("shifts.id"), nullable=True)
    action      = Column(String(100), nullable=False)
    entity_type = Column(String(50),  nullable=True)
    entity_id   = Column(String, nullable=True)
    old_value   = Column(JSON, nullable=True)
    new_value   = Column(JSON, nullable=True)
    ip_address  = Column(String(50), nullable=True)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())


# ─────────────────────────── PRINT JOBS ─────────────────────────────────────

class PrintJob(Base):
    __tablename__ = "print_jobs"

    id           = Column(String, primary_key=True, default=_uuid)
    requested_by = Column(String, ForeignKey("users.id"), nullable=False)
    job_type     = Column(String(50), nullable=False)
    status       = Column(Enum(PrintJobStatusEnum),
                          default=PrintJobStatusEnum.queued)
    file_path    = Column(String, nullable=True)
    package_ids  = Column(JSON, nullable=True)
    error        = Column(Text, nullable=True)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())
    ready_at     = Column(DateTime(timezone=True), nullable=True)
