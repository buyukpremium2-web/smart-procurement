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
from datetime import datetime, date
import os

from app.core.database import get_db
from app.models.models import Product, Category, Sale, User, StockMovement, MovementType

router = APIRouter()

# API kalit env dan yoki default
SYNC_API_KEY = os.getenv("SYNC_API_KEY", "BUYUK_PREMIUM_SECRET_2026")


class ProductFrom1C(BaseModel):
    code: str                                # 1C kod
    name: str                                # nomi
    group_name: Optional[str] = None         # guruh (papka)
    unit: Optional[str] = "kg"               # birlik
    selling_price: Optional[float] = 0       # sotuv narxi (yangilanadi)


class Sync1CPayload(BaseModel):
    api_key: str
    products: List[ProductFrom1C]


# ─── SOTILGAN TOVARLAR (1C dan) ────────────────────────
class Sale1C(BaseModel):
    code: str                       # tovar kodi (1C kod)
    quantity: float                  # sotilgan miqdor
    unit_price: Optional[float] = 0  # sotuv narxi
    sale_date: Optional[str] = None  # 2026-06-12 yoki 2026-06-12T14:30
    doc_number: Optional[str] = None # 1C chek raqami (takror kelmaslik uchun)


class SalesPayload(BaseModel):
    api_key: str
    sales: List[Sale1C]


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
            selling = float(p.selling_price or 0)

            if existing:
                # Yangilaymiz (faqat nom, guruh, sotuv narx)
                existing.name = name
                if p.group_name:
                    existing.group_name = p.group_name.strip()
                existing.unit = unit
                if selling > 0:
                    existing.selling_price = selling
                # current_stock va purchase_price YO'Q - sayt o'zi yuritadi
                existing.is_active = True
                existing.updated_at = datetime.utcnow()
                updated += 1
            else:
                # Yangi mahsulot qo'shamiz (ostatka 0, kirim narx 0)
                new_prod = Product(
                    name=name,
                    product_code=code,
                    group_name=(p.group_name or "").strip() or None,
                    unit=unit,
                    minimum_stock=10,
                    current_stock=0,                  # ostatka sayt orqali (tovaroved qabul qiladi)
                    purchase_price=0,                 # kirim narx sayt orqali kiritiladi
                    last_purchase_price=0,
                    selling_price=selling,            # sotuv narxi 1C dan
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


# ─── SOTUVLARNI 1C DAN QABUL QILISH ────────────────────
@router.post("/sales-from-1c")
async def sales_from_1c(
    data: SalesPayload,
    db: AsyncSession = Depends(get_db),
):
    """1C dan sotilgan tovarlar — ostatkani kamaytiramiz"""
    if data.api_key != SYNC_API_KEY:
        raise HTTPException(status_code=403, detail="Noto'g'ri API kaliti")

    if not data.sales:
        return {"message": "Sotuv yo'q", "processed": 0}

    # 1C-tizim foydalanuvchi (sotuvlarni shu nomdan yozamiz)
    sys_r = await db.execute(select(User).where(User.username == "1c_system"))
    sys_user = sys_r.scalar_one_or_none()
    if not sys_user:
        # Yo'q bo'lsa - admin ni olamiz
        admin_r = await db.execute(select(User).where(User.role == "admin").limit(1))
        sys_user = admin_r.scalar_one_or_none()
    if not sys_user:
        raise HTTPException(status_code=500, detail="Sotuvchi foydalanuvchi yo'q")

    processed = 0
    skipped = 0
    errors = []

    for s in data.sales:
        try:
            code = (s.code or "").strip()
            if not code or s.quantity <= 0:
                continue

            # Tovarni kod bo'yicha topamiz
            pr = await db.execute(select(Product).where(Product.product_code == code))
            product = pr.scalar_one_or_none()
            if not product:
                errors.append({"code": code, "error": "Tovar topilmadi (sayt da yo'q)"})
                continue

            # Sana
            sale_date = date.today()
            if s.sale_date:
                try:
                    sale_date = datetime.fromisoformat(s.sale_date.replace("Z", "")).date()
                except:
                    pass

            # Takrorlanmaslik uchun: doc_number + product + sana bo'yicha tekshirish
            if s.doc_number:
                dup_r = await db.execute(
                    select(Sale).where(
                        Sale.product_id == product.id,
                        Sale.notes == f"1C #{s.doc_number}",
                    )
                )
                if dup_r.scalar_one_or_none():
                    skipped += 1
                    continue

            qty = float(s.quantity)
            price = float(s.unit_price or product.selling_price or 0)

            # Sotuv yozuvi
            sale = Sale(
                product_id=product.id,
                quantity=qty,
                unit_price=price,
                seller_id=sys_user.id,
                sale_date=sale_date,
                notes=f"1C #{s.doc_number}" if s.doc_number else "1C dan",
            )
            db.add(sale)

            # Ostatkani kamaytiramiz
            try:
                old_stock = float(product.current_stock or 0)
                product.current_stock = max(0, old_stock - qty)
                db.add(StockMovement(
                    product_id=product.id,
                    movement_type=MovementType.sale,
                    quantity=-qty,
                    stock_before=old_stock,
                    stock_after=product.current_stock,
                    created_by=sys_user.id,
                    notes=f"1C sotuv #{s.doc_number or ''}",
                ))
            except Exception:
                pass

            processed += 1
        except Exception as e:
            errors.append({"code": s.code, "error": str(e)})

    await db.commit()
    return {
        "message": "Sotuvlar qabul qilindi",
        "total_received": len(data.sales),
        "processed": processed,
        "skipped_duplicate": skipped,
        "errors": errors[:10],
    }
