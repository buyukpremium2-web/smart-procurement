from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
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

# Frontend qidirish — Railway da backend/ build qilinadi
# index.html quyidagi joylarda bo'lishi mumkin
BASE = os.path.dirname(os.path.abspath(__file__))   # /app/app
CANDIDATES = [
    os.path.join(BASE, "static", "index.html"),           # /app/app/static/
    os.path.join(BASE, "..", "static", "index.html"),      # /app/static/
    "/app/static/index.html",
    "/app/frontend/src/index.html",
    "/app/frontend/index.html",
]

INDEX_FILE = None
for c in CANDIDATES:
    c = os.path.abspath(c)
    if os.path.isfile(c):
        INDEX_FILE = c
        break


@app.get("/health")
async def health():
    return {"status": "ok", "index_file": INDEX_FILE or "NOT FOUND"}


@app.get("/", include_in_schema=False)
async def root():
    if INDEX_FILE:
        return FileResponse(INDEX_FILE)
    return {"message": "API running", "docs": "/api/docs"}


@app.get("/{path:path}", include_in_schema=False)
async def spa(path: str):
    if path.startswith("api"):
        raise HTTPException(status_code=404)
    if INDEX_FILE:
        return FileResponse(INDEX_FILE)
    raise HTTPException(status_code=404)
