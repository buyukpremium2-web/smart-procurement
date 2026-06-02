"""
Inventory Module:
- Admin: boshlangich ostatka kiritish (inventory_sessions)
- Sotuvchi: chiqindi/buzilgan kiritish (waste_records)
- Hisobot: ostatka = boshlangich + kelgan - sotilgan - chiqindi
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from datetime import date, timedelta
from typing import Optional, List
from pydantic import BaseModel
from uuid import UUID

from app.core.database import get_db
from app.core.security import get_current_user, require_roles
from app.models.models import (
    InventorySession, WasteRecord, Sale, Product,
    StockMovement, MovementType, User, ProcurementItem, ProcurementStatus, ProcurementOrder
)

router = APIRouter()


# ─── SCHEMAS ───────────────────────────────────────────
class InventoryInput(BaseModel):
    items: List[dict]   # [{product_id, initial_stock, notes?}]
    session_date: Optional[date] = None
    notes: Optional[str] = None


class WasteInput(BaseModel):
    product_id: UUID
    quantity: float
    reason: Optional[str] = None
    waste_date: Optional[date] = None


# ─── HELPERS ───────────────────────────────────────────
async def calc_stock_for_date(db: AsyncSession, product_id: str, target_date: date) -> dict:
    """
    Formula: ostatka = boshlangich + kelgan - sotilgan - chiqindi
    """
    # 1. Boshlangich (o'sha kun admin kiritgan)
    inv_result = await db.execute(
        select(func.coalesce(func.sum(InventorySession.initial_stock), 0))
        .where(
            InventorySession.product_id == product_id,
            InventorySession.session_date == target_date
        )
    )
    initial = float(inv_result.scalar() or 0)

    # 2. Kelgan tovar (o'sha kun completed procurement)
    received_result = await db.execute(
        select(func.coalesce(func.sum(ProcurementItem.received_qty), 0))
        .join(ProcurementOrder, ProcurementItem.order_id == ProcurementOrder.id)
        .where(
            ProcurementItem.product_id == product_id,
            ProcurementOrder.status == ProcurementStatus.completed,
            func.date(ProcurementOrder.completed_at) == target_date
        )
    )
    received = float(received_result.scalar() or 0)

    # 3. Sotilgan
    sold_result = await db.execute(
        select(func.coalesce(func.sum(Sale.quantity), 0))
        .where(Sale.product_id == product_id, Sale.sale_date == target_date)
    )
    sold = float(sold_result.scalar() or 0)

    # 4. Chiqindi
    waste_result = await db.execute(
        select(func.coalesce(func.sum(WasteRecord.quantity), 0))
        .where(WasteRecord.product_id == product_id, WasteRecord.waste_date == target_date)
    )
    waste = float(waste_result.scalar() or 0)

    remaining = initial + received - sold - waste
    return {
        "initial": initial,
        "received": received,
        "sold": sold,
        "waste": waste,
        "remaining": max(0, remaining)
    }


# ─── ADMIN: BOSHLANGICH OSTATKA ───────────────────────
@router.post("/initial-stock")
async def set_initial_stock(
    data: InventoryInput,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin"))
):
    """Admin: kunning boshida boshlangich ostatka kiritadi"""
    session_date = data.session_date or date.today()
    created = 0

    for item in data.items:
        product_id = item.get("product_id")
        initial = float(item.get("initial_stock", 0))
        if not product_id or initial < 0:
            continue

        # Avvalgi yozuv bo'lsa yangilaymiz
        existing = await db.execute(
            select(InventorySession).where(
                InventorySession.product_id == product_id,
                InventorySession.session_date == session_date
            )
        )
        existing_rec = existing.scalar_one_or_none()

        if existing_rec:
            old_stock = float(existing_rec.initial_stock)
            existing_rec.initial_stock = initial
            existing_rec.notes = item.get("notes")
        else:
            old_stock = None
            rec = InventorySession(
                session_date=session_date,
                product_id=product_id,
                initial_stock=initial,
                notes=item.get("notes"),
                admin_id=current_user.id,
            )
            db.add(rec)

        # Mahsulot current_stock ni yangilaymiz (bugungi formula bilan)
        prod_r = await db.execute(select(Product).where(Product.id == product_id))
        product = prod_r.scalar_one_or_none()
        if product:
            stock_data = await calc_stock_for_date(db, str(product_id), session_date)
            stock_before = float(product.current_stock)
            product.current_stock = stock_data["remaining"]

            # Movement log
            db.add(StockMovement(
                product_id=product_id,
                movement_type=MovementType.initial,
                quantity=initial,
                stock_before=stock_before,
                stock_after=stock_data["remaining"],
                reference_type="inventory_session",
                user_id=current_user.id,
                notes=f"Boshlangich ostatka: {session_date}"
            ))
        created += 1

    await db.commit()
    return {"message": f"{created} ta mahsulot boshlangich ostatka kiritildi", "date": str(session_date)}


@router.get("/initial-stock")
async def get_initial_stock(
    session_date: Optional[date] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin"))
):
    """Admin: boshlangich ostatka ro'yxati"""
    target = session_date or date.today()
    result = await db.execute(
        select(InventorySession, Product.name, Product.unit)
        .join(Product, InventorySession.product_id == Product.id)
        .where(InventorySession.session_date == target)
        .order_by(Product.name)
    )
    rows = result.all()
    return [
        {
            "id": str(s.id),
            "product_id": str(s.product_id),
            "product_name": name,
            "unit": unit,
            "initial_stock": float(s.initial_stock),
            "notes": s.notes,
            "session_date": str(s.session_date),
        }
        for s, name, unit in rows
    ]


# ─── SOTUVCHI: CHIQINDI ────────────────────────────────
@router.post("/waste")
async def record_waste(
    data: WasteInput,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("seller", "admin"))
):
    """Sotuvchi: buzilgan/chiqindi mahsulot kiritadi"""
    prod_r = await db.execute(select(Product).where(Product.id == data.product_id))
    product = prod_r.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Mahsulot topilmadi")

    waste_date = data.waste_date or date.today()

    waste = WasteRecord(
        product_id=data.product_id,
        quantity=data.quantity,
        reason=data.reason,
        seller_id=current_user.id,
        waste_date=waste_date,
    )
    db.add(waste)

    # current_stock yangilash
    stock_before = float(product.current_stock)
    stock_data = await calc_stock_for_date(db, str(data.product_id), waste_date)
    # waste hali saqlanmagan, qo'lda ayiramiz
    new_stock = max(0, stock_data["remaining"] - data.quantity)
    product.current_stock = new_stock

    db.add(StockMovement(
        product_id=data.product_id,
        movement_type=MovementType.waste,
        quantity=data.quantity,
        stock_before=stock_before,
        stock_after=new_stock,
        reference_type="waste_record",
        user_id=current_user.id,
        notes=data.reason or "Chiqindi"
    ))
    await db.commit()

    return {
        "message": "Chiqindi kiritildi",
        "product": product.name,
        "waste_qty": data.quantity,
        "remaining_stock": new_stock
    }


@router.get("/waste")
async def list_waste(
    waste_date: Optional[date] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Chiqindi ro'yxati"""
    target = waste_date or date.today()
    result = await db.execute(
        select(WasteRecord, Product.name, Product.unit, User.full_name)
        .join(Product, WasteRecord.product_id == Product.id)
        .join(User, WasteRecord.seller_id == User.id)
        .where(WasteRecord.waste_date == target)
        .order_by(WasteRecord.created_at.desc())
    )
    rows = result.all()
    return [
        {
            "id": str(w.id),
            "product_name": name,
            "unit": unit,
            "quantity": float(w.quantity),
            "reason": w.reason,
            "seller_name": seller_name,
            "waste_date": str(w.waste_date),
        }
        for w, name, unit, seller_name in rows
    ]


# ─── HISOBOT: OSTATKA HISOBI ──────────────────────────
@router.get("/report/daily")
async def daily_stock_report(
    report_date: Optional[date] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Kunlik hisobot: barcha mahsulotlar bo'yicha
    boshlangich + kelgan - sotilgan - chiqindi = ostatka
    """
    target = report_date or date.today()

    products_r = await db.execute(
        select(Product).where(Product.is_active == True).order_by(Product.name)
    )
    products = products_r.scalars().all()

    report = []
    total_sold_value = 0
    total_waste_value = 0

    for p in products:
        stock = await calc_stock_for_date(db, str(p.id), target)
        sold_value = stock["sold"] * float(p.selling_price)
        waste_value = stock["waste"] * float(p.purchase_price)
        total_sold_value += sold_value
        total_waste_value += waste_value

        report.append({
            "product_id": str(p.id),
            "product_name": p.name,
            "unit": p.unit,
            "initial_stock": stock["initial"],
            "received": stock["received"],
            "sold": stock["sold"],
            "waste": stock["waste"],
            "remaining": stock["remaining"],
            "sold_value": round(sold_value),
            "waste_value": round(waste_value),
            "selling_price": float(p.selling_price),
            "purchase_price": float(p.purchase_price),
            "is_low": stock["remaining"] < float(p.minimum_stock),
        })

    return {
        "date": str(target),
        "summary": {
            "total_products": len(products),
            "total_sold_value": round(total_sold_value),
            "total_waste_value": round(total_waste_value),
            "low_stock_count": sum(1 for r in report if r["is_low"]),
        },
        "items": report
    }


@router.get("/report/range")
async def range_stock_report(
    date_from: date = Query(...),
    date_to: date = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Davr bo'yicha hisobot (admin va bozorchi uchun)"""
    if (date_to - date_from).days > 31:
        raise HTTPException(status_code=400, detail="Maksimal 31 kun")

    products_r = await db.execute(
        select(Product).where(Product.is_active == True).order_by(Product.name)
    )
    products = products_r.scalars().all()

    # Sotilgan miqdor va qiymat
    sold_result = await db.execute(
        select(
            Sale.product_id,
            func.sum(Sale.quantity).label("total_qty"),
            func.sum(Sale.quantity * Sale.unit_price).label("total_value")
        )
        .where(Sale.sale_date.between(date_from, date_to))
        .group_by(Sale.product_id)
    )
    sold_map = {str(r.product_id): {"qty": float(r.total_qty), "value": float(r.total_value)} for r in sold_result}

    # Chiqindi miqdori
    waste_result = await db.execute(
        select(WasteRecord.product_id, func.sum(WasteRecord.quantity).label("total"))
        .where(WasteRecord.waste_date.between(date_from, date_to))
        .group_by(WasteRecord.product_id)
    )
    waste_map = {str(r.product_id): float(r.total) for r in waste_result}

    items = []
    for p in products:
        pid = str(p.id)
        sold = sold_map.get(pid, {"qty": 0, "value": 0})
        waste_qty = waste_map.get(pid, 0)
        items.append({
            "product_name": p.name,
            "unit": p.unit,
            "current_stock": float(p.current_stock),
            "sold_qty": sold["qty"],
            "sold_value": round(sold["value"]),
            "waste_qty": waste_qty,
            "waste_value": round(waste_qty * float(p.purchase_price)),
        })

    return {
        "date_from": str(date_from),
        "date_to": str(date_to),
        "summary": {
            "total_sold_value": sum(i["sold_value"] for i in items),
            "total_waste_value": sum(i["waste_value"] for i in items),
            "total_waste_qty": sum(i["waste_qty"] for i in items),
        },
        "items": sorted(items, key=lambda x: x["sold_value"], reverse=True)
    }
