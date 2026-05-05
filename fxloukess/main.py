"""main.py — fxloukess v3"""
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from config import CORS_ORIGINS
from database import check_connection, create_tables

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("logs/fxloukess.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("fxloukess")

limiter = Limiter(key_func=get_remote_address)

for d in ["static/css", "static/js", "templates", "photos", "prints", "logs"]:
    os.makedirs(d, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("fxloukess v3 starting…")
    if check_connection():
        create_tables()
    else:
        logger.error("DB unreachable — tables NOT created")
    yield
    logger.info("fxloukess v3 shut down")


app = FastAPI(
    title="fxloukess",
    description="Delivery Station Management System v3",
    version="3.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory="static"), name="static")


def _html(filename: str) -> HTMLResponse:
    path = os.path.join("templates", filename)
    if not os.path.exists(path):
        return HTMLResponse(content=f"<h1>Missing: {filename}</h1>", status_code=404)
    with open(path, encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


# ── Pages ─────────────────────────────────────────────────────────────────────
@app.get("/",           include_in_schema=False) 
async def root():            return _html("login.html")
@app.get("/login",      include_in_schema=False)
async def login_page():      return _html("login.html")
@app.get("/superadmin", include_in_schema=False)
async def superadmin_page(): return _html("superadmin.html")
@app.get("/frontdesk",  include_in_schema=False)
async def frontdesk_page():  return _html("frontdesk.html")
@app.get("/dispatch",   include_in_schema=False)
async def dispatch_page():   return _html("dispatch.html")
@app.get("/returns",    include_in_schema=False)
async def returns_page():    return _html("returns.html")
@app.get("/driver",     include_in_schema=False)
async def driver_page():     return _html("driver.html")
@app.get("/manager",    include_in_schema=False)
async def manager_page():    return _html("superadmin.html")
@app.get("/track",      include_in_schema=False)
async def track_page():      return _html("track.html")


# ── Health ────────────────────────────────────────────────────────────────────
@app.get("/health", tags=["system"])
async def health():
    db_ok = check_connection()
    return {"status": "ok" if db_ok else "degraded", "db": db_ok, "version": "3.0.0"}


# ── Error handlers ────────────────────────────────────────────────────────────
@app.exception_handler(404)
async def not_found(_: Request, exc):
    return JSONResponse(status_code=404, content={"detail": "Ressource introuvable"})

@app.exception_handler(500)
async def server_error(request: Request, exc: Exception):
    logger.error(f"500 {request.url}: {exc}", exc_info=True)
    return JSONResponse(status_code=500, content={"detail": "Erreur serveur interne"})


# ── Routers ───────────────────────────────────────────────────────────────────
from routers import auth, dispatch, drivers, frontdesk, packages, returns, sellers, superadmin
from routers import reports, labels

app.include_router(auth.router,       prefix="/api/auth",       tags=["auth"])
app.include_router(packages.router,   prefix="/api/packages",   tags=["packages"])
app.include_router(drivers.router,    prefix="/api/drivers",    tags=["drivers"])
app.include_router(sellers.router,    prefix="/api/sellers",    tags=["sellers"])
app.include_router(frontdesk.router,  prefix="/api/frontdesk",  tags=["frontdesk"])
app.include_router(dispatch.router,   prefix="/api/dispatch",   tags=["dispatch"])
app.include_router(returns.router,    prefix="/api/returns",    tags=["returns"])
app.include_router(superadmin.router, prefix="/api/superadmin", tags=["superadmin"])
app.include_router(reports.router,    prefix="/api/reports",    tags=["reports"])
app.include_router(labels.router,     prefix="/api/labels",     tags=["labels"])

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
