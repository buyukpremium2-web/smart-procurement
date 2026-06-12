"""
Qurilma tasdiqlash tizimi:
- Foydalanuvchi yangi kompyuter/telefondan kirsa - admin tasdiqlashi kerak
- Admin Telegram orqali tasdiqlaydi
- Tasdiqlangan qurilma keyingi safar so'ramaydi
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime
from typing import Optional
from pydantic import BaseModel
from uuid import UUID
import secrets
import random

from app.core.database import get_db
from app.core.security import get_current_user, require_roles
from app.models.models import DeviceApproval, User, Notification

router = APIRouter()


def gen_approval_code():
    """6 belgili kod - admin uchun (1234AB)"""
    return ''.join(random.choices('0123456789ABCDEFGHJKLMNPQRSTUVWXYZ', k=6))


class DeviceCheckRequest(BaseModel):
    device_id: str
    device_info: Optional[str] = None


class DeviceRequestApproval(BaseModel):
    device_id: str
    device_info: Optional[str] = None


@router.post("/check")
async def check_device(
    data: DeviceCheckRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Qurilma tasdiqlanganmi tekshiradi"""
    if not data.device_id or len(data.device_id) < 16:
        raise HTTPException(status_code=400, detail="Noto'g'ri device_id")

    r = await db.execute(
        select(DeviceApproval).where(
            DeviceApproval.device_id == data.device_id,
            DeviceApproval.user_id == current_user.id
        )
    )
    device = r.scalar_one_or_none()

    if not device:
        return {"status": "not_registered", "message": "Qurilma ro'yxatda yo'q"}

    if device.status == "approved":
        # Foydalanish vaqtini yangilaymiz
        device.last_used_at = datetime.utcnow()
        await db.commit()
        return {"status": "approved", "message": "Qurilma tasdiqlangan"}

    if device.status == "rejected":
        return {"status": "rejected", "message": "Qurilma rad etilgan"}

    return {"status": "pending", "code": device.approval_code, "message": "Admin tasdiqi kutilmoqda"}


@router.post("/request-approval")
async def request_approval(
    data: DeviceRequestApproval,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Yangi qurilma uchun tasdiq so'rash"""
    if not data.device_id or len(data.device_id) < 16:
        raise HTTPException(status_code=400, detail="Noto'g'ri device_id")

    # Bu device allaqachon bormi?
    r = await db.execute(
        select(DeviceApproval).where(
            DeviceApproval.device_id == data.device_id,
            DeviceApproval.user_id == current_user.id
        )
    )
    existing = r.scalar_one_or_none()

    if existing:
        if existing.status == "approved":
            return {"status": "approved", "message": "Allaqachon tasdiqlangan"}
        if existing.status == "pending":
            return {"status": "pending", "code": existing.approval_code, "message": "Admin tasdiqi kutilmoqda"}

    # IP va user-agent ni saqlaymiz
    client_ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "?")
    if "," in client_ip:
        client_ip = client_ip.split(",")[0].strip()
    user_agent = request.headers.get("user-agent", "")

    code = gen_approval_code()
    role = current_user.role.value if hasattr(current_user.role, 'value') else current_user.role

    if existing:
        existing.approval_code = code
        existing.status = "pending"
        existing.device_info = data.device_info
        existing.ip_address = client_ip
        existing.user_agent = user_agent[:500]
        existing.requested_at = datetime.utcnow()
    else:
        existing = DeviceApproval(
            device_id=data.device_id,
            user_id=current_user.id,
            status="pending",
            approval_code=code,
            device_info=data.device_info,
            ip_address=client_ip,
            user_agent=user_agent[:500],
        )
        db.add(existing)

    # Adminlarga Telegram orqali xabar
    admin_r = await db.execute(select(User).where(User.role == "admin", User.is_active == True))
    for admin in admin_r.scalars().all():
        db.add(Notification(
            user_id=admin.id,
            type="device_approval",
            title="🔐 Yangi qurilma tasdiqlash kerak",
            message=(f"Foydalanuvchi: {current_user.full_name} ({role})\n"
                     f"📱 Qurilma: {data.device_info or 'noma_lum'}\n"
                     f"🌐 IP: {client_ip}\n"
                     f"🔑 Kod: {code}\n\n"
                     f"Tasdiqlash: /tasdiqla {code}"),
            data={"device_id": data.device_id, "code": code, "user_id": str(current_user.id)},
            is_read=False,
            sent_to_telegram=False,
        ))

    await db.commit()
    return {"status": "pending", "code": code, "message": "Adminga so'rov yuborildi. Tasdiqlangach saytdan foydalanishingiz mumkin."}


# ─── ADMIN UCHUN: TASDIQLASH ─────────────────────────
class AdminApproveByCode(BaseModel):
    code: str


@router.post("/approve-by-code")
async def admin_approve_by_code(
    data: AdminApproveByCode,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin"))
):
    """Admin kod orqali qurilmani tasdiqlaydi"""
    r = await db.execute(
        select(DeviceApproval).where(
            DeviceApproval.approval_code == data.code.upper().strip(),
            DeviceApproval.status == "pending"
        )
    )
    device = r.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Kod topilmadi yoki allaqachon ishlatilgan")

    device.status = "approved"
    device.approved_at = datetime.utcnow()
    device.approved_by = current_user.id
    device.last_used_at = datetime.utcnow()

    # Foydalanuvchi nomi
    ur = await db.execute(select(User.full_name).where(User.id == device.user_id))
    user_name = ur.scalar_one_or_none() or "?"

    await db.commit()
    return {
        "message": f"✅ {user_name} qurilmasi tasdiqlandi",
        "user_name": user_name,
        "device_info": device.device_info,
    }


@router.post("/reject-by-code")
async def admin_reject_by_code(
    data: AdminApproveByCode,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin"))
):
    """Admin kod orqali qurilmani rad etadi"""
    r = await db.execute(
        select(DeviceApproval).where(
            DeviceApproval.approval_code == data.code.upper().strip(),
            DeviceApproval.status == "pending"
        )
    )
    device = r.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Kod topilmadi")
    device.status = "rejected"
    device.approved_at = datetime.utcnow()
    device.approved_by = current_user.id
    await db.commit()
    return {"message": "❌ Qurilma rad etildi"}


@router.get("/")
async def list_devices(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin"))
):
    """Admin: barcha qurilmalar ro'yxati"""
    r = await db.execute(
        select(DeviceApproval).order_by(DeviceApproval.requested_at.desc()).limit(100)
    )
    devices = r.scalars().all()
    out = []
    for d in devices:
        ur = await db.execute(select(User.full_name, User.username).where(User.id == d.user_id))
        u = ur.first()
        out.append({
            "id": str(d.id),
            "device_id": d.device_id[:16] + "...",
            "user_name": u[0] if u else "?",
            "username": u[1] if u else "?",
            "status": d.status,
            "code": d.approval_code,
            "device_info": d.device_info,
            "ip_address": d.ip_address,
            "requested_at": d.requested_at.isoformat() if d.requested_at else None,
            "approved_at": d.approved_at.isoformat() if d.approved_at else None,
            "last_used_at": d.last_used_at.isoformat() if d.last_used_at else None,
        })
    return out


@router.delete("/{device_id}")
async def revoke_device(
    device_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin"))
):
    """Admin: qurilma ruxsatini bekor qilish"""
    r = await db.execute(select(DeviceApproval).where(DeviceApproval.id == device_id))
    device = r.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Topilmadi")
    await db.delete(device)
    await db.commit()
    return {"message": "Qurilma ruxsati bekor qilindi"}
