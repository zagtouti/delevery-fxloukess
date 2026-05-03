from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from database import get_db
from models import User, UserSession, AuditLog, RoleEnum
from passlib.context import CryptContext
from jose import jwt
from config import SECRET_KEY, ALGORITHM
from datetime import datetime, timezone
import uuid
import hashlib

router = APIRouter()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)

def generate_token(user_id: str, role: str, station_id: str, device: str) -> str:
    payload = {
        "user_id":    user_id,
        "role":       role,
        "station_id": station_id,
        "device":     device,
        "issued_at":  str(datetime.now(timezone.utc))
    }
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")

def get_device_fingerprint(request: Request) -> str:
    raw = f"{request.headers.get('user-agent', '')}{request.client.host}"
    return hashlib.sha256(raw.encode()).hexdigest()

def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get("token") or request.headers.get("Authorization", "").replace("Bearer ", "")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")

    session = db.query(UserSession).filter(
        UserSession.token == token,
        UserSession.is_active == True
    ).first()

    if not session:
        raise HTTPException(status_code=401, detail="Session expired")

    device = get_device_fingerprint(request)
    if session.device_fingerprint and session.device_fingerprint != device:
        session.is_active = False
        db.commit()
        raise HTTPException(status_code=401, detail="Device mismatch - session invalidated")

    user = db.query(User).filter(User.id == payload["user_id"]).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")

    session.last_active = datetime.now(timezone.utc)
    db.commit()
    return user

def require_role(*roles):
    def checker(current_user: User = Depends(get_current_user)):
        if current_user.role not in roles:
            raise HTTPException(status_code=403, detail="Access denied")
        return current_user
    return checker

# ─────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────

@router.post("/login")
async def login(request: Request, db: Session = Depends(get_db)):
    body = await request.json()
    phone    = body.get("phone", "").strip()
    password = body.get("password", "").strip()

    if not phone or not password:
        raise HTTPException(status_code=400, detail="Phone and password required")

    user = db.query(User).filter(User.phone == phone).first()

    if not user or not verify_password(password, user.hashed_password):
        db.add(AuditLog(
            action="login_failed",
            entity_type="user",
            ip_address=request.client.host
        ))
        db.commit()
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is inactive")

    device = get_device_fingerprint(request)

    # Driver gets permanent session
    # All others get 8 hour session
    token = generate_token(user.id, user.role, user.station_id or "", device)

    session = UserSession(
        user_id=user.id,
        token=token,
        device_fingerprint=device,
        is_active=True
    )
    db.add(session)

    user.last_login = datetime.now(timezone.utc)

    db.add(AuditLog(
        user_id=user.id,
        station_id=user.station_id,
        action="login_success",
        entity_type="user",
        entity_id=user.id,
        ip_address=request.client.host
    ))
    db.commit()

    response = JSONResponse(content={
        "success": True,
        "role": user.role,
        "name": user.full_name,
        "token": token
    })
    response.set_cookie(
        key="token",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 365 if user.role == "driver" else 60 * 60 * 8
    )
    return response

@router.post("/logout")
async def logout(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get("token")
    if token:
        session = db.query(UserSession).filter(UserSession.token == token).first()
        if session:
            session.is_active = False
            db.commit()
    response = JSONResponse(content={"success": True})
    response.delete_cookie("token")
    return response

@router.post("/report-stolen")
async def report_stolen(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get("token")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")

    db.query(UserSession).filter(
        UserSession.user_id == payload["user_id"]
    ).update({"is_active": False})
    db.commit()

    response = JSONResponse(content={
        "success": True,
        "message": "All sessions invalidated. Contact your admin."
    })
    response.delete_cookie("token")
    return response

@router.get("/me")
async def me(current_user: User = Depends(get_current_user)):
    return {
        "id":         current_user.id,
        "name":       current_user.full_name,
        "phone":      current_user.phone,
        "role":       current_user.role,
        "station_id": current_user.station_id,
        "language":   current_user.language
    }