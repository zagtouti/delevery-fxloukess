import os

# Database
DATABASE_URL = "postgresql://postgres:fxloukess123@localhost:5432/fxloukess"

# Security
SECRET_KEY = "fxloukess-secret-key-change-this-in-production"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 480  # 8 hours for all roles except driver

# Station
STATION_CODE = "ORA"  # Change to your station code
STATION_NAME = "PDEX Oran"

# Alerts
DRIVER_CASH_ALERT_THRESHOLD = 5000  # DZD
DRIVER_CASH_ALERT_HOURS = 48
MAX_DELIVERY_ATTEMPTS = 3
OTP_MAX_ATTEMPTS = 3
OTP_MAX_REQUESTS = 5
OTP_COOLDOWN_MINUTES = 2

# Archive
ARCHIVE_AFTER_DAYS = 90

# Storage
PHOTO_MAX_SIZE_KB = 500
PHOTO_ARCHIVE_MAX_SIZE_KB = 200
STORAGE_ALERT_THRESHOLD = 0.80  # 80%

# Printing
PRINT_BATCH_SIZE = 50
PRINT_JOB_TIMEOUT_SECONDS = 30

# Notifications
SMS_RETRY_ATTEMPTS = 3
SMS_RETRY_INTERVALS = [5, 15, 30]  # minutes
NOTIFICATION_SUCCESS_RATE_THRESHOLD = 0.80

# Shifts
SHIFTS = {
    "morning":   {"start": "06:00", "end": "14:00"},
    "afternoon": {"start": "14:00", "end": "22:00"},
    "night":     {"start": "22:00", "end": "06:00"},
}

# Petty cash
PETTY_CASH_LOW_THRESHOLD = 5000  # DZD

# Payouts
PAYOUT_SINGLE_ADMIN_LIMIT = 50000       # DZD - below this one admin confirms
PAYOUT_REGIONAL_APPROVAL_LIMIT = 200000 # DZD - above this regional manager needed
MAX_PAYOUTS_PER_AGENT_PER_HOUR = 3

# Roles
ROLES = [
    "superadmin",
    "regional_manager", 
    "frontdesk",
    "dispatch",
    "returns",
    "driver",
    "seller"
]

# Package physical locations
PHYSICAL_LOCATIONS = [
    "receiving",
    "shelf",
    "dispatch_bag",
    "with_driver",
    "returns_area",
    "unknown"
]

# Package statuses
PACKAGE_STATUSES = [
    "created",
    "assigned",
    "out_for_delivery",
    "delivered",
    "failed",
    "returned",
    "rescheduled",
    "address_changed",
    "waiting_for_client",
    "held_at_station",
    "partially_delivered",
    "lost",
    "sync_conflict"
]

# Colors per status
STATUS_COLORS = {
    "created":             "#3b82f6",
    "assigned":            "#8b5cf6",
    "out_for_delivery":    "#f97316",
    "delivered":           "#22c55e",
    "failed":              "#ef4444",
    "returned":            "#a855f7",
    "rescheduled":         "#eab308",
    "address_changed":     "#06b6d4",
    "waiting_for_client":  "#f59e0b",
    "held_at_station":     "#6b7280",
    "partially_delivered": "#84cc16",
    "lost":                "#1f2937",
    "sync_conflict":       "#dc2626",
}