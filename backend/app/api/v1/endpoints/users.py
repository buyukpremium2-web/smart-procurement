from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional
from app.core.database import get_db
from app.core.security import get_current_user, require_roles, get_password_hash
from app.models.models import User, UserRole

router = APIRouter()


class UserCreate(BaseModel):
    username: str
    full_name: str
    password: str
    role: str = "seller"
    phone: Optional[str] = None
    telegram_id: Optional[int] = None


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    phone: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None


@router.get("/")
async def list_users(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin"))
):
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    users = result.scalars().all()
    return [
        {
            "id": str(u.id),
            "username": u.username,
            "full_name": u.full_name,
            "role": u.role.value if hasattr(u.role, 'value') else u.role,
            "phone": u.phone,
            "is_active": u.is_active,
            "telegram_id": u.telegram_id,
            "created_at": u.created_at.isoformat() if u.created_at else None,
        }
        for u in users
    ]


@router.post("/")
async def create_user(
    data: UserCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin"))
):
    # Username mavjudligini tekshir
    existing = await db.execute(select(User).where(User.username == data.username))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Bu username allaqachon mavjud")

    try:
        role_enum = UserRole(data.role)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Noto'g'ri rol: {data.role}")

    user = User(
        username=data.username,
        full_name=data.full_name,
        hashed_password=get_password_hash(data.password),
        role=role_enum,
        phone=data.phone,
        telegram_id=data.telegram_id,
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    return {
        "id": str(user.id),
        "username": user.username,
        "full_name": user.full_name,
        "role": user.role.value,
        "message": "Foydalanuvchi muvaffaqiyatli yaratildi"
    }


@router.patch("/{user_id}")
async def update_user(
    user_id: str,
    data: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin"))
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Foydalanuvchi topilmadi")

    if data.full_name is not None:
        user.full_name = data.full_name
    if data.phone is not None:
        user.phone = data.phone
    if data.is_active is not None:
        user.is_active = data.is_active
    if data.password:
        user.hashed_password = get_password_hash(data.password)
    if data.role:
        try:
            user.role = UserRole(data.role)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Noto'g'ri rol: {data.role}")

    await db.commit()
    return {"message": "Yangilandi", "id": str(user.id)}


@router.delete("/{user_id}")
async def deactivate_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin"))
):
    if str(current_user.id) == user_id:
        raise HTTPException(status_code=400, detail="O'zingizni o'chira olmaysiz")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Foydalanuvchi topilmadi")

    user.is_active = False
    await db.commit()
    return {"message": "Foydalanuvchi bloklandi"}


class TelegramUpdate(BaseModel):
    telegram_id: int


@router.patch("/{user_id}/telegram")
async def update_telegram_id(
    user_id: str,
    data: TelegramUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Foydalanuvchi o'z Telegram ID sini saqlaydi (bot orqali)"""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Foydalanuvchi topilmadi")

    # Faqat o'zini yoki admin
    if str(current_user.id) != user_id and (current_user.role.value if hasattr(current_user.role,'value') else current_user.role) != "admin":
        raise HTTPException(status_code=403, detail="Ruxsat yo'q")

    user.telegram_id = data.telegram_id
    await db.commit()
    return {"message": "Telegram ID saqlandi", "telegram_id": data.telegram_id}
