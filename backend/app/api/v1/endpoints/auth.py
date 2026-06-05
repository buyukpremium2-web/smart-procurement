from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.core.security import verify_password, create_access_token, get_current_user
from app.models.models import User
from pydantic import BaseModel
from typing import Optional

router = APIRouter()


def role_str(role):
    return role.value if hasattr(role, "value") else str(role)


class Token(BaseModel):
    access_token: str
    token_type: str
    user: dict


@router.post("/login", response_model=Token)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(User).where(User.username == form_data.username))
    user = result.scalar_one_or_none()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Login yoki parol noto'g'ri",
        )
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Foydalanuvchi bloklangan")

    token = create_access_token(data={"sub": str(user.id), "role": role_str(user.role)})
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": str(user.id),
            "username": user.username,
            "full_name": user.full_name,
            "role": role_str(user.role),
        }
    }


@router.get("/me")
async def get_me(current_user: User = Depends(get_current_user)):
    return {
        "id": str(current_user.id),
        "username": current_user.username,
        "full_name": current_user.full_name,
        "role": role_str(current_user.role),
        "phone": current_user.phone,
    }
