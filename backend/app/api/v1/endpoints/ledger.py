"""
Bozorchi hisob-kitobi (Akt-sverka)
- Pul oldi (+), Tovar oldi (-)
- Qoldiq ketma-ket yuriladi
- Har bozorchi alohida
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel
from uuid import UUID

from app.core.database import get_db
from app.core.security import get_current_user, require_roles
from app.models.models import BuyerLedger, User, UserRole

router = APIRouter()


class LedgerEntry(BaseModel):
    buyer_id: UUID
    entry_type: str          # 'money' yoki 'goods'
    amount: float            # qiymat (musbat)
    comment: Optional[str] = None
    entry_date: Optional[date] = None


@router.get("/buyers")
async def list_buyers(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "buyer", "goods_receiver"))
):
    """Bozorchilar ro'yxati (hisob uchun)"""
    result = await db.execute(
        select(User).where(User.role == UserRole.buyer, User.is_active == True).order_by(User.full_name)
    )
    return [{"id": str(u.id), "full_name": u.full_name, "username": u.username} for u in result.scalars().all()]


@router.post("/")
async def add_entry(
    data: LedgerEntry,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "buyer"))
):
    """Hisobga yozuv qo'shish: pul oldi (+) yoki tovar oldi (-)"""
    if data.entry_type not in ("money", "goods"):
        raise HTTPException(status_code=400, detail="entry_type 'money' yoki 'goods' bo'lishi kerak")

    amt = abs(float(data.amount))
    # money = +, goods = -
    signed = amt if data.entry_type == "money" else -amt

    entry = BuyerLedger(
        buyer_id=data.buyer_id,
        entry_date=data.entry_date or date.today(),
        entry_type=data.entry_type,
        amount=signed,
        comment=data.comment,
        created_by=current_user.id,
    )
    db.add(entry)
    await db.commit()
    return {"message": "Yozuv qo'shildi"}


@router.get("/{buyer_id}")
async def get_ledger(
    buyer_id: UUID,
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "buyer", "goods_receiver"))
):
    """Bozorchi hisobi: davr bo'yicha yozuvlar + ketma-ket qoldiq"""
    # Hamma yozuvlar (qoldiqni to'g'ri hisoblash uchun)
    result = await db.execute(
        select(BuyerLedger).where(BuyerLedger.buyer_id == buyer_id)
        .order_by(BuyerLedger.entry_date, BuyerLedger.created_at)
    )
    all_rows = result.scalars().all()

    entries = []
    running = 0.0
    opening_balance = 0.0   # davr boshigacha bo'lgan qoldiq
    total_money = 0.0
    total_goods = 0.0

    for r in all_rows:
        amt = float(r.amount)
        running += amt
        # Davrga kiradimi?
        in_period = True
        if from_date and r.entry_date < from_date:
            in_period = False
        if to_date and r.entry_date > to_date:
            in_period = False

        if not in_period:
            # Davrdan oldingi yozuv - faqat opening balansga qo'shamiz
            if (not from_date) or r.entry_date < from_date:
                opening_balance = running
            continue

        if amt > 0:
            total_money += amt
        else:
            total_goods += abs(amt)
        entries.append({
            "id": str(r.id),
            "date": str(r.entry_date),
            "type": r.entry_type,
            "money_in": amt if amt > 0 else 0,
            "goods_out": abs(amt) if amt < 0 else 0,
            "comment": r.comment,
            "balance": round(running, 2),
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })

    ur = await db.execute(select(User.full_name).where(User.id == buyer_id))
    name = ur.scalar_one_or_none()

    return {
        "buyer_id": str(buyer_id),
        "buyer_name": name or "?",
        "balance": round(running, 2),               # umumiy qoldiq (hamma vaqt)
        "opening_balance": round(opening_balance, 2), # davr boshidagi qoldiq
        "total_money": round(total_money, 2),
        "total_goods": round(total_goods, 2),
        "entries": entries,
        "from_date": str(from_date) if from_date else None,
        "to_date": str(to_date) if to_date else None,
    }


@router.delete("/{entry_id}")
async def delete_entry(
    entry_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin"))
):
    result = await db.execute(select(BuyerLedger).where(BuyerLedger.id == entry_id))
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Yozuv topilmadi")
    await db.delete(entry)
    await db.commit()
    return {"message": "O'chirildi"}
