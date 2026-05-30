@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    from app.models.models import User
    from app.core.security import get_password_hash
    from sqlalchemy import select, text
    
    async with AsyncSessionLocal() as db:
        # Qaysi DB ga ulanganini ko'rish
        result = await db.execute(text("SELECT current_user, current_database()"))
        row = result.fetchone()
        print(f"🔌 DB: user={row[0]}, database={row[1]}")
        
        result = await db.execute(select(User).where(User.username == "admin"))
        user = result.scalar_one_or_none()
        if user:
            # Parolni yangilash
            user.hashed_password = get_password_hash("Admin123")
            await db.commit()
            print(f"✅ Admin paroli yangilandi: Admin123")
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
            print("✅ Admin yaratildi: login=admin, parol=Admin123")
    
    yield
    await engine.dispose()
