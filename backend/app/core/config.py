from pydantic_settings import BaseSettings
from typing import List
import secrets
import os


class Settings(BaseSettings):
    # App
    APP_NAME: str = "Buyuk Premium ERP"
    DEBUG: bool = False

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://admin:secret123@localhost:5432/procurement_db"

    # Redis
    REDIS_URL: str = "redis://localhost:6379"

    # JWT - SECRET_KEY env dan olinadi, bo'lmasa random (har restart o'zgaradi)
    SECRET_KEY: str = os.getenv("SECRET_KEY") or secrets.token_urlsafe(48)
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 12  # 12 soat

    # Telegram
    TELEGRAM_BOT_TOKEN: str = ""
    BOT_USERNAME: str = "BozorBuyukbot"

    # Bot internal API key (pending-telegram himoyasi uchun)
    BOT_API_KEY: str = os.getenv("BOT_API_KEY", "buyuk-premium-bot-secret-2026")

    # AI Settings
    FORECAST_DAYS_AHEAD: int = 7
    SAFETY_STOCK_MULTIPLIER: float = 0.25

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"


settings = Settings()
