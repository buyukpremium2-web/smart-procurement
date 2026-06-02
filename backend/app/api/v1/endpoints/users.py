from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.core.security import get_current_user, require_roles
from app.models.models import User

router = APIRouter()

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
            "telegram_id": u.telegram_id,
        }
        for u in users
    ]
