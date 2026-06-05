from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    # App
    APP_NAME: str = "Smart AI Procurement System"
    DEBUG: bool = False

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://admin:secret123@localhost:5432/procurement_db"

    # Redis
    REDIS_URL: str = "redis://localhost:6379"

    # JWT
    SECRET_KEY: str = "supersecretkey_change_in_production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # Telegram
    TELEGRAM_BOT_TOKEN: str = ""

    # CORS
    ALLOWED_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://localhost:80",
    ]

    # AI Settings
    FORECAST_DAYS_AHEAD: int = 7
    SAFETY_STOCK_MULTIPLIER: float = 0.25

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
