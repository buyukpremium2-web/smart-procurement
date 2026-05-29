from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from contextlib import asynccontextmanager
from app.core.config import settings
from app.core.database import engine, Base, AsyncSessionLocal
from app.api.v1.router import api_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup - jadvallar yaratish
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # Admin user yaratish
    from app.models.models import User
    from app.core.security import get_password_hash
    from sqlalchemy import select
    
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.username == "admin"))
        if not result.scalar_one_or_none():
            admin = User(
                username="admin",
                full_name="Administrator",
                hashed_password=get_password_hash("Admin123"),
                role="admin",
                is_active=True
            )
            db.add(admin)
            await db.commit()
            print("✅ Admin yaratildi: login=admin, parol=Admin123")
    
    yield
    # Shutdown
    await engine.dispose()

app = FastAPI(
    title="Smart AI Procurement System",
    description="Multi-role ERP system for fruit & vegetable stores with AI forecasting",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes
app.include_router(api_router, prefix="/api/v1")

@app.get("/health")
async def health_check():
    return {"status": "ok", "version": "1.0.0"}
