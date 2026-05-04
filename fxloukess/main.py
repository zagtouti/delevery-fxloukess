"""
main.py — FastAPI application entry point.
- Loads all routers
- Global error handlers (400, 401, 403, 404, 422, 500)
- CORS
- Rate limiting via slowapi
- Serves HTML pages for each role
"""
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

from database import check_connection, create_tables

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("logs/fxloukess.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("fxloukess")

# ── Rate limiter ──────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address)

# ── Directories ───────────────────────────────────────────────────────────────
for d in ["static/css", "static/js", "templates", "photos", "prints", "logs"]:
    os.makedirs(d, exist_ok=True)


# ── Lifespan ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting fxloukess…")
    if check_connection():
        create_tables()
    else:
        logger.error("Database unreachable — tables NOT created")
    yield
    logger.info("fxloukess shut down")


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="fxloukess",
    description="Delivery Station Management System",
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],        # tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")


# ── HTML helpers ──────────────────────────────────────────────────────────────
def _html(filename: str) -> HTMLResponse:
    path = os.path.join("templates", filename)
    if not os.path.exists(path):
        return HTMLResponse(content=f"<h1>Page not found: {filename}</h1>", status_code=404)
    with open(path, encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


# ── Page routes ───────────────────────────────────────────────────────────────
@app.get("/",          include_in_schema=False) 
async def root():          return _html("login.html")

@app.get("/login",     include_in_schema=False)
async def login_page():    return _html("login.html")

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
    from database import check_connection
    db_ok = check_connection()
    return {"status": "ok" if db_ok else "degraded", "db": db_ok, "app": "fxloukess"}


# ── Global error handlers ─────────────────────────────────────────────────────
@app.exception_handler(404)
async def not_found(_: Request, exc):
    return JSONResponse(status_code=404, content={"detail": "Ressource introuvable"})

@app.exception_handler(500)
async def server_error(request: Request, exc: Exception):
    logger.error(f"500 on {request.url}: {exc}", exc_info=True)
    return JSONResponse(status_code=500, content={"detail": "Erreur serveur interne"})


# ── API routers ───────────────────────────────────────────────────────────────
from routers import auth, dispatch, drivers, frontdesk, packages, returns, sellers, superadmin

app.include_router(auth.router,       prefix="/api/auth",       tags=["auth"])
app.include_router(packages.router,   prefix="/api/packages",   tags=["packages"])
app.include_router(drivers.router,    prefix="/api/drivers",    tags=["drivers"])
app.include_router(sellers.router,    prefix="/api/sellers",    tags=["sellers"])
app.include_router(frontdesk.router,  prefix="/api/frontdesk",  tags=["frontdesk"])
app.include_router(dispatch.router,   prefix="/api/dispatch",   tags=["dispatch"])
app.include_router(returns.router,    prefix="/api/returns",    tags=["returns"])
app.include_router(superadmin.router, prefix="/api/superadmin", tags=["superadmin"])


# ── Dev entry point ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
