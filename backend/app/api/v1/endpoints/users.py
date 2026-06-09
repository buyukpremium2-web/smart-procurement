from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional
import secrets
import os
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


# ─── TELEGRAM ID (eski usul) ──────────────────────────
class TelegramUpdate(BaseModel):
    telegram_id: int


@router.patch("/{user_id}/telegram")
async def update_telegram_id(
    user_id: str,
    data: TelegramUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Foydalanuvchi topilmadi")
    role = current_user.role.value if hasattr(current_user.role, 'value') else current_user.role
    if str(current_user.id) != user_id and role != "admin":
        raise HTTPException(status_code=403, detail="Ruxsat yo'q")
    user.telegram_id = data.telegram_id
    await db.commit()
    return {"message": "Telegram ID saqlandi", "telegram_id": data.telegram_id}


# ─── INVITE HAVOLA (admin yaratadi) ───────────────────
@router.post("/{user_id}/invite-link")
async def generate_invite_link(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin"))
):
    """Admin: foydalanuvchi uchun maxsus botga ulanish havolasi yaratadi"""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Foydalanuvchi topilmadi")

    token = secrets.token_urlsafe(16)
    user.invite_token = token
    user.telegram_id = None  # eski bog'lanishni uzamiz
    await db.commit()

    bot_username = os.getenv("BOT_USERNAME", "BozorBuyukbot")
    link = f"https://t.me/{bot_username}?start={token}"

    return {
        "invite_link": link,
        "token": token,
        "user": user.full_name,
        "message": "Havola yaratildi"
    }


# ─── BOT: TOKEN ORQALI BOG'LANISH ─────────────────────
class TelegramConnect(BaseModel):
    invite_token: str
    telegram_id: int


@router.post("/connect-telegram")
async def connect_telegram(
    data: TelegramConnect,
    db: AsyncSession = Depends(get_db),
):
    """Bot: invite_token orqali foydalanuvchini Telegram ID ga bog'laydi"""
    # Token formatini tekshiramiz (faqat secrets.token_urlsafe formati)
    token = (data.invite_token or "").strip()
    if not token or len(token) < 16 or len(token) > 64:
        raise HTTPException(status_code=400, detail="Havola formati noto'g'ri")

    result = await db.execute(select(User).where(User.invite_token == token))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Havola yaroqsiz yoki ishlatilgan")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Foydalanuvchi bloklangan")

    # Bu telegram_id boshqa userda band emasligini tekshiramiz
    existing = await db.execute(
        select(User).where(User.telegram_id == data.telegram_id, User.id != user.id)
    )
    other = existing.scalar_one_or_none()
    if other:
        # Eski bog'lanishni uzamiz (bitta telegram = bitta user)
        other.telegram_id = None

    user.telegram_id = data.telegram_id
    user.invite_token = None  # bir martalik - darhol o'chadi
    await db.commit()

    return {
        "message": "Muvaffaqiyatli bog'landi",
        "user_id": str(user.id),
        "username": user.username,
        "full_name": user.full_name,
        "role": user.role.value if hasattr(user.role, 'value') else user.role,
    }


@router.get("/check-telegram/{telegram_id}")
async def check_telegram(
    telegram_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Bot: Telegram ID ro'yxatda bormi tekshiradi"""
    result = await db.execute(select(User).where(User.telegram_id == telegram_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        return {"allowed": False}
    return {
        "allowed": True,
        "user_id": str(user.id),
        "username": user.username,
        "full_name": user.full_name,
        "role": user.role.value if hasattr(user.role, 'value') else user.role,
    }


# ─── BOT: ADMIN USERNAME BO'YICHA HAVOLA YARATADI ─────
class InviteByUsername(BaseModel):
    admin_telegram_id: int   # so'rovchi admin (tekshiriladi)
    target_username: str     # kimga havola


@router.post("/invite-by-username")
async def invite_by_username(
    data: InviteByUsername,
    db: AsyncSession = Depends(get_db),
):
    """Bot: admin o'z telegramidan boshqa userga havola yaratadi"""
    # So'rovchi haqiqatan admin ekanligini tekshiramiz
    admin_r = await db.execute(select(User).where(User.telegram_id == data.admin_telegram_id))
    admin = admin_r.scalar_one_or_none()
    if not admin:
        raise HTTPException(status_code=403, detail="Siz ro'yxatda yo'qsiz")
    admin_role = admin.role.value if hasattr(admin.role, 'value') else admin.role
    if admin_role != "admin":
        raise HTTPException(status_code=403, detail="Faqat admin havola yarata oladi")

    # Maqsad foydalanuvchini topamiz
    target_r = await db.execute(select(User).where(User.username == data.target_username.lstrip("@")))
    target = target_r.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="Bunday username topilmadi")

    token = secrets.token_urlsafe(16)
    target.invite_token = token
    target.telegram_id = None
    await db.commit()

    bot_username = os.getenv("BOT_USERNAME", "BozorBuyukbot")
    link = f"https://t.me/{bot_username}?start={token}"

    return {
        "invite_link": link,
        "target": target.full_name,
        "username": target.username,
        "role": target.role.value if hasattr(target.role, 'value') else target.role,
    }


@router.get("/list-for-bot/{admin_telegram_id}")
async def list_for_bot(
    admin_telegram_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Bot: admin uchun foydalanuvchilar ro'yxati (havola yaratish uchun)"""
    admin_r = await db.execute(select(User).where(User.telegram_id == admin_telegram_id))
    admin = admin_r.scalar_one_or_none()
    if not admin:
        raise HTTPException(status_code=403, detail="Ro'yxatda yo'qsiz")
    admin_role = admin.role.value if hasattr(admin.role, 'value') else admin.role
    if admin_role != "admin":
        raise HTTPException(status_code=403, detail="Faqat admin")

    result = await db.execute(select(User).order_by(User.full_name))
    return [
        {
            "username": u.username,
            "full_name": u.full_name,
            "role": u.role.value if hasattr(u.role, 'value') else u.role,
            "connected": u.telegram_id is not None,
        }
        for u in result.scalars().all()
    ]
