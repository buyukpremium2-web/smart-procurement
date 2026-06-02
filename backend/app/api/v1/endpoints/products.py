from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import Product, User

router = APIRouter()

@router.get("/")
async def list_products(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    result = await db.execute(select(Product).where(Product.is_active == True).order_by(Product.name))
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
            "is_active": p.is_active,
        }
        for p in products
    ]
