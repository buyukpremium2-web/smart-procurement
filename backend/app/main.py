from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
import os
import asyncio
import logging

from sqlalchemy import text

from app.core.config import settings
from app.core.database import engine, Base, AsyncSessionLocal
from app.api.v1.router import api_router
from app.api.v1.endpoints.sync import _pull_products, _pull_sales

logger = logging.getLogger("onec_sync")

# 1C avtomatik sinxron (scheduler) sozlamalari
ONEC_SYNC_ENABLED      = os.getenv("ONEC_SYNC_ENABLED", "1") == "1"
ONEC_SYNC_INTERVAL_MIN = int(os.getenv("ONEC_SYNC_INTERVAL_MIN", "5"))

# Global (butun Postgres bo'yicha) advisory-lock kaliti.
# Bir vaqtda FAQAT bitta instans/replika sync qilsin — shu bilan
# UPDATE'lar ustma-ust kelib qulf zanjiriga aylanmaydi.
_SYNC_LOCK_KEY = 915231


async def _run_one_sync():
    """Bitta sync aylanishi: global lock olib, 1C dan tovar+sotuv tortadi.
    Lock band bo'lsa (boshqa instans ishlayapti) - jimgina o'tkazib yuboradi."""
    async with AsyncSessionLocal() as db:
        locked = (await db.execute(text("SELECT pg_try_advisory_lock(:k)"),
                                   {"k": _SYNC_LOCK_KEY})).scalar()
        if not locked:
            logger.info("1C sync: boshqa instans band, aylanish o'tkazib yuborildi")
            return
        try:
            p = await _pull_products(db)
            s = await _pull_sales(db)
            logger.info("1C sync: products=%s sales=%s", p, s)
        except Exception as e:
            await db.rollback()
            # %r -> xato bo'sh bo'lsa ham turini ko'rsatadi (avval log bo'sh chiqardi)
            logger.warning("1C sync xato (ichki): %r", e)
        finally:
            try:
                await db.execute(text("SELECT pg_advisory_unlock(:k)"),
                                 {"k": _SYNC_LOCK_KEY})
            except Exception:
                pass


async def _onec_sync_loop():
    """Har N daqiqada 1C dan tovar+sotuvni o'zi tortib oladi.
    Har aylanish 180s bilan cheklangan - hech qachon cheksiz qotib qolmaydi."""
    await asyncio.sleep(30)  # app to'liq ko'tarilishini kutamiz
    while True:
        try:
            await asyncio.wait_for(_run_one_sync(), timeout=180)
        except asyncio.TimeoutError:
            logger.warning("1C sync: 180s dan oshdi, keyingi aylanishga o'tildi")
        except Exception as e:
            logger.warning("1C sync xato (tashqi): %r", e)
        await asyncio.sleep(ONEC_SYNC_INTERVAL_MIN * 60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    sync_task = None
    if ONEC_SYNC_ENABLED:
        sync_task = asyncio.create_task(_onec_sync_loop())
        logger.info("1C avtomatik sinxron yoqildi: har %s daqiqa", ONEC_SYNC_INTERVAL_MIN)

    yield

    if sync_task:
        sync_task.cancel()
        try:
            await sync_task
        except Exception:
            pass
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
