from database import get_db
from sqlalchemy import text

db = next(get_db())

migrations = [
    "ALTER TABLE packages ALTER COLUMN seller_id DROP NOT NULL",
    "ALTER TABLE packages ADD COLUMN IF NOT EXISTS source VARCHAR(20) DEFAULT 'seller'",
    "ALTER TABLE packages ADD COLUMN IF NOT EXISTS walk_in_name VARCHAR(100)",
    "ALTER TABLE packages ADD COLUMN IF NOT EXISTS walk_in_phone VARCHAR(20)",
]

for sql in migrations:
    try:
        db.execute(text(sql))
        print(f"OK: {sql[:60]}")
    except Exception as e:
        print(f"SKIP: {e}")

db.commit()
print("\nMigration complete.")
