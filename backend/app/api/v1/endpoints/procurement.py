from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel
from uuid import UUID
import random, string

from app.core.database import get_db
from app.core.security import get_current_user, require_roles
from app.models.models import (
    ProcurementOrder, ProcurementItem, ProcurementStatus,
    Product, User, Notification
)

router = APIRouter()


def gen_order_number():
    suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))
    return f"ZK-{datetime.now().strftime('%y%m%d')}-{suffix}"


def role_str(role):
    return role.value if hasattr(role, "value") else str(role)


# ─── SCHEMAS ──────────────────────────────────────────
class ItemInput(BaseModel):
    product_id: UUID
    quantity: float
    notes: Optional[str] = None


class CreateOrder(BaseModel):
    items: List[ItemInput]
    notes: Optional[str] = None


class BuyerItemUpdate(BaseModel):
    item_id: UUID
    bought_qty: float          # bozorchi olgan miqdor
    price: Optional[float] = None
    supplier: Optional[str] = None


class BuyerConfirm(BaseModel):
    items: List[BuyerItemUpdate]
    notes: Optional[str] = None


class ReceiveItem(BaseModel):
    item_id: UUID
    received_qty: float
    damaged_qty: float = 0
    actual_price: Optional[float] = None


class ReceiveInput(BaseModel):
    items: List[ReceiveItem]
    invoice_number: Optional[str] = None
    notes: Optional[str] = None


# ─── NOTIFICATION HELPER ──────────────────────────────
async def notify_role(db: AsyncSession, role: str, title: str, message: str, order_id: str = None):
    """Berilган roldagi barcha userlarga bildirishnoma yaratadi (bot o'qiydi)"""
    users_r = await db.execute(select(User).where(User.role == role, User.is_active == True))
    users = users_r.scalars().all()
    for u in users:
        db.add(Notification(
            user_id=u.id,
            type="workflow",
            title=title,
            message=message,
            data={"order_id": order_id, "for_role": role} if order_id else {"for_role": role},
            is_read=False,
            sent_to_telegram=False,
        ))


def order_dict(o: ProcurementOrder) -> dict:
    return {
        "id": str(o.id),
        "order_number": o.order_number,
        "status": o.status.value if hasattr(o.status, 'value') else str(o.status),
        "total_estimated_cost": float(o.total_estimated_cost or 0),
        "total_actual_cost": float(o.total_actual_cost or 0),
        "buyer_notes": o.buyer_notes,
        "warehouse_notes": o.warehouse_notes,
        "created_at": o.created_at.isoformat() if o.created_at else None,
        "buyer_confirmed_at": o.buyer_confirmed_at.isoformat() if o.buyer_confirmed_at else None,
        "warehouse_approved_at": o.warehouse_approved_at.isoformat() if o.warehouse_approved_at else None,
        "completed_at": o.completed_at.isoformat() if o.completed_at else None,
    }


# ─── 1. SOTUVCHI: ZAKAZ YARATISH ──────────────────────
@router.post("/")
async def create_order(
    data: CreateOrder,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("seller", "admin"))
):
    """Sotuvchi: kerakli mahsulotlar bilan zakaz yaratadi → Bozorchiga"""
    if not data.items:
        raise HTTPException(status_code=400, detail="Kamida bitta mahsulot kerak")

    order = ProcurementOrder(
        order_number=gen_order_number(),
        status=ProcurementStatus.ai_generated,  # sotuvchi yaratdi, bozorchi kutyapti
        buyer_notes=data.notes,
        created_at=datetime.utcnow(),
    )
    db.add(order)
    await db.flush()

    for it in data.items:
        db.add(ProcurementItem(
            order_id=order.id,
            product_id=it.product_id,
            ai_recommended_qty=it.quantity,   # sotuvchi so'ragan miqdor
            buyer_ordered_qty=None,
            notes=it.notes,
        ))

    await notify_role(db, "buyer", "🛒 Yangi zakaz", f"Sotuvchidan yangi zakaz: {order.order_number}", str(order.id))
    await db.commit()

    return {
        "id": str(order.id),
        "order_number": order.order_number,
        "message": "Zakaz bozorchiga yuborildi",
    }


# ─── 2. BOZORCHI: TASDIQLASH ──────────────────────────
@router.post("/{order_id}/buyer-confirm")
async def buyer_confirm(
    order_id: UUID,
    data: BuyerConfirm,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("buyer", "admin"))
):
    """Bozorchi: olgan mahsulotlarni belgilaydi → Omborchiga"""
    r = await db.execute(select(ProcurementOrder).where(ProcurementOrder.id == order_id))
    order = r.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Zakaz topilmadi")

    total = 0.0
    for upd in data.items:
        ir = await db.execute(select(ProcurementItem).where(ProcurementItem.id == upd.item_id))
        item = ir.scalar_one_or_none()
        if item:
            item.buyer_ordered_qty = upd.bought_qty
            item.estimated_price = upd.price
            if upd.price:
                total += upd.bought_qty * upd.price

    order.status = ProcurementStatus.buyer_confirmed
    order.buyer_id = current_user.id
    order.buyer_notes = data.notes
    order.total_estimated_cost = total
    order.buyer_confirmed_at = datetime.utcnow()

    await notify_role(db, "warehouse_manager", "📦 Tasdiqlash kerak", f"Bozorchidan zakaz: {order.order_number}", str(order.id))
    await db.commit()
    return {"message": "Zakaz omborchiga yuborildi", "status": order.status.value}


# ─── 3. OMBORCHI: QABUL / TAHRIR / BEKOR ──────────────
@router.patch("/{order_id}/approve")
async def approve_order(
    order_id: UUID,
    notes: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("warehouse_manager", "admin"))
):
    """Omborchi: tasdiqlaydi → Tovarovedga"""
    r = await db.execute(select(ProcurementOrder).where(ProcurementOrder.id == order_id))
    order = r.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Zakaz topilmadi")

    order.status = ProcurementStatus.warehouse_approved
    order.warehouse_manager_id = current_user.id
    order.warehouse_notes = notes
    order.warehouse_approved_at = datetime.utcnow()

    await notify_role(db, "goods_receiver", "📥 Tovar kutilmoqda", f"Tasdiqlangan zakaz: {order.order_number}", str(order.id))
    await db.commit()
    return {"message": "Zakaz tovarovedga yuborildi", "status": order.status.value}


@router.patch("/{order_id}/reject")
async def reject_order(
    order_id: UUID,
    notes: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("warehouse_manager", "admin"))
):
    r = await db.execute(select(ProcurementOrder).where(ProcurementOrder.id == order_id))
    order = r.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Zakaz topilmadi")
    order.status = ProcurementStatus.rejected
    order.warehouse_manager_id = current_user.id
    order.warehouse_notes = notes
    await notify_role(db, "buyer", "❌ Zakaz rad etildi", f"{order.order_number} rad etildi", str(order.id))
    await db.commit()
    return {"message": "Zakaz rad etildi", "status": order.status.value}


# ─── 4. TOVAROVED: QABUL QILISH ───────────────────────
@router.post("/{order_id}/receive")
async def receive_goods(
    order_id: UUID,
    data: ReceiveInput,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("goods_receiver", "admin"))
):
    """Tovaroved: kelgan tovarni qabul qiladi, ombor yangilanadi"""
    from app.models.models import StockMovement, MovementType

    r = await db.execute(select(ProcurementOrder).where(ProcurementOrder.id == order_id))
    order = r.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Zakaz topilmadi")

    total_actual = 0.0
    for ri in data.items:
        ir = await db.execute(select(ProcurementItem).where(ProcurementItem.id == ri.item_id))
        item = ir.scalar_one_or_none()
        if not item:
            continue
        item.received_qty = ri.received_qty
        item.damaged_qty = ri.damaged_qty
        item.actual_price = ri.actual_price
        if ri.actual_price:
            total_actual += ri.received_qty * ri.actual_price

        # Omborni yangilash (received - damaged)
        pr = await db.execute(select(Product).where(Product.id == item.product_id))
        product = pr.scalar_one_or_none()
        if product:
            net = ri.received_qty - ri.damaged_qty
            before = float(product.current_stock)
            product.current_stock = before + net
            db.add(StockMovement(
                product_id=product.id,
                movement_type=MovementType.incoming,
                quantity=net,
                stock_before=before,
                stock_after=before + net,
                reference_id=order.id,
                reference_type="procurement_receive",
                user_id=current_user.id,
                notes=f"Zakaz {order.order_number}"
            ))

    order.status = ProcurementStatus.completed
    order.receiver_id = current_user.id
    order.total_actual_cost = total_actual
    order.completed_at = datetime.utcnow()

    await notify_role(db, "buyer", "✅ Tovar qabul qilindi", f"{order.order_number} yakunlandi", str(order.id))
    await db.commit()
    return {"message": "Tovar qabul qilindi, ombor yangilandi", "status": order.status.value}


# ─── RO'YXAT VA TAFSILOT ──────────────────────────────
@router.get("/")
async def list_orders(
    status: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    query = select(ProcurementOrder).order_by(ProcurementOrder.created_at.desc())
    if status:
        try:
            query = query.where(ProcurementOrder.status == ProcurementStatus(status))
        except ValueError:
            pass
    r = await db.execute(query)
    return [order_dict(o) for o in r.scalars().all()]


@router.get("/{order_id}")
async def get_order(
    order_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    r = await db.execute(select(ProcurementOrder).where(ProcurementOrder.id == order_id))
    order = r.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Zakaz topilmadi")

    items_r = await db.execute(
        select(ProcurementItem, Product.name, Product.unit)
        .join(Product, ProcurementItem.product_id == Product.id)
        .where(ProcurementItem.order_id == order_id)
    )
    d = order_dict(order)
    d["items"] = [
        {
            "id": str(it.id),
            "product_id": str(it.product_id),
            "product_name": name,
            "unit": unit,
            "requested_qty": float(it.ai_recommended_qty or 0),
            "bought_qty": float(it.buyer_ordered_qty or 0),
            "received_qty": float(it.received_qty or 0),
            "damaged_qty": float(it.damaged_qty or 0),
            "price": float(it.estimated_price or 0),
            "actual_price": float(it.actual_price or 0),
            "notes": it.notes,
        }
        for it, name, unit in items_r.all()
    ]
    return d


# ─── EXCEL EXPORT (Nakladnoy) ─────────────────────────
@router.get("/{order_id}/excel")
async def export_excel(
    order_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Nakladnoyni Excel formatida yuklab olish"""
    from fastapi.responses import StreamingResponse
    import io
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
    except ImportError:
        raise HTTPException(status_code=500, detail="openpyxl o'rnatilmagan")

    r = await db.execute(select(ProcurementOrder).where(ProcurementOrder.id == order_id))
    order = r.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Zakaz topilmadi")

    items_r = await db.execute(
        select(ProcurementItem, Product.name, Product.unit)
        .join(Product, ProcurementItem.product_id == Product.id)
        .where(ProcurementItem.order_id == order_id)
    )
    items = items_r.all()

    wb = Workbook()
    ws = wb.active
    ws.title = "Nakladnoy"

    bold = Font(bold=True)
    header_fill = PatternFill(start_color="3FB950", end_color="3FB950", fill_type="solid")
    center = Alignment(horizontal="center", vertical="center")
    thin = Side(style="thin")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    # Sarlavha
    ws.merge_cells("A1:G1")
    ws["A1"] = "NAKLADNOY"
    ws["A1"].font = Font(bold=True, size=16)
    ws["A1"].alignment = center

    ws["A2"] = f"Zakaz raqami: {order.order_number}"
    ws["A2"].font = bold
    ws["A3"] = f"Sana: {order.created_at.strftime('%d.%m.%Y') if order.created_at else ''}"
    ws["A4"] = f"Holat: {order.status.value if hasattr(order.status, 'value') else order.status}"

    # Jadval sarlavhasi
    headers = ["№", "Mahsulot", "Birlik", "So'ralgan", "Olingan", "Qabul", "Narx", "Summa"]
    row = 6
    for col, h in enumerate(headers, 1):
        c = ws.cell(row=row, column=col, value=h)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = header_fill
        c.alignment = center
        c.border = border

    # Ma'lumotlar
    total = 0
    for i, (it, name, unit) in enumerate(items, 1):
        row += 1
        received = float(it.received_qty or 0)
        price = float(it.actual_price or it.estimated_price or 0)
        summa = received * price
        total += summa
        vals = [
            i, name, unit,
            float(it.ai_recommended_qty or 0),
            float(it.buyer_ordered_qty or 0),
            received, price, summa
        ]
        for col, v in enumerate(vals, 1):
            c = ws.cell(row=row, column=col, value=v)
            c.border = border
            if col >= 4:
                c.alignment = center

    # Jami
    row += 1
    ws.cell(row=row, column=7, value="JAMI:").font = bold
    ws.cell(row=row, column=8, value=total).font = bold

    # Ustun kengligi
    widths = [5, 25, 10, 12, 12, 10, 12, 15]
    for col, w in enumerate(widths, 1):
        ws.column_dimensions[chr(64 + col)].width = w

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=nakladnoy_{order.order_number}.xlsx"}
    )
