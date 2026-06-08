from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import Notification, User

router = APIRouter()


@router.get("/")
async def my_notifications(
    unread_only: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    q = select(Notification).where(Notification.user_id == current_user.id)
    if unread_only:
        q = q.where(Notification.is_read == False)
    q = q.order_by(Notification.created_at.desc()).limit(50)
    r = await db.execute(q)
    return [
        {
            "id": str(n.id),
            "title": n.title,
            "message": n.message,
            "data": n.data,
            "is_read": n.is_read,
            "created_at": n.created_at.isoformat() if n.created_at else None,
        }
        for n in r.scalars().all()
    ]


@router.get("/pending-telegram")
async def pending_telegram(
    db: AsyncSession = Depends(get_db),
):
    """Bot uchun: telegramga yuborilmagan bildirishnomalar (telegram_id bilan)"""
    r = await db.execute(
        select(Notification, User.telegram_id, User.full_name, User.role)
        .join(User, Notification.user_id == User.id)
        .where(Notification.sent_to_telegram == False, User.telegram_id.isnot(None))
        .order_by(Notification.created_at)
        .limit(50)
    )
    result = []
    for n, tg_id, name, role in r.all():
        result.append({
            "id": str(n.id),
            "telegram_id": tg_id,
            "full_name": name,
            "role": role.value if hasattr(role, 'value') else role,
            "title": n.title,
            "message": n.message,
            "data": n.data,
        })
    return result


@router.post("/{notif_id}/mark-sent")
async def mark_sent(notif_id: str, db: AsyncSession = Depends(get_db)):
    await db.execute(
        update(Notification).where(Notification.id == notif_id).values(sent_to_telegram=True)
    )
    await db.commit()
    return {"ok": True}


@router.post("/mark-all-read")
async def mark_all_read(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    await db.execute(
        update(Notification).where(
            Notification.user_id == current_user.id
        ).values(is_read=True)
    )
    await db.commit()
    return {"ok": True}
