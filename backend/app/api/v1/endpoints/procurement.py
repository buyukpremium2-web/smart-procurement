from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel
from uuid import UUID
import random, string

from app.core.database import get_db
from app.core.security import get_current_user, require_roles
from app.models.models import (
    ProcurementOrder, ProcurementItem,
    ProcurementStatus, Product, User
)

router = APIRouter()


def generate_order_number():
    suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"PRO-{datetime.now().strftime('%Y%m%d')}-{suffix}"


class ProcurementItemInput(BaseModel):
    product_id: UUID
    buyer_ordered_qty: float
    estimated_price: Optional[float] = None
    supplier_id: Optional[UUID] = None
    notes: Optional[str] = None


class ProcurementCreate(BaseModel):
    items: List[ProcurementItemInput]
    buyer_notes: Optional[str] = None


def order_to_dict(o: ProcurementOrder) -> dict:
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
    }


@router.post("/", dependencies=[Depends(require_roles("buyer", "admin"))])
async def create_procurement(
    data: ProcurementCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    order = ProcurementOrder(
        order_number=generate_order_number(),
        status=ProcurementStatus.buyer_confirmed,
        buyer_id=current_user.id,
        buyer_notes=data.buyer_notes,
        buyer_confirmed_at=datetime.utcnow(),
    )
    db.add(order)
    await db.flush()

    total_cost = 0.0
    for item_data in data.items:
        item = ProcurementItem(
            order_id=order.id,
            product_id=item_data.product_id,
            buyer_ordered_qty=item_data.buyer_ordered_qty,
            estimated_price=item_data.estimated_price,
            supplier_id=item_data.supplier_id,
            notes=item_data.notes,
        )
        db.add(item)
        if item_data.estimated_price:
            total_cost += item_data.buyer_ordered_qty * item_data.estimated_price

    order.total_estimated_cost = total_cost
    await db.commit()

    return {
        "id": str(order.id),
        "order_number": order.order_number,
        "status": ProcurementStatus.buyer_confirmed.value,
        "message": "Zakaz omborchiga yuborildi",
    }


@router.get("/")
async def list_procurement_orders(
    status: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    query = select(ProcurementOrder).order_by(ProcurementOrder.created_at.desc())

    # Enum filter — string ni enum ga convert qilamiz
    if status:
        try:
            status_enum = ProcurementStatus(status)
            query = query.where(ProcurementOrder.status == status_enum)
        except ValueError:
            # Noto'g'ri status — hammasi qaytariladi
            pass

    result = await db.execute(query)
    orders = result.scalars().all()
    return [order_to_dict(o) for o in orders]


@router.get("/{order_id}")
async def get_procurement_order(
    order_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    result = await db.execute(
        select(ProcurementOrder).where(ProcurementOrder.id == order_id)
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Zakaz topilmadi")

    items_result = await db.execute(
        select(ProcurementItem, Product.name, Product.unit)
        .join(Product, ProcurementItem.product_id == Product.id)
        .where(ProcurementItem.order_id == order_id)
    )
    items = items_result.all()

    result_dict = order_to_dict(order)
    result_dict["items"] = [
        {
            "id": str(item.id),
            "product_name": name,
            "unit": unit,
            "ai_recommended_qty": float(item.ai_recommended_qty or 0),
            "buyer_ordered_qty": float(item.buyer_ordered_qty or 0),
            "received_qty": float(item.received_qty or 0),
            "estimated_price": float(item.estimated_price or 0),
            "actual_price": float(item.actual_price or 0),
        }
        for item, name, unit in items
    ]
    return result_dict


@router.patch("/{order_id}/approve")
async def approve_order(
    order_id: UUID,
    notes: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("warehouse_manager", "admin"))
):
    result = await db.execute(
        select(ProcurementOrder).where(ProcurementOrder.id == order_id)
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Zakaz topilmadi")
    if order.status != ProcurementStatus.buyer_confirmed:
        raise HTTPException(
            status_code=400,
            detail=f"Bu zakaz tasdiqlanishi mumkin emas. Joriy holat: {order.status.value}"
        )

    order.status = ProcurementStatus.warehouse_approved
    order.warehouse_manager_id = current_user.id
    order.warehouse_notes = notes
    order.warehouse_approved_at = datetime.utcnow()
    await db.commit()

    return {
        "message": "Zakaz tasdiqlandi!",
        "status": ProcurementStatus.warehouse_approved.value
    }


@router.patch("/{order_id}/reject")
async def reject_order(
    order_id: UUID,
    notes: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("warehouse_manager", "admin"))
):
    result = await db.execute(
        select(ProcurementOrder).where(ProcurementOrder.id == order_id)
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Zakaz topilmadi")

    order.status = ProcurementStatus.rejected
    order.warehouse_manager_id = current_user.id
    order.warehouse_notes = notes
    await db.commit()

    return {
        "message": "Zakaz rad etildi",
        "status": ProcurementStatus.rejected.value
    }
