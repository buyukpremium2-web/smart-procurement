from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.core.config import settings


engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_pre_ping=True,
    pool_size=20,
    max_overflow=30,
    pool_timeout=30,
    pool_recycle=1800,
    # ── QOTIB QOLISHGA QARSHI HIMOYA (asyncpg) ─────────────────────────
    # 11 soatlik "active UPDATE products" muammosining ildiz yechimi.
    # Har ulanishga Postgres o'zi quyidagi limitlarni majburlaydi (millisekundda):
    #   lock_timeout=10000  -> qatorni qulflashni 10s kutadi, ololmasa xato beradi
    #                          (endi cheksiz kutib qotib qolmaydi)
    #   statement_timeout=120000 -> bironta so'rov 120s dan oshsa avtomat bekor bo'ladi
    #   idle_in_transaction_session_timeout=60000 -> ochilib qolgan bekor
    #                          tranzaksiya 60s da yopiladi (qatorni bo'shatadi)
    # Normal 1C sync soniyalarda tugaydi, shuning uchun bu limitlar unga xalaqit bermaydi.
    connect_args={
        "server_settings": {
            "lock_timeout": "10000",
            "statement_timeout": "120000",
            "idle_in_transaction_session_timeout": "60000",
        }
    },
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
