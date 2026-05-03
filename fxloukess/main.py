from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from contextlib import asynccontextmanager
from database import check_connection
import os

@asynccontextmanager
async def lifespan(app):
    check_connection()
    print("fxloukess server is running")
    yield

app = FastAPI(
    title="fxloukess",
    description="Delivery Station Management System",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for d in ["static", "static/css", "static/js", "templates", "photos", "prints"]:
    os.makedirs(d, exist_ok=True)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

def _html(path: str) -> HTMLResponse:
    with open(f"templates/{path}", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

@app.get("/")
async def root():
    return _html("login.html")

@app.get("/login")
async def login_page():
    return _html("login.html")

@app.get("/superadmin")
async def superadmin_page():
    return _html("superadmin.html")

@app.get("/frontdesk")
async def frontdesk_page():
    return _html("frontdesk.html")

@app.get("/dispatch")
async def dispatch_page():
    return _html("dispatch.html")

@app.get("/returns")
async def returns_page():
    return _html("returns.html")

@app.get("/driver")
async def driver_page():
    return _html("driver.html")

@app.get("/manager")
async def manager_page():
    return _html("superadmin.html")  # same UI, role-gated on backend

@app.get("/track")
async def track_page():
    return _html("track.html")

@app.get("/health")
async def health():
    return {"status": "ok", "app": "fxloukess"}

from routers import auth, packages, drivers, sellers, frontdesk, dispatch, returns, superadmin

app.include_router(auth.router,       prefix="/api/auth",       tags=["auth"])
app.include_router(packages.router,   prefix="/api/packages",   tags=["packages"])
app.include_router(drivers.router,    prefix="/api/drivers",    tags=["drivers"])
app.include_router(sellers.router,    prefix="/api/sellers",    tags=["sellers"])
app.include_router(frontdesk.router,  prefix="/api/frontdesk",  tags=["frontdesk"])
app.include_router(dispatch.router,   prefix="/api/dispatch",   tags=["dispatch"])
app.include_router(returns.router,    prefix="/api/returns",    tags=["returns"])
app.include_router(superadmin.router, prefix="/api/superadmin", tags=["superadmin"])

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
