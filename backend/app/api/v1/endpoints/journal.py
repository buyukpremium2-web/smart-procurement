"""
Omborchi jurnali - kontragentlar (korxonalar) reestri
- Sana, summa, korxona nomi, ekspeditor, telefon, izoh
- Davr bo'yicha ko'rsatish
- Filtr: korxona nomi yoki summa
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel
from uuid import UUID

from app.core.database import get_db
from app.core.security import require_roles
from app.models.models import WarehouseJournal, User

router = APIRouter()


class JournalEntry(BaseModel):
    entry_date: Optional[date] = None
    amount: float = 0
    company_name: str
    expeditor: Optional[str] = None
    phone: Optional[str] = None
    comment: Optional[str] = None


@router.post("/")
async def add_journal(
    data: JournalEntry,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "goods_receiver", "warehouse_manager"))
):
    """Jurnalga kontragent qo'shish - takrorlanmaslik tekshiruvi bilan"""
    company = (data.company_name or "").strip()
    if not company:
        raise HTTPException(status_code=400, detail="Korxona nomi kerak")

    # Bu firma avval kiritilganmi?
    existing_r = await db.execute(
        select(WarehouseJournal).where(WarehouseJournal.company_name.ilike(company)).limit(1)
    )
    existing = existing_r.scalar_one_or_none()
    is_new = existing is None

    entry = WarehouseJournal(
        entry_date=data.entry_date or date.today(),
        amount=float(data.amount),
        company_name=company,
        expeditor=data.expeditor or (existing.expeditor if existing else None),
        phone=data.phone or (existing.phone if existing else None),
        comment=data.comment,
        created_by=current_user.id,
    )
    db.add(entry)
    await db.commit()
    return {
        "message": f"⊕ Yangi firma '{company}' qo'shildi" if is_new else f"✓ '{company}' uchun yangi yozuv qo'shildi",
        "is_new_company": is_new,
    }


@router.get("/companies")
async def list_companies(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "goods_receiver", "warehouse_manager"))
):
    """Mavjud firmalar ro'yxati (autocomplete uchun)"""
    r = await db.execute(select(WarehouseJournal))
    rows = r.scalars().all()
    # Korxona bo'yicha guruh
    by_company = {}
    for e in rows:
        key = (e.company_name or "").strip()
        if not key:
            continue
        if key not in by_company:
            by_company[key] = {
                "company_name": key,
                "expeditor": e.expeditor or "",
                "phone": e.phone or "",
                "count": 0,
            }
        by_company[key]["count"] += 1
        # Eng oxirgi ekspeditor/telefon
        if e.expeditor:
            by_company[key]["expeditor"] = e.expeditor
        if e.phone:
            by_company[key]["phone"] = e.phone
    return list(by_company.values())


@router.get("/")
async def list_journal(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    search: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "goods_receiver", "warehouse_manager"))
):
    """Jurnal yozuvlari - davr va qidiruv bilan"""
    query = select(WarehouseJournal).order_by(WarehouseJournal.entry_date.desc(), WarehouseJournal.created_at.desc())
    if from_date:
        query = query.where(WarehouseJournal.entry_date >= from_date)
    if to_date:
        query = query.where(WarehouseJournal.entry_date <= to_date)
    result = await db.execute(query)
    rows = result.scalars().all()

    out = []
    total = 0.0
    s = (search or "").strip().lower()
    for r in rows:
        # Qidiruv: korxona nomi yoki summa
        if s:
            name_match = s in (r.company_name or "").lower()
            amount_match = s in str(r.amount)
            if not (name_match or amount_match):
                continue
        total += float(r.amount)
        out.append({
            "id": str(r.id),
            "date": str(r.entry_date),
            "amount": float(r.amount),
            "company_name": r.company_name,
            "expeditor": r.expeditor or "",
            "phone": r.phone or "",
            "comment": r.comment or "",
        })

    return {
        "entries": out,
        "total": round(total, 2),
        "count": len(out),
        "from_date": str(from_date) if from_date else None,
        "to_date": str(to_date) if to_date else None,
    }


@router.delete("/{entry_id}")
async def delete_journal(
    entry_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "goods_receiver", "warehouse_manager"))
):
    result = await db.execute(select(WarehouseJournal).where(WarehouseJournal.id == entry_id))
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Topilmadi")
    await db.delete(entry)
    await db.commit()
    return {"message": "O'chirildi"}
