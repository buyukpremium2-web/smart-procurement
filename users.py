from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional
from pydantic import BaseModel

from app.core.database import get_db
from app.core.security import get_current_user, require_roles, get_password_hash
from app.models.models import User

router = APIRouter()


class UserCreate(BaseModel):
    username: str
    full_name: str
    password: str
    role: str = "seller"
    phone: Optional[str] = None


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
            "role": u.role,
            "phone": u.phone,
            "is_active": u.is_active,
        }
        for u in users
    ]


@router.post("/")
async def create_user(
    data: UserCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin"))
):
    result = await db.execute(select(User).where(User.username == data.username))
    existing = result.scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail="Bu username allaqachon mavjud")

    user = User(
        username=data.username,
        full_name=data.full_name,
        hashed_password=get_password_hash(data.password),
        role=data.role,
        phone=data.phone,
        is_active=True,
    )
    db.add(user)
    await db.commit()
    return {"message": "Foydalanuvchi yaratildi", "id": str(user.id)}


@router.patch("/{user_id}/toggle")
async def toggle_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin"))
):
    from uuid import UUID
    result = await db.execute(select(User).where(User.id == UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Foydalanuvchi topilmadi")
    user.is_active = not user.is_active
    await db.commit()
    status = "faollashtirildi" if user.is_active else "bloklandi"
    return {"message": f"Foydalanuvchi {status}", "is_active": user.is_active}
