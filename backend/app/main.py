from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.core.database import engine, Base, AsyncSessionLocal
from app.api.v1.router import api_router
from sqlalchemy import select, text

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    from app.models.models import User
    from app.core.security import get_password_hash
    
    async with AsyncSessionLocal() as db:
        result = await db.execute(text("SELECT current_user, current_database()"))
        row = result.fetchone()
        print(f"🔌 DB: user={row[0]}, database={row[1]}")
        
        result = await db.execute(select(User).where(User.username == "admin"))
        user = result.scalar_one_or_none()
        if user:
            user.hashed_password = get_password_hash("Admin123")
            await db.commit()
            print("✅ Admin paroli yangilandi: Admin123")
        else:
            admin = User(
                username="admin",
                full_name="Administrator",
                hashed_password=get_password_hash("Admin123"),
                role="admin",
                is_active=True
            )
            db.add(admin)
            await db.commit()
            print("✅ Admin yaratildi: Admin123")
    
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
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")

@app.get("/health")
async def health_check():
    return {"status": "ok", "version": "1.0.0"}
