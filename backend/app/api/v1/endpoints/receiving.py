from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel
from uuid import UUID

from app.core.database import get_db
from app.core.security import get_current_user, require_roles
from app.models.models import (
    ProcurementOrder, ProcurementItem, ProcurementStatus,
    Product, StockMovement, MovementType, User
)

router = APIRouter()


class ReceiveItemInput(BaseModel):
    procurement_item_id: UUID
    received_qty: float
    damaged_qty: float = 0
    actual_price: Optional[float] = None


class ReceiveOrderInput(BaseModel):
    items: List[ReceiveItemInput]
    invoice_number: Optional[str] = None
    invoice_photo_url: Optional[str] = None
    notes: Optional[str] = None


@router.get("/pending")
async def get_pending_receiving(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("goods_receiver", "admin"))
):
    """Qabul qilish kutayotgan zakazlar."""
    result = await db.execute(
        select(ProcurementOrder)
        .where(ProcurementOrder.status == ProcurementStatus.warehouse_approved)
        .order_by(ProcurementOrder.warehouse_approved_at.desc())
    )
    orders = result.scalars().all()

    response = []
    for order in orders:
        items_result = await db.execute(
            select(ProcurementItem, Product.name, Product.unit)
            .join(Product, ProcurementItem.product_id == Product.id)
            .where(ProcurementItem.order_id == order.id)
        )
        items = items_result.all()
        response.append({
            "id": str(order.id),
            "order_number": order.order_number,
            "status": order.status.value,
            "total_estimated_cost": float(order.total_estimated_cost or 0),
            "warehouse_approved_at": order.warehouse_approved_at.isoformat() if order.warehouse_approved_at else None,
            "items": [
                {
                    "id": str(item.id),
                    "product_name": name,
                    "unit": unit,
                    "buyer_ordered_qty": float(item.buyer_ordered_qty or 0),
                    "estimated_price": float(item.estimated_price or 0),
                }
                for item, name, unit in items
            ]
        })
    return response


@router.post("/{order_id}/receive")
async def receive_order(
    order_id: UUID,
    data: ReceiveOrderInput,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("goods_receiver", "admin"))
):
    """Tovarni qabul qilish va ombor yangilash."""
    result = await db.execute(select(ProcurementOrder).where(ProcurementOrder.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Zakaz topilmadi")
    if order.status != ProcurementStatus.warehouse_approved:
        raise HTTPException(status_code=400, detail=f"Bu zakaz qabul qilinishi mumkin emas. Holat: {order.status.value}")

    order.status = ProcurementStatus.receiving
    total_actual = 0.0

    for recv in data.items:
        item_result = await db.execute(
            select(ProcurementItem).where(ProcurementItem.id == recv.procurement_item_id)
        )
        item = item_result.scalar_one_or_none()
        if not item:
            continue

        item.received_qty = recv.received_qty
        item.damaged_qty = recv.damaged_qty
        if recv.actual_price:
            item.actual_price = recv.actual_price
            total_actual += recv.received_qty * recv.actual_price

        # Ombor yangilash (shikastlanmagan miqdor)
        net_received = recv.received_qty - recv.damaged_qty
        if net_received > 0:
            prod_result = await db.execute(select(Product).where(Product.id == item.product_id))
            product = prod_result.scalar_one_or_none()
            if product:
                stock_before = float(product.current_stock)
                product.current_stock = stock_before + net_received

                movement = StockMovement(
                    product_id=product.id,
                    movement_type=MovementType.incoming,
                    quantity=net_received,
                    reference_id=item.id,
                    reference_type="procurement_item",
                    stock_before=stock_before,
                    stock_after=float(product.current_stock),
                    user_id=current_user.id,
                    notes=f"Zakaz {order.order_number} bo'yicha qabul"
                )
                db.add(movement)

    order.status = ProcurementStatus.completed
    order.receiver_id = current_user.id
    order.total_actual_cost = total_actual
    order.completed_at = datetime.utcnow()

    await db.commit()
    return {
        "message": "Tovar qabul qilindi va ombor yangilandi!",
        "order_number": order.order_number,
        "status": "completed",
        "total_actual_cost": total_actual
    }
