"""
Inventory Module:
- Boshlangich ostatka BIR MARTA kiritiladi
- Keyin har kun: kechagi qoldiq = bugungi boshlangich (avtomatik)
- Formula: ostatka = boshlangich + kelgan - sotilgan - chiqindi
- Inventarizatsiya: qoldiqni qo'lda to'g'rilash (Admin + Tovaroved)
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import date, timedelta
from typing import Optional, List
from pydantic import BaseModel
from uuid import UUID

from app.core.database import get_db
from app.core.security import get_current_user, require_roles
from app.models.models import (
    InventorySession, WasteRecord, Sale, Product,
    StockMovement, MovementType, User, ProcurementItem,
    ProcurementStatus, ProcurementOrder
)

router = APIRouter()


class InventoryInput(BaseModel):
    items: List[dict]
    session_date: Optional[date] = None
    notes: Optional[str] = None


class WasteInput(BaseModel):
    product_id: UUID
    quantity: float
    reason: Optional[str] = None
    waste_date: Optional[date] = None


class AdjustInput(BaseModel):
    product_id: UUID
    actual_stock: float   # haqiqiy sanab chiqilgan qoldiq
    notes: Optional[str] = None


# ─── HELPERS ───────────────────────────────────────────
async def get_initial_for_date(db: AsyncSession, product_id: str, target_date: date) -> Optional[float]:
    """O'sha kun uchun boshlangich ostatka bormi?"""
    r = await db.execute(
        select(func.sum(InventorySession.initial_stock))
        .where(
            InventorySession.product_id == product_id,
            InventorySession.session_date == target_date
        )
    )
    val = r.scalar()
    return float(val) if val is not None else None


async def get_received(db: AsyncSession, product_id: str, target_date: date) -> float:
    r = await db.execute(
        select(func.coalesce(func.sum(ProcurementItem.received_qty), 0))
        .join(ProcurementOrder, ProcurementItem.order_id == ProcurementOrder.id)
        .where(
            ProcurementItem.product_id == product_id,
            ProcurementOrder.status == ProcurementStatus.completed,
            func.date(ProcurementOrder.completed_at) == target_date
        )
    )
    return float(r.scalar() or 0)


async def get_sold(db: AsyncSession, product_id: str, target_date: date) -> float:
    r = await db.execute(
        select(func.coalesce(func.sum(Sale.quantity), 0))
        .where(Sale.product_id == product_id, Sale.sale_date == target_date)
    )
    return float(r.scalar() or 0)


async def get_waste(db: AsyncSession, product_id: str, target_date: date) -> float:
    r = await db.execute(
        select(func.coalesce(func.sum(WasteRecord.quantity), 0))
        .where(WasteRecord.product_id == product_id, WasteRecord.waste_date == target_date)
    )
    return float(r.scalar() or 0)


async def calc_stock_for_date(db: AsyncSession, product_id: str, target_date: date) -> dict:
    """
    Boshlangich ostatkani aniqlash:
    1. Agar o'sha kun uchun kiritilган bo'lsa - shuni olamiz
    2. Aks holda - kechagi qoldiqni hisoblaymiz (avtomatik o'tkazish)
    """
    initial = await get_initial_for_date(db, product_id, target_date)

    if initial is None:
        # Kechagi qoldiqni topamiz (rekursiv emas, oxirgi kiritilган kundan boshlab)
        initial = await _compute_carryover(db, product_id, target_date)

    received = await get_received(db, product_id, target_date)
    sold = await get_sold(db, product_id, target_date)
    waste = await get_waste(db, product_id, target_date)

    remaining = initial + received - sold - waste
    return {
        "initial": round(initial, 2),
        "received": round(received, 2),
        "sold": round(sold, 2),
        "waste": round(waste, 2),
        "remaining": round(max(0, remaining), 2),
    }


async def _compute_carryover(db: AsyncSession, product_id: str, target_date: date) -> float:
    """
    Oxirgi boshlangich kiritilган kundan target_date gacha qoldiqni hisoblab keladi.
    Maksimal 60 kun orqaga qaraydi.
    """
    # Oxirgi boshlangich kiritilган kunni topamiz (target_date dan oldin)
    r = await db.execute(
        select(InventorySession.session_date, func.sum(InventorySession.initial_stock).label("init"))
        .where(
            InventorySession.product_id == product_id,
            InventorySession.session_date < target_date
        )
        .group_by(InventorySession.session_date)
        .order_by(InventorySession.session_date.desc())
        .limit(1)
    )
    row = r.first()

    if not row:
        return 0.0  # Hech qachon kiritilmagan

    last_date = row.session_date
    running = float(row.init)

    # last_date dan target_date gacha har kun: + kelgan - sotilgan - chiqindi
    cur = last_date
    while cur < target_date:
        received = await get_received(db, product_id, cur)
        sold = await get_sold(db, product_id, cur)
        waste = await get_waste(db, product_id, cur)
        running = max(0, running + received - sold - waste)
        cur = cur + timedelta(days=1)

    return running


# ─── BOSHLANGICH OSTATKA (Admin) ──────────────────────
@router.post("/initial-stock")
async def set_initial_stock(
    data: InventoryInput,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin"))
):
    """Admin: boshlangich ostatka kiritadi (odatda faqat bir marta - boshda)"""
    session_date = data.session_date or date.today()
    created = 0

    for item in data.items:
        product_id = item.get("product_id")
        initial = float(item.get("initial_stock", 0))
        if not product_id or initial < 0:
            continue

        existing = await db.execute(
            select(InventorySession).where(
                InventorySession.product_id == product_id,
                InventorySession.session_date == session_date
            )
        )
        existing_rec = existing.scalar_one_or_none()

        if existing_rec:
            existing_rec.initial_stock = initial
            existing_rec.notes = item.get("notes")
        else:
            db.add(InventorySession(
                session_date=session_date,
                product_id=product_id,
                initial_stock=initial,
                notes=item.get("notes"),
                admin_id=current_user.id,
            ))

        prod_r = await db.execute(select(Product).where(Product.id == product_id))
        product = prod_r.scalar_one_or_none()
        if product:
            product.current_stock = initial
        created += 1

    await db.commit()
    return {"message": f"{created} ta mahsulot boshlangich ostatka kiritildi", "date": str(session_date)}


@router.get("/initial-stock")
async def get_initial_stock(
    session_date: Optional[date] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
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


@router.get("/has-initial")
async def has_any_initial(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Umuman boshlangich ostatka kiritilganmi?"""
    r = await db.execute(select(func.count(InventorySession.id)))
    count = r.scalar() or 0
    return {"has_initial": count > 0, "count": count}


# ─── CHIQINDI (Sotuvchi) ──────────────────────────────
@router.post("/waste")
async def record_waste(
    data: WasteInput,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("seller", "admin", "goods_receiver"))
):
    prod_r = await db.execute(select(Product).where(Product.id == data.product_id))
    product = prod_r.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Mahsulot topilmadi")

    waste_date = data.waste_date or date.today()
    db.add(WasteRecord(
        product_id=data.product_id,
        quantity=data.quantity,
        reason=data.reason,
        seller_id=current_user.id,
        waste_date=waste_date,
    ))

    # current_stock dan to'g'ridan ayiramiz (sodda va ishonchli)
    stock_before = float(product.current_stock or 0)
    new_stock = max(0, stock_before - float(data.quantity))
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
    return {"message": "Chiqindi kiritildi", "product": product.name, "remaining_stock": new_stock}


@router.get("/waste")
async def list_waste(
    waste_date: Optional[date] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
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


# ─── QOLGAN TOVAR KIRITISH (Sotuvchi) ─────────────────
class RemainingInput(BaseModel):
    items: List[dict]   # [{product_id, remaining_qty}]
    report_date: Optional[date] = None


@router.post("/remaining")
async def record_remaining(
    data: RemainingInput,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("seller", "admin", "goods_receiver"))
):
    """
    Sotuvchi kun oxirida QOLGAN tovarni kiritadi.
    Sotilgan = Boshlangich + Kelgan - Chiqindi - Qolgan
    Sotilgan miqdor Sale jadvaliga yoziladi.
    """
    target = data.report_date or date.today()
    saved = 0

    for item in data.items:
        pid = item.get("product_id")
        remaining = item.get("remaining_qty")
        if pid is None or remaining is None:
            continue
        remaining = float(remaining)

        prod_r = await db.execute(select(Product).where(Product.id == pid))
        product = prod_r.scalar_one_or_none()
        if not product:
            continue

        # Boshlangich + Kelgan - Chiqindi
        initial = await get_initial_for_date(db, str(pid), target)
        if initial is None:
            initial = await _compute_carryover(db, str(pid), target)
        received = await get_received(db, str(pid), target)
        waste = await get_waste(db, str(pid), target)

        available = initial + received - waste
        sold = available - remaining
        if sold < 0:
            sold = 0  # qolgan ko'p bo'lsa, sotilgan 0

        # Eski bugungi sotuvni o'chiramiz (qayta kiritish uchun)
        existing_sales = await db.execute(
            select(Sale).where(
                Sale.product_id == pid,
                Sale.sale_date == target,
                Sale.notes == "auto_remaining"
            )
        )
        for old in existing_sales.scalars().all():
            await db.delete(old)

        # Yangi sotuv yozuvi (avtomatik)
        if sold > 0:
            db.add(Sale(
                product_id=pid,
                quantity=sold,
                unit_price=product.selling_price,
                seller_id=current_user.id,
                sale_date=target,
                notes="auto_remaining",
            ))

        # current_stock = qolgan
        product.current_stock = remaining
        saved += 1

    await db.commit()
    return {"message": f"{saved} ta mahsulot qoldig'i kiritildi, sotuvlar hisoblandi", "date": str(target)}


# ─── INVENTARIZATSIYA (Admin + Tovaroved) ─────────────
@router.post("/adjust")
async def adjust_stock(
    data: AdjustInput,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "goods_receiver"))
):
    """
    Inventarizatsiya: haqiqiy qoldiqni sanab, tizimni to'g'rilash.
    Bugungi sana uchun yangi boshlangich sifatida yoziladi.
    """
    prod_r = await db.execute(select(Product).where(Product.id == data.product_id))
    product = prod_r.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Mahsulot topilmadi")

    today = date.today()
    stock_before = float(product.current_stock)

    # Bugungi boshlangich yozuvni yangilaymiz / yaratamiz
    existing = await db.execute(
        select(InventorySession).where(
            InventorySession.product_id == data.product_id,
            InventorySession.session_date == today
        )
    )
    rec = existing.scalar_one_or_none()

    # Haqiqiy qoldiq = yangi boshlangich, lekin bugungi sotilgan/chiqindini qaytaramiz
    sold = await get_sold(db, str(data.product_id), today)
    waste = await get_waste(db, str(data.product_id), today)
    # Inventarizatsiya = haqiqiy ombor, bugungi harakatlardan oldin
    new_initial = data.actual_stock + sold + waste

    if rec:
        rec.initial_stock = new_initial
        rec.notes = f"Inventarizatsiya: {data.notes or ''}"
    else:
        db.add(InventorySession(
            session_date=today,
            product_id=data.product_id,
            initial_stock=new_initial,
            notes=f"Inventarizatsiya: {data.notes or ''}",
            admin_id=current_user.id,
        ))

    product.current_stock = data.actual_stock

    db.add(StockMovement(
        product_id=data.product_id,
        movement_type=MovementType.adjustment,
        quantity=abs(data.actual_stock - stock_before),
        stock_before=stock_before,
        stock_after=data.actual_stock,
        reference_type="inventory_adjustment",
        user_id=current_user.id,
        notes=f"Inventarizatsiya: {data.notes or ''}"
    ))
    await db.commit()

    return {
        "message": "Inventarizatsiya bajarildi",
        "product": product.name,
        "old_stock": stock_before,
        "new_stock": data.actual_stock,
    }


# ─── HISOBOTLAR ───────────────────────────────────────
@router.get("/report/daily")
async def daily_stock_report(
    report_date: Optional[date] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    target = report_date or date.today()
    products_r = await db.execute(
        select(Product).where(Product.is_active == True).order_by(Product.name)
    )
    products = products_r.scalars().all()

    report = []
    total_sold_value = 0.0
    total_waste_value = 0.0

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
    if (date_to - date_from).days > 31:
        raise HTTPException(status_code=400, detail="Maksimal 31 kun")

    products_r = await db.execute(
        select(Product).where(Product.is_active == True).order_by(Product.name)
    )
    products = products_r.scalars().all()

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
