from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import date
from typing import List, Optional
from pydantic import BaseModel
from uuid import UUID

from app.core.database import get_db
from app.core.security import get_current_user, require_roles
from app.models.models import Sale, Product, StockMovement, MovementType, User

router = APIRouter()


class SaleCreate(BaseModel):
    product_id: UUID
    quantity: float
    unit_price: float
    sale_date: Optional[date] = None
    notes: Optional[str] = None


class SaleResponse(BaseModel):
    id: str
    product_name: str
    quantity: float
    unit_price: float
    total_amount: float
    sale_date: date
    seller_name: str


@router.post("/", dependencies=[Depends(require_roles("seller", "admin"))])
async def create_sale(
    data: SaleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Check product exists and has stock
    result = await db.execute(select(Product).where(Product.id == data.product_id))
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Mahsulot topilmadi")
    if float(product.current_stock) < data.quantity:
        raise HTTPException(
            status_code=400,
            detail=f"Omborda yetarli mahsulot yo'q. Mavjud: {product.current_stock} {product.unit}"
        )

    stock_before = float(product.current_stock)

    # Create sale
    sale = Sale(
        product_id=data.product_id,
        quantity=data.quantity,
        unit_price=data.unit_price,
        seller_id=current_user.id,
        sale_date=data.sale_date or date.today(),
        notes=data.notes,
    )
    db.add(sale)

    # Update stock
    product.current_stock = stock_before - data.quantity

    # Log movement
    movement = StockMovement(
        product_id=data.product_id,
        movement_type=MovementType.outgoing,
        quantity=data.quantity,
        reference_type="sale",
        stock_before=stock_before,
        stock_after=float(product.current_stock),
        user_id=current_user.id,
    )
    db.add(movement)
    await db.commit()

    return {
        "id": str(sale.id),
        "message": "Sotuv muvaffaqiyatli kiritildi",
        "remaining_stock": float(product.current_stock)
    }


@router.get("/today")
async def get_today_sales(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    today = date.today()
    result = await db.execute(
        select(
            Sale,
            Product.name.label("product_name"),
            Product.unit,
        )
        .join(Product, Sale.product_id == Product.id)
        .where(Sale.sale_date == today)
        .order_by(Sale.created_at.desc())
    )
    rows = result.all()

    sales = []
    total_revenue = 0
    for sale, product_name, unit in rows:
        amount = float(sale.quantity) * float(sale.unit_price)
        total_revenue += amount
        sales.append({
            "id": str(sale.id),
            "product_name": product_name,
            "quantity": float(sale.quantity),
            "unit": unit,
            "unit_price": float(sale.unit_price),
            "total_amount": amount,
            "notes": sale.notes,
        })

    return {"sales": sales, "total_revenue": total_revenue, "count": len(sales)}


@router.get("/analytics")
async def sales_analytics(
    days: int = 30,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    from datetime import timedelta
    start_date = date.today() - timedelta(days=days)

    # Daily totals
    result = await db.execute(
        select(
            Sale.sale_date,
            func.sum(Sale.quantity * Sale.unit_price).label("revenue"),
            func.count(Sale.id).label("transactions"),
        )
        .where(Sale.sale_date >= start_date)
        .group_by(Sale.sale_date)
        .order_by(Sale.sale_date)
    )
    daily = result.all()

    # Top products
    top_result = await db.execute(
        select(
            Product.name,
            Product.unit,
            func.sum(Sale.quantity).label("total_qty"),
            func.sum(Sale.quantity * Sale.unit_price).label("total_revenue"),
        )
        .join(Sale, Sale.product_id == Product.id)
        .where(Sale.sale_date >= start_date)
        .group_by(Product.name, Product.unit)
        .order_by(func.sum(Sale.quantity * Sale.unit_price).desc())
        .limit(10)
    )
    top_products = top_result.all()

    return {
        "daily_sales": [
            {
                "date": str(row.sale_date),
                "revenue": float(row.revenue or 0),
                "transactions": row.transactions,
            }
            for row in daily
        ],
        "top_products": [
            {
                "name": row.name,
                "unit": row.unit,
                "total_qty": float(row.total_qty),
                "total_revenue": float(row.total_revenue),
            }
            for row in top_products
        ],
    }
