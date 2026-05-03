from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from database import get_db
from models import *
from routers.auth import get_current_user, require_role
from passlib.context import CryptContext

router = APIRouter()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

@router.get("/users")
async def list_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.superadmin))
):
    users = db.query(User).filter(
        User.station_id == current_user.station_id
    ).all()
    return [{
        "id": u.id,
        "full_name": u.full_name,
        "phone": u.phone,
        "role": u.role.value if hasattr(u.role, 'value') else u.role,
        "is_active": u.is_active,
        "last_login": u.last_login.isoformat() if u.last_login else None,
        "created_at": u.created_at.isoformat() if u.created_at else None,
    } for u in users]

@router.post("/users")
async def create_user(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.superadmin))
):
    body = await request.json()

    required = ["full_name", "phone", "role", "password"]
    for field in required:
        if not body.get(field):
            raise HTTPException(
                status_code=400,
                detail=f"Champ requis: {field}"
            )

    existing = db.query(User).filter(
        User.phone == body["phone"]
    ).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail="Ce numéro est déjà utilisé"
        )

    user = User(
        station_id=current_user.station_id,
        full_name=body["full_name"],
        phone=body["phone"],
        hashed_password=pwd_context.hash(body["password"]),
        role=body["role"],
        is_active=True
    )
    db.add(user)

    db.add(AuditLog(
        user_id=current_user.id,
        station_id=current_user.station_id,
        action="user_created",
        entity_type="user",
        entity_id=user.id,
        new_value={"full_name": user.full_name, "role": body["role"]}
    ))

    db.commit()
    db.refresh(user)
    return {
        "id": user.id,
        "full_name": user.full_name,
        "phone": user.phone,
        "role": user.role.value if hasattr(user.role, 'value') else user.role,
        "is_active": user.is_active
    }

@router.patch("/users/{user_id}/toggle")
async def toggle_user(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.superadmin))
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    if user.id == current_user.id:
        raise HTTPException(
            status_code=400,
            detail="Vous ne pouvez pas désactiver votre propre compte"
        )
    user.is_active = not user.is_active
    db.commit()
    return {"id": user.id, "is_active": user.is_active}

@router.post("/users/{user_id}/force-logout")
async def force_logout(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.superadmin))
):
    db.query(UserSession).filter(
        UserSession.user_id == user_id
    ).update({"is_active": False})
    db.commit()
    return {"success": True, "message": "Toutes les sessions ont été invalidées"}

@router.get("/stats")
async def get_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    from datetime import datetime, timezone
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    total_today = db.query(Package).filter(
        Package.station_id == current_user.station_id,
        Package.created_at >= today_start
    ).count()

    delivered_today = db.query(Package).filter(
        Package.station_id == current_user.station_id,
        Package.status == PackageStatusEnum.delivered,
        Package.delivered_at >= today_start
    ).count()

    out_for_delivery = db.query(Package).filter(
        Package.station_id == current_user.station_id,
        Package.status == PackageStatusEnum.out_for_delivery
    ).count()

    cod_today = db.query(Package).filter(
        Package.station_id == current_user.station_id,
        Package.status == PackageStatusEnum.delivered,
        Package.delivered_at >= today_start
    ).all()

    cod_total = sum(p.cod_amount for p in cod_today)

    return {
        "total_today": total_today,
        "delivered_today": delivered_today,
        "out_for_delivery": out_for_delivery,
        "cod_today": cod_total,
    }
    # Default wilaya pricing
DEFAULT_WILAYA_PRICES = {
    "Adrar": {"home": 700, "desk": 500},
    "Chlef": {"home": 500, "desk": 400},
    "Laghouat": {"home": 600, "desk": 500},
    "Oum El Bouaghi": {"home": 500, "desk": 400},
    "Batna": {"home": 500, "desk": 400},
    "Béjaïa": {"home": 500, "desk": 400},
    "Biskra": {"home": 550, "desk": 450},
    "Béchar": {"home": 700, "desk": 500},
    "Blida": {"home": 400, "desk": 350},
    "Bouira": {"home": 500, "desk": 400},
    "Tamanrasset": {"home": 800, "desk": 600},
    "Tébessa": {"home": 550, "desk": 450},
    "Tlemcen": {"home": 500, "desk": 400},
    "Tiaret": {"home": 500, "desk": 400},
    "Tizi Ouzou": {"home": 500, "desk": 400},
    "Alger": {"home": 400, "desk": 350},
    "Djelfa": {"home": 550, "desk": 450},
    "Jijel": {"home": 500, "desk": 400},
    "Sétif": {"home": 500, "desk": 400},
    "Saïda": {"home": 500, "desk": 400},
    "Skikda": {"home": 500, "desk": 400},
    "Sidi Bel Abbès": {"home": 500, "desk": 400},
    "Annaba": {"home": 500, "desk": 400},
    "Guelma": {"home": 500, "desk": 400},
    "Constantine": {"home": 450, "desk": 350},
    "Médéa": {"home": 450, "desk": 350},
    "Mostaganem": {"home": 500, "desk": 400},
    "M'Sila": {"home": 500, "desk": 400},
    "Mascara": {"home": 500, "desk": 400},
    "Ouargla": {"home": 650, "desk": 500},
    "Oran": {"home": 400, "desk": 350},
    "El Bayadh": {"home": 650, "desk": 500},
    "Illizi": {"home": 800, "desk": 600},
    "Bordj Bou Arréridj": {"home": 500, "desk": 400},
    "Boumerdès": {"home": 400, "desk": 350},
    "El Tarf": {"home": 500, "desk": 400},
    "Tindouf": {"home": 800, "desk": 600},
    "Tissemsilt": {"home": 550, "desk": 450},
    "El Oued": {"home": 650, "desk": 500},
    "Khenchela": {"home": 550, "desk": 450},
    "Souk Ahras": {"home": 550, "desk": 450},
    "Tipaza": {"home": 400, "desk": 350},
    "Mila": {"home": 500, "desk": 400},
    "Aïn Defla": {"home": 450, "desk": 350},
    "Naâma": {"home": 650, "desk": 500},
    "Aïn Témouchent": {"home": 500, "desk": 400},
    "Ghardaïa": {"home": 650, "desk": 500},
    "Relizane": {"home": 500, "desk": 400},
    "Timimoun": {"home": 750, "desk": 550},
    "Bordj Badji Mokhtar": {"home": 850, "desk": 650},
    "Ouled Djellal": {"home": 650, "desk": 500},
    "Béni Abbès": {"home": 750, "desk": 550},
    "In Salah": {"home": 800, "desk": 600},
    "In Guezzam": {"home": 850, "desk": 650},
    "Touggourt": {"home": 650, "desk": 500},
    "Djanet": {"home": 850, "desk": 650},
    "El M'Ghair": {"home": 650, "desk": 500},
    "El Meniaa": {"home": 700, "desk": 550},
}

@router.get("/wilaya-prices")
async def get_wilaya_prices(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return DEFAULT_WILAYA_PRICES

@router.patch("/wilaya-prices")
async def update_wilaya_prices(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.superadmin))
):
    body = await request.json()
    wilaya = body.get("wilaya")
    home = body.get("home")
    desk = body.get("desk")

    if not wilaya or home is None or desk is None:
        raise HTTPException(status_code=400, detail="Wilaya, home et desk requis")

    DEFAULT_WILAYA_PRICES[wilaya] = {"home": home, "desk": desk}

    db.add(AuditLog(
        user_id=current_user.id,
        station_id=current_user.station_id,
        action="wilaya_price_updated",
        entity_type="config",
        new_value={"wilaya": wilaya, "home": home, "desk": desk}
    ))
    db.commit()
    return {"success": True, "wilaya": wilaya, "home": home, "desk": desk}