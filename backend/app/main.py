from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
import os

from app.core.config import settings
from app.core.database import engine, Base
from app.api.v1.router import api_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


app = FastAPI(
    title="Smart AI Procurement System",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")

# Frontend papkasini qidirish — barcha mumkin bo'lgan joylar
BASE = os.path.dirname(file)
POSSIBLE = [
    "/app/frontend/src",          # Railway: frontend/src/index.html
    "/app/frontend",              # Railway: frontend/index.html
    os.path.join(BASE, "..", "..", "frontend", "src"),
    os.path.join(BASE, "..", "..", "frontend"),
    os.path.join(BASE, "..", "frontend", "src"),
    os.path.join(BASE, "..", "frontend"),
]

STATIC_DIR = None
for d in POSSIBLE:
    d = os.path.abspath(d)
    if os.path.isfile(os.path.join(d, "index.html")):
        STATIC_DIR = d
        break


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "frontend_dir": STATIC_DIR or "NOT FOUND",
        "searched": [os.path.abspath(d) for d in POSSIBLE],
    }


@app.get("/", include_in_schema=False)
async def root():
    if STATIC_DIR:
        return FileResponse(os.path.join(STATIC_DIR, "index.html"))
    return {"message": "API is running. Frontend not found.", "docs": "/api/docs"}


@app.get("/{path:path}", include_in_schema=False)
async def spa(path: str):
    if path.startswith("api/") or path.startswith("api"):
        raise HTTPException(status_code=404)
    if STATIC_DIR:
        return FileResponse(os.path.join(STATIC_DIR, "index.html"))
    raise HTTPException(status_code=404)
