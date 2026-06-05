from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional
from uuid import UUID

from app.core.database import get_db
from app.core.security import get_current_user, require_roles
from app.models.models import Product, Category, User

router = APIRouter()


class ProductCreate(BaseModel):
    name: str
    unit: str = "kg"
    minimum_stock: float = 10
    purchase_price: float = 0
    selling_price: float = 0
    expiration_days: int = 7
    category_id: Optional[UUID] = None


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    unit: Optional[str] = None
    minimum_stock: Optional[float] = None
    purchase_price: Optional[float] = None
    selling_price: Optional[float] = None
    expiration_days: Optional[int] = None
    is_active: Optional[bool] = None


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
            "purchase_price": float(p.purchase_price),
            "expiration_days": p.expiration_days,
            "is_active": p.is_active,
        }
        for p in products
    ]


@router.post("/")
async def create_product(
    data: ProductCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "buyer", "goods_receiver"))
):
    # Kategoriya bo'lmasa, birinchisini olamiz
    cat_id = data.category_id
    if not cat_id:
        cat_r = await db.execute(select(Category).limit(1))
        cat = cat_r.scalar_one_or_none()
        cat_id = cat.id if cat else None

    product = Product(
        name=data.name,
        unit=data.unit,
        minimum_stock=data.minimum_stock,
        current_stock=0,
        purchase_price=data.purchase_price,
        selling_price=data.selling_price,
        expiration_days=data.expiration_days,
        category_id=cat_id,
        is_active=True,
    )
    db.add(product)
    await db.commit()
    await db.refresh(product)
    return {
        "id": str(product.id),
        "name": product.name,
        "message": "Mahsulot qo'shildi"
    }


@router.patch("/{product_id}")
async def update_product(
    product_id: UUID,
    data: ProductUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "buyer", "goods_receiver"))
):
    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Mahsulot topilmadi")

    if data.name is not None:
        product.name = data.name
    if data.unit is not None:
        product.unit = data.unit
    if data.minimum_stock is not None:
        product.minimum_stock = data.minimum_stock
    if data.purchase_price is not None:
        product.purchase_price = data.purchase_price
    if data.selling_price is not None:
        product.selling_price = data.selling_price
    if data.expiration_days is not None:
        product.expiration_days = data.expiration_days
    if data.is_active is not None:
        product.is_active = data.is_active

    await db.commit()
    return {"message": "Mahsulot yangilandi", "id": str(product.id)}


@router.delete("/{product_id}")
async def delete_product(
    product_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "buyer", "goods_receiver"))
):
    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Mahsulot topilmadi")

    product.is_active = False
    await db.commit()
    return {"message": "Mahsulot o'chirildi"}
