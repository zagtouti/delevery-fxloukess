"""
routers/auth.py
Authentication: login, logout, me, stolen-device report.
Rate-limited login (10/min per IP via slowapi).
JWT stored in HttpOnly cookie (token is not returned in JSON payload).
"""
import hashlib
import logging
import secrets
import hmac
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from fastapi.responses import JSONResponse
from jose import jwt, JWTError
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from config import (
    SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES, DRIVER_TOKEN_EXPIRE_DAYS,
    LOGIN_RATE_LIMIT, COOKIE_SECURE, CSRF_PROTECT, COOKIE_SAMESITE, COOKIE_PATH,
)
from database import get_db
from models import AuditLog, RoleEnum, User, UserSession

logger = logging.getLogger("fxloukess.auth")
router = APIRouter()
limiter = Limiter(key_func=get_remote_address)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _extract_token(request: Request) -> str:
    auth_header = request.headers.get("Authorization", "").strip()
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    return (request.cookies.get("token") or "").strip()


def _validate_csrf(request: Request) -> None:
    if not CSRF_PROTECT:
        return

    # Enforce CSRF checks only for cookie-authenticated browser requests.
    token_cookie = (request.cookies.get("token") or "").strip()
    if not token_cookie:
        return

    csrf_cookie = (request.cookies.get("csrf_token") or "").strip()
    csrf_header = (request.headers.get("x-csrf-token") or "").strip()
    if not csrf_cookie or not csrf_header:
        raise HTTPException(status_code=403, detail="CSRF token requis")
    if not hmac.compare_digest(csrf_cookie, csrf_header):
        raise HTTPException(status_code=403, detail="CSRF token invalide")

# ── Helpers ───────────────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def _device_fp(request: Request) -> str:
    """Stable-ish fingerprint: prefer explicit device header, avoid volatile IP binding."""
    device_id = request.headers.get("x-device-id", "").strip()
    user_agent = request.headers.get("user-agent", "").strip()
    accept_lang = request.headers.get("accept-language", "").strip()
    raw = f"{device_id}|{user_agent}|{accept_lang}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _make_token(user: User) -> str:
    if user.role == RoleEnum.driver:
        expire = datetime.now(timezone.utc) + timedelta(days=DRIVER_TOKEN_EXPIRE_DAYS)
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "user_id":    user.id,
        "role":       user.role.value if hasattr(user.role, "value") else user.role,
        "station_id": user.station_id or "",
        "exp":        int(expire.timestamp()),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """FastAPI dependency — validates JWT + session; returns User."""
    token = _extract_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Non authentifié")

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Token invalide ou expiré")

    session = (
        db.query(UserSession)
        .filter(UserSession.token == token, UserSession.is_active == True)
        .first()
    )
    if not session:
        raise HTTPException(status_code=401, detail="Session expirée")

    # Device-fingerprint check (optional hardening — skip for drivers on mobile)
    user = db.query(User).filter(User.id == payload["user_id"]).first()
    if not user:
        raise HTTPException(status_code=401, detail="Utilisateur introuvable")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Compte désactivé")

    expected_fp = session.device_fingerprint
    if expected_fp and user.role != RoleEnum.driver and expected_fp != _device_fp(request):
        session.is_active = False
        db.commit()
        raise HTTPException(status_code=401, detail="Session invalide pour cet appareil")

    session.last_active = datetime.now(timezone.utc)
    db.commit()
    return user


def require_role(*roles: RoleEnum):
    """Dependency factory — 403 if user's role is not in *roles."""
    def checker(current_user: User = Depends(get_current_user)) -> User:
        role_val = current_user.role.value if hasattr(current_user.role, "value") else current_user.role
        allowed  = [r.value if hasattr(r, "value") else r for r in roles]
        if role_val not in allowed:
            raise HTTPException(status_code=403, detail="Accès refusé")
        return current_user
    return checker


def _audit(db: Session, *, action: str, request: Request,
           user_id: str | None = None, station_id: str | None = None,
           entity_type: str | None = None, entity_id: str | None = None,
           new_value: dict | None = None) -> None:
    db.add(AuditLog(
        user_id=user_id, station_id=station_id,
        action=action, entity_type=entity_type, entity_id=entity_id,
        new_value=new_value, ip_address=request.client.host,
    ))


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/login")
@limiter.limit(LOGIN_RATE_LIMIT)
async def login(request: Request, db: Session = Depends(get_db)):
    await request.app.state.limiter._check_request_limit(request, LOGIN_RATE_LIMIT)
    body = await request.json()
    phone    = (body.get("phone") or "").strip()
    password = (body.get("password") or "").strip()

    if not phone or not password:
        raise HTTPException(status_code=400, detail="Téléphone et mot de passe requis")

    user = db.query(User).filter(User.phone == phone).first()

    if not user or not verify_password(password, user.hashed_password):
        _audit(db, action="login_failed", request=request, entity_type="user")
        db.commit()
        logger.warning(f"Failed login for phone={phone} from {request.client.host}")
        raise HTTPException(status_code=401, detail="Identifiants incorrects")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Compte désactivé")

    token = _make_token(user)
    session = UserSession(
        user_id=user.id,
        token=token,
        device_fingerprint=_device_fp(request),
        is_active=True,
    )
    db.add(session)
    user.last_login = datetime.now(timezone.utc)
    _audit(db, action="login_success", request=request,
           user_id=user.id, station_id=user.station_id,
           entity_type="user", entity_id=user.id)
    db.commit()
    logger.info(f"Login OK: {user.phone} role={user.role}")

    role_val = user.role.value if hasattr(user.role, "value") else user.role
    response = JSONResponse(content={
        "success":    True,
        "role":       role_val,
        "name":       user.full_name,
        "station_id": user.station_id,
    })
    max_age = 60 * 60 * 24 * DRIVER_TOKEN_EXPIRE_DAYS if role_val == "driver" else 60 * ACCESS_TOKEN_EXPIRE_MINUTES
    response.set_cookie(
        key="token", value=token,
        httponly=True, secure=COOKIE_SECURE, samesite=COOKIE_SAMESITE, max_age=max_age, path=COOKIE_PATH,
    )
    csrf_token = secrets.token_urlsafe(24)
    response.set_cookie(
        key="csrf_token", value=csrf_token,
        httponly=False, secure=COOKIE_SECURE, samesite=COOKIE_SAMESITE, max_age=max_age, path=COOKIE_PATH,
        httponly=True, secure=COOKIE_SECURE, samesite="lax", max_age=max_age,
    )
    return response


@router.post("/logout")
async def logout(request: Request, db: Session = Depends(get_db)):
    _validate_csrf(request)
    token = _extract_token(request)
    if token:
        db.query(UserSession).filter(UserSession.token == token).update({"is_active": False})
        db.commit()
    response = JSONResponse(content={"success": True})
    response.delete_cookie("token", path=COOKIE_PATH)
    response.delete_cookie("csrf_token", path=COOKIE_PATH)
    return response


@router.post("/report-stolen")
async def report_stolen(request: Request, db: Session = Depends(get_db)):
    """Invalidate ALL sessions for the current user (lost/stolen device)."""
    _validate_csrf(request)
    token = _extract_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Non authentifié")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Token invalide")

    active_session = (
        db.query(UserSession)
        .filter(UserSession.token == token, UserSession.user_id == payload["user_id"], UserSession.is_active == True)
        .first()
    )
    if not active_session:
        raise HTTPException(status_code=401, detail="Session expirée")

    db.query(UserSession).filter(UserSession.user_id == payload["user_id"]).update({"is_active": False})
    _audit(db, action="stolen_device_report", request=request,
           user_id=payload["user_id"], entity_type="user", entity_id=payload["user_id"])
    db.commit()

    response = JSONResponse(content={"success": True, "message": "Toutes les sessions invalidées"})
    response.delete_cookie("token", path=COOKIE_PATH)
    response.delete_cookie("csrf_token", path=COOKIE_PATH)
    return response


@router.get("/me")
async def me(current_user: User = Depends(get_current_user)):
    return {
        "id":         current_user.id,
        "name":       current_user.full_name,
        "phone":      current_user.phone,
        "role":       current_user.role.value if hasattr(current_user.role, "value") else current_user.role,
        "station_id": current_user.station_id,
        "language":   current_user.language,
    }
