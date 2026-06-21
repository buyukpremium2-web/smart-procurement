"""
1C dan integratsiya endpoint
- 1C dan POST /sync/from-1c orqali mahsulotlar keladi
- API key bilan himoyalangan
- Mavjud mahsulotlar yangilanadi (kod bo'yicha), yangilari qo'shiladi
"""
from fastapi import APIRouter, Depends, HTTPException, Header, Request
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, date
import os
import httpx

from app.core.database import get_db
from app.models.models import Product, Category, Sale, User, StockMovement, MovementType

router = APIRouter()

# API kalit env dan yoki default
SYNC_API_KEY = os.getenv("SYNC_API_KEY", "BUYUK_PREMIUM_SECRET_2026")
log = logging.getLogger("sync1c")

# ─── Bekzodjon 1C HTTP-servisi (PULL) ──────────────────
ONEC_BASE_URL = os.getenv("ONEC_BASE_URL", "http://185.181.165.61:54321/optimal_savdo/hs/shop")
ONEC_USER     = os.getenv("ONEC_USER", "webuser")
ONEC_PASS     = os.getenv("ONEC_PASS", "123")
# Sotuvlarni qancha orqaga olamiz (kun). Eski tarixni qayta tortmaslik uchun.
ONEC_SALES_LOOKBACK_DAYS = int(os.getenv("ONEC_SALES_LOOKBACK_DAYS", "1"))


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




def _pick(d, *keys, default=None):
    """dict dan bir nechta nom variantidan birinchi to'lganini oladi."""
    for k in keys:
        if isinstance(d, dict) and d.get(k) not in (None, ""):
            return d.get(k)
    return default


async def _read_body_and_key(request: Request, endpoint: str):
    """Xom JSON o'qiydi va api_key ni (body yoki header) qaytaradi. Xatoni logga yozadi."""
    try:
        body = await request.json()
    except Exception as e:
        raw = (await request.body()).decode("utf-8", "ignore")[:800]
        log.warning("%s JSON xato: %s | body=%s", endpoint, e, raw)
        raise HTTPException(status_code=400, detail="JSON o'qib bo'lmadi")
    api_key = None
    if isinstance(body, dict):
        api_key = _pick(body, "api_key", "apikey", "key", "API_KEY")
    api_key = api_key or request.headers.get("x-api-key") or request.headers.get("api-key")
    return body, api_key


@router.post("/from-1c")
async def sync_from_1c(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """1C dan mahsulotlarni qabul qilib bazani yangilash (moslashuvchan format)"""
    body, api_key = await _read_body_and_key(request, "from-1c")
    if api_key != SYNC_API_KEY:
        log.warning("from-1c noto'g'ri api_key: %r", api_key)
        raise HTTPException(status_code=403, detail="Noto'g'ri API kaliti")

    # products ro'yxati — har xil nom variantlari
    if isinstance(body, list):
        products = body
    elif isinstance(body, dict):
        products = _pick(body, "products", "tovarlar", "goods", "items", default=[])
    else:
        products = []
    if not isinstance(products, list):
        products = []
    if not products:
        log.info("from-1c: bo'sh products. body kalitlari=%s",
                 list(body.keys()) if isinstance(body, dict) else type(body).__name__)
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

    for p in products:
        if not isinstance(p, dict):
            continue
        try:
            code = str(_pick(p, "code", "good_code", "kod", default="")).strip()
            if not code:
                continue
            name = str(_pick(p, "name", "naimenovanie", "nom", default="")).strip()
            if not name:
                continue
            group = _pick(p, "group_name", "group", "guruh", "group_guid")
            group = (str(group).strip() or None) if group is not None else None
            unit = normalize_unit(_pick(p, "unit", "birlik"))
            selling = float(_pick(p, "selling_price", "price", "narx", default=0) or 0)

            existing_r = await db.execute(
                select(Product).where(Product.product_code == code)
            )
            existing = existing_r.scalar_one_or_none()

            if existing:
                existing.name = name
                if group:
                    existing.group_name = group
                existing.unit = unit
                if selling > 0:
                    existing.selling_price = selling
                existing.is_active = True
                existing.updated_at = datetime.utcnow()
                updated += 1
            else:
                new_prod = Product(
                    name=name,
                    product_code=code,
                    group_name=group,
                    unit=unit,
                    minimum_stock=10,
                    current_stock=0,
                    purchase_price=0,
                    last_purchase_price=0,
                    selling_price=selling,
                    expiration_days=7,
                    is_active=True,
                    category_id=default_cat_id,
                )
                db.add(new_prod)
                created += 1
        except Exception as e:
            errors.append({"code": str(_pick(p, "code", "good_code", default="?")), "error": str(e)})

    await db.commit()
    log.info("from-1c: received=%s created=%s updated=%s", len(products), created, updated)
    return {
        "message": "Sinxronizatsiya yakunlandi",
        "total_received": len(products),
        "created": created,
        "updated": updated,
        "errors": errors[:10],
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
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """1C dan sotilgan tovarlar — ostatkani kamaytiramiz (moslashuvchan format)"""
    body, api_key = await _read_body_and_key(request, "sales-from-1c")
    if api_key != SYNC_API_KEY:
        log.warning("sales-from-1c noto'g'ri api_key: %r", api_key)
        raise HTTPException(status_code=403, detail="Noto'g'ri API kaliti")

    if isinstance(body, list):
        sales = body
    elif isinstance(body, dict):
        sales = _pick(body, "sales", "savdo", "sotuvlar", "items", default=[])
    else:
        sales = []
    if not isinstance(sales, list):
        sales = []
    if not sales:
        log.info("sales-from-1c: bo'sh sales. body kalitlari=%s",
                 list(body.keys()) if isinstance(body, dict) else type(body).__name__)
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

    for s in sales:
        if not isinstance(s, dict):
            continue
        try:
            code = str(_pick(s, "code", "good_code", "kod", default="")).strip()
            qty = float(_pick(s, "quantity", "miqdor", "soni", default=0) or 0)
            if not code or qty <= 0:
                continue

            # Tovarni kod bo'yicha topamiz
            pr = await db.execute(select(Product).where(Product.product_code == code))
            product = pr.scalar_one_or_none()
            if not product:
                errors.append({"code": code, "error": "Tovar topilmadi (sayt da yo'q)"})
                continue

            # Sana
            sale_date = date.today()
            _sd = _pick(s, "sale_date", "sana", "date")
            if _sd:
                try:
                    sale_date = datetime.fromisoformat(str(_sd).replace("Z", "")).date()
                except Exception:
                    pass

            doc_number = _pick(s, "doc_number", "doc", "chek", "check_number")
            doc_number = str(doc_number).strip() if doc_number not in (None, "") else None

            # Takrorlanmaslik uchun: doc_number + product bo'yicha tekshirish
            if doc_number:
                dup_r = await db.execute(
                    select(Sale).where(
                        Sale.product_id == product.id,
                        Sale.notes == f"1C #{doc_number}",
                    )
                )
                if dup_r.scalar_one_or_none():
                    skipped += 1
                    continue

            price = float(_pick(s, "unit_price", "narx", default=0) or product.selling_price or 0)

            # Sotuv yozuvi
            sale = Sale(
                product_id=product.id,
                quantity=qty,
                unit_price=price,
                seller_id=sys_user.id,
                sale_date=sale_date,
                notes=f"1C #{doc_number}" if doc_number else "1C dan",
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
                    notes=f"1C sotuv #{doc_number or ''}",
                ))
            except Exception:
                pass

            processed += 1
        except Exception as e:
            errors.append({"code": str(_pick(s, "code", "good_code", default="?")), "error": str(e)})

    await db.commit()
    return {
        "message": "Sotuvlar qabul qilindi",
        "total_received": len(sales),
        "processed": processed,
        "skipped_duplicate": skipped,
        "errors": errors[:10],
    }


# ═══════════════════════════════════════════════════════════════
# PULL: backend o'zi 1C HTTP-servisidan tortib oladi (Bekzodjon usuli)
#   getTovarlar -> tovarlar,  getSavdo -> sotuvlar
# ═══════════════════════════════════════════════════════════════

def _norm_code(c) -> str:
    """Kodni solishtirish uchun normallashtirish: bo'sh joylarni olib tashlash."""
    return str(c or "").replace(" ", "").strip()


async def _onec_get(path: str):
    """1C HTTP-servisidan GET (Basic Auth)."""
    url = ONEC_BASE_URL.rstrip("/") + "/" + path.lstrip("/")
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.get(url, auth=(ONEC_USER, ONEC_PASS))
        r.raise_for_status()
        return r.json()


async def _pull_products(db: AsyncSession) -> dict:
    """1C getTovarlar -> tovarlarni qo'shish/yangilash (kod bo'yicha, bo'sh joysiz solishtirib)."""
    items = await _onec_get("getTovarlar")
    if not isinstance(items, list):
        return {"error": "getTovarlar ro'yxat qaytarmadi"}

    # default kategoriya
    cat_r = await db.execute(select(Category).limit(1))
    cat = cat_r.scalar_one_or_none()
    if not cat:
        cat = Category(name="Default")
        db.add(cat)
        await db.flush()
    default_cat_id = cat.id

    # mavjud tovarlar xaritasi: norm(kod) -> Product
    all_r = await db.execute(select(Product))
    by_code = {}
    for p in all_r.scalars().all():
        if p.product_code:
            by_code[_norm_code(p.product_code)] = p

    created = updated = 0
    for it in items:
        code = str(it.get("good_code") or "").strip()
        name = str(it.get("name") or "").strip()
        if not code or not name:
            continue
        nk = _norm_code(code)
        group = (str(it.get("group_name") or "").strip() or None)
        unit = normalize_unit(it.get("unit"))
        selling = float(it.get("selling_price") or 0)

        existing = by_code.get(nk)
        if existing:
            existing.name = name
            if group:
                existing.group_name = group
            existing.unit = unit
            if selling > 0:
                existing.selling_price = selling
            existing.is_active = True
            existing.updated_at = datetime.utcnow()
            updated += 1
        else:
            np = Product(
                name=name, product_code=code, group_name=group, unit=unit,
                minimum_stock=10, current_stock=0, purchase_price=0,
                last_purchase_price=0, selling_price=selling, expiration_days=7,
                is_active=True, category_id=default_cat_id,
            )
            db.add(np)
            by_code[nk] = np
            created += 1

    await db.commit()
    return {"received": len(items), "created": created, "updated": updated}


async def _pull_sales(db: AsyncSession) -> dict:
    """1C getSavdo -> sotuvlar (kod bo'yicha topib, ostatka kamaytirish, doc bo'yicha dedup)."""
    items = await _onec_get("getSavdo")
    if not isinstance(items, list):
        return {"error": "getSavdo ro'yxat qaytarmadi"}

    # tizim foydalanuvchi
    sys_r = await db.execute(select(User).where(User.username == "1c_system"))
    sys_user = sys_r.scalar_one_or_none()
    if not sys_user:
        admin_r = await db.execute(select(User).where(User.role == "admin").limit(1))
        sys_user = admin_r.scalar_one_or_none()
    if not sys_user:
        return {"error": "Sotuvchi foydalanuvchi yo'q"}

    # tovarlar xaritasi
    all_r = await db.execute(select(Product))
    by_code = {}
    for p in all_r.scalars().all():
        if p.product_code:
            by_code[_norm_code(p.product_code)] = p

    # mavjud 1C sotuvlari (dedup uchun): (product_id, notes)
    seen = set()
    ex_r = await db.execute(select(Sale.product_id, Sale.notes).where(Sale.notes.like("1C #%")))
    for pid, notes in ex_r.all():
        seen.add((str(pid), notes))

    cutoff = datetime.utcnow().date()
    try:
        from datetime import timedelta
        cutoff = (datetime.utcnow() - timedelta(days=ONEC_SALES_LOOKBACK_DAYS)).date()
    except Exception:
        pass

    processed = skipped = notfound = old = 0
    for s in items:
        code = str(s.get("good_code") or "").strip()
        qty = float(s.get("quantity") or 0)
        if not code or qty <= 0:
            continue
        product = by_code.get(_norm_code(code))
        if not product:
            notfound += 1
            continue

        sale_date = date.today()
        if s.get("sale_date"):
            try:
                sale_date = datetime.fromisoformat(str(s["sale_date"]).replace("Z", "")).date()
            except Exception:
                pass
        if sale_date < cutoff:
            old += 1
            continue

        doc = str(s.get("doc_number") or "").strip()
        notes = f"1C #{doc}" if doc else "1C dan"
        if doc and (str(product.id), notes) in seen:
            skipped += 1
            continue

        price = float(s.get("unit_price") or product.selling_price or 0)
        db.add(Sale(
            product_id=product.id, quantity=qty, unit_price=price,
            seller_id=sys_user.id, sale_date=sale_date, notes=notes,
        ))
        try:
            old_stock = float(product.current_stock or 0)
            product.current_stock = max(0, old_stock - qty)
            db.add(StockMovement(
                product_id=product.id, movement_type=MovementType.sale,
                quantity=-qty, stock_before=old_stock, stock_after=product.current_stock,
                created_by=sys_user.id, notes=f"1C sotuv #{doc}",
            ))
        except Exception:
            pass
        if doc:
            seen.add((str(product.id), notes))
        processed += 1

    await db.commit()
    return {"received": len(items), "processed": processed,
            "skipped_duplicate": skipped, "not_found": notfound, "too_old": old}


@router.get("/pull-from-1c")
async def pull_from_1c(key: str = "", db: AsyncSession = Depends(get_db)):
    """Qo'lda yoki scheduler orqali: 1C dan tovar+sotuvni tortib olish."""
    if key != SYNC_API_KEY:
        raise HTTPException(status_code=403, detail="key noto'g'ri")
    try:
        prod = await _pull_products(db)
    except Exception as e:
        prod = {"error": str(e)}
    try:
        sal = await _pull_sales(db)
    except Exception as e:
        sal = {"error": str(e)}
    return {"products": prod, "sales": sal}
