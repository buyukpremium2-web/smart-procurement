"""
1C dan integratsiya endpoint
- 1C dan POST /sync/from-1c orqali mahsulotlar keladi
- API key bilan himoyalangan
- Mavjud mahsulotlar yangilanadi (kod bo'yicha), yangilari qo'shiladi
"""
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import os

from app.core.database import get_db
from app.models.models import Product, Category

router = APIRouter()

# API kalit env dan yoki default
SYNC_API_KEY = os.getenv("SYNC_API_KEY", "BUYUK_PREMIUM_SECRET_2026")


class ProductFrom1C(BaseModel):
    code: str                                # 1C kod
    name: str                                # nomi
    group_name: Optional[str] = None         # guruh (papka)
    unit: Optional[str] = "kg"               # birlik
    purchase_price: Optional[float] = 0      # xarid narx
    selling_price: Optional[float] = 0       # sotuv narx
    current_stock: Optional[float] = None    # joriy ostatka (1C dan kelsa yangilanadi)


class Sync1CPayload(BaseModel):
    api_key: str
    products: List[ProductFrom1C]


def normalize_unit(u: Optional[str]) -> str:
    """1C dan kelgan birlikni bizning formatga keltirish"""
    if not u:
        return "kg"
    m = {
        "кг": "kg", "kg": "kg", "kilogramm": "kg",
        "шт": "dona", "dona": "dona", "штука": "dona",
        "л": "litr", "litr": "litr", "литр": "litr",
        "уп": "quti", "пакет": "quti", "коробка": "quti",
        "бог": "bog", "bog": "bog",
    }
    return m.get(u.strip().lower(), u.strip())


@router.post("/from-1c")
async def sync_from_1c(
    data: Sync1CPayload,
    db: AsyncSession = Depends(get_db),
):
    """1C dan mahsulotlarni qabul qilib bazani yangilash"""
    # 1. API kalit tekshirish
    if data.api_key != SYNC_API_KEY:
        raise HTTPException(status_code=403, detail="Noto'g'ri API kaliti")

    if not data.products:
        return {"message": "Mahsulot yo'q", "created": 0, "updated": 0}

    # 2. Default kategoriya (foreign key uchun)
    cat_r = await db.execute(select(Category).limit(1))
    cat = cat_r.scalar_one_or_none()
    if not cat:
        cat = Category(name="Default")
        db.add(cat)
        await db.flush()
    default_cat_id = cat.id

    created = 0
    updated = 0
    errors = []

    for p in data.products:
        try:
            code = (p.code or "").strip()
            if not code:
                continue
            name = (p.name or "").strip()
            if not name:
                continue

            # Mavjudmi tekshiramiz (kod bo'yicha)
            existing_r = await db.execute(
                select(Product).where(Product.product_code == code)
            )
            existing = existing_r.scalar_one_or_none()

            unit = normalize_unit(p.unit)
            purchase = float(p.purchase_price or 0)
            selling = float(p.selling_price or 0)

            if existing:
                # Yangilaymiz (faqat o'zgargan ma'lumotlarni)
                existing.name = name
                if p.group_name:
                    existing.group_name = p.group_name.strip()
                existing.unit = unit
                if purchase > 0:
                    existing.purchase_price = purchase
                    existing.last_purchase_price = purchase
                if selling > 0:
                    existing.selling_price = selling
                if p.current_stock is not None:
                    existing.current_stock = float(p.current_stock)
                existing.is_active = True
                existing.updated_at = datetime.utcnow()
                updated += 1
            else:
                # Yangi mahsulot qo'shamiz
                new_prod = Product(
                    name=name,
                    product_code=code,
                    group_name=(p.group_name or "").strip() or None,
                    unit=unit,
                    minimum_stock=10,
                    current_stock=float(p.current_stock) if p.current_stock is not None else 0,
                    purchase_price=purchase,
                    last_purchase_price=purchase,
                    selling_price=selling,
                    expiration_days=7,
                    is_active=True,
                    category_id=default_cat_id,
                )
                db.add(new_prod)
                created += 1
        except Exception as e:
            errors.append({"code": p.code, "error": str(e)})

    await db.commit()

    return {
        "message": "Sinxronizatsiya yakunlandi",
        "total_received": len(data.products),
        "created": created,
        "updated": updated,
        "errors": errors[:10],  # birinchi 10 ta xato
    }


@router.get("/status")
async def sync_status(
    x_api_key: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
):
    """1C tomon tekshirish uchun - sayt ishlayaptimi"""
    if x_api_key != SYNC_API_KEY:
        raise HTTPException(status_code=403, detail="API kaliti kerak")

    r = await db.execute(select(Product).where(Product.is_active == True))
    products = r.scalars().all()
    return {
        "status": "ok",
        "total_products": len(products),
        "with_code": len([p for p in products if p.product_code]),
        "groups": len(set(p.group_name for p in products if p.group_name)),
    }
