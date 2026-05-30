from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional
from pydantic import BaseModel
from uuid import UUID

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import Product, User

router = APIRouter()


class ProductCreate(BaseModel):
    name: str
    unit: str = "kg"
    minimum_stock: float = 10
    current_stock: float = 0
    purchase_price: float = 0
    selling_price: float = 0


@router.get("/")
async def list_products(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    result = await db.execute(
        select(Product).where(Product.is_active == True).order_by(Product.name)
    )
    products = result.scalars().all()
    return [
        {
            "id": str(p.id),
            "name": p.name,
            "unit": p.unit,
            "current_stock": float(p.current_stock),
            "minimum_stock": float(p.minimum_stock),
            "selling_price": float(p.selling_price),
        }
        for p in products
    ]


@router.get("/stock")
async def get_stock(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    result = await db.execute(
        select(Product).where(Product.is_active == True).order_by(Product.name)
    )
    products = result.scalars().all()
    return [
        {
            "id": str(p.id),
            "name": p.name,
            "unit": p.unit,
            "current_stock": float(p.current_stock),
            "minimum_stock": float(p.minimum_stock),
            "stock": float(p.current_stock),
            "min_stock": float(p.minimum_stock),
        }
        for p in products
    ]


@router.post("/")
async def create_product(
    data: ProductCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    product = Product(
        name=data.name,
        unit=data.unit,
        minimum_stock=data.minimum_stock,
        current_stock=data.current_stock,
        purchase_price=data.purchase_price,
        selling_price=data.selling_price,
        is_active=True,
    )
    db.add(product)
    await db.commit()
    return {"message": "Mahsulot yaratildi", "id": str(product.id)}
