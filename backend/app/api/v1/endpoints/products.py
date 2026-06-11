from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel
from typing import Optional
from uuid import UUID

from app.core.database import get_db
from app.core.security import get_current_user, require_roles
from app.models.models import Product, Category, User

router = APIRouter()


class ProductCreate(BaseModel):
    name: str
    product_code: Optional[str] = None
    group_name: Optional[str] = None
    unit: str = "kg"
    minimum_stock: float = 10
    purchase_price: float = 0
    selling_price: float = 0
    expiration_days: int = 7
    category_id: Optional[UUID] = None


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    product_code: Optional[str] = None
    group_name: Optional[str] = None
    unit: Optional[str] = None
    minimum_stock: Optional[float] = None
    purchase_price: Optional[float] = None
    selling_price: Optional[float] = None
    expiration_days: Optional[int] = None
    is_active: Optional[bool] = None


async def gen_product_code(db: AsyncSession) -> str:
    """Avtomatik tovar kodi: M-0001, M-0002..."""
    r = await db.execute(select(func.count(Product.id)))
    count = (r.scalar() or 0) + 1
    return f"M-{count:04d}"


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
            "product_code": p.product_code or "",
            "group_name": p.group_name or "",
            "unit": p.unit,
            "current_stock": float(p.current_stock),
            "minimum_stock": float(p.minimum_stock),
            "selling_price": float(p.selling_price),
            "purchase_price": float(p.purchase_price),
            "last_purchase_price": float(p.last_purchase_price or 0),
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
    cat_id = data.category_id
    if not cat_id:
        cat_r = await db.execute(select(Category).limit(1))
        cat = cat_r.scalar_one_or_none()
        cat_id = cat.id if cat else None

    code = data.product_code or await gen_product_code(db)

    product = Product(
        name=data.name,
        product_code=code,
        group_name=data.group_name,
        unit=data.unit,
        minimum_stock=data.minimum_stock,
        current_stock=0,
        purchase_price=data.purchase_price,
        last_purchase_price=data.purchase_price,
        selling_price=data.selling_price,
        expiration_days=data.expiration_days,
        category_id=cat_id,
        is_active=True,
    )
    db.add(product)
    await db.commit()
    await db.refresh(product)
    return {"id": str(product.id), "name": product.name, "product_code": code, "message": "Mahsulot qo'shildi"}


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

    if data.name is not None: product.name = data.name
    if data.product_code is not None: product.product_code = data.product_code
    if data.group_name is not None: product.group_name = data.group_name
    if data.unit is not None: product.unit = data.unit
    if data.minimum_stock is not None: product.minimum_stock = data.minimum_stock
    if data.purchase_price is not None: product.purchase_price = data.purchase_price
    if data.selling_price is not None: product.selling_price = data.selling_price
    if data.expiration_days is not None: product.expiration_days = data.expiration_days
    if data.is_active is not None: product.is_active = data.is_active

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
