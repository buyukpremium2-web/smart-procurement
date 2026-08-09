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
from datetime import datetime, date, timedelta
import os
import httpx

from app.core.database import get_db
from app.models.models import Product, Category, Sale, User, StockMovement, MovementType, ProductBarcode

router = APIRouter()

# API kalit env dan yoki default
SYNC_API_KEY = os.getenv("SYNC_API_KEY", "BUYUK_PREMIUM_SECRET_2026")
log = logging.getLogger("sync1c")

# ─── BOZOR GURUHLARI ───────────────────────────────────
# Bozorchi/hisobotlar FAQAT shu guruhlarni ko'radi. Menejer hammasini ko'radi.
# Yangi guruh qo'shish/olib tashlash uchun shu ro'yxatni tahrirlang (kichik harflar, bo'sh joysiz).
def _norm_group(g) -> str:
    import re as _re
    return _re.sub(r"\s+", " ", str(g or "").strip().lower())

BOZOR_GURUHLARI = {_norm_group(x) for x in [
    "Винаграды", "Зелень", "Фрукты 2024", "Овощи", "Дыня и Арбуз",
    "Болгарский перец", "Капуста", "Картошка", "Лук", "Морков", "Помидор",
    "Абрикос", "Апельсины", "Груши", "Киви", "Клубника", "Персики",
    "Сухофрукты Местные", "Яблоко", "Мандарины", "Фрукты",
]}

def _is_bozor(group_name) -> bool:
    return _norm_group(group_name) in BOZOR_GURUHLARI

# 1C oxirgi yuborgan namunani xotirada saqlaymiz (tekshirish uchun)
_LAST_1C_SAMPLE = {"from-1c": None, "sales-from-1c": None}

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

    # products — yangi struktura: {"goods":[...], "barcodes":[...]} yoki oddiy ro'yxat
    prod_field = body.get("products") if isinstance(body, dict) else None
    barcodes_list = []
    if isinstance(prod_field, dict):
        products = prod_field.get("goods") or []
        barcodes_list = prod_field.get("barcodes") or []
    elif isinstance(prod_field, list):
        products = prod_field
    elif isinstance(body, list):
        products = body
    elif isinstance(body, dict):
        products = _pick(body, "tovarlar", "goods", "items", default=[])
    else:
        products = []
    if not isinstance(products, list):
        products = []
    if not isinstance(barcodes_list, list):
        barcodes_list = []
    if not products:
        # Bo'sh yoki tushunarsiz kelsa ham - xom body'ni saqlaymiz (1C nima yuboryapti ko'rish uchun)
        _keys = list(body.keys()) if isinstance(body, dict) else type(body).__name__
        log.info("from-1c: bo'sh products. body kalitlari=%s", _keys)
        _sample_body = body
        if isinstance(body, dict):
            _sample_body = {}
            for k, v in body.items():
                if isinstance(v, list):
                    _sample_body[k] = {"_tur": "ro'yxat", "_soni": len(v),
                                        "_birinchi": v[0] if v else None}
                elif isinstance(v, dict):
                    # obyekt ichini to'liq ko'rsatamiz (shtrix/ostatka shu yerda ko'rinadi)
                    _sample_body[k] = {"_tur": "obyekt", "_kalitlari": list(v.keys()),
                                        "_toliq": v}
                else:
                    _sample_body[k] = str(v)[:200]
        _LAST_1C_SAMPLE["from-1c"] = {
            "vaqt": datetime.utcnow().isoformat(),
            "holat": "BO'SH yoki tushunarsiz - products topilmadi",
            "body_kalitlari": _keys,
            "xom_body_namuna": _sample_body,
        }
        return {"message": "Mahsulot yo'q", "created": 0, "updated": 0}

    # NAMUNA: 1C aynan qanday maydonlar yuborayotganini saqlaymiz (shtrix/ostatka tekshirish)
    if products and isinstance(products[0], dict):
        log.info("from-1c NAMUNA maydonlar=%s | birinchi=%s",
                 list(products[0].keys()), products[0])
        _LAST_1C_SAMPLE["from-1c"] = {
            "vaqt": datetime.utcnow().isoformat(),
            "jami": len(products),
            "maydonlar": list(products[0].keys()),
            "birinchi_tovar": products[0],
        }

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
    guid_to_product = {}   # good_guid -> Product (shtrixlarni bog'lash uchun)

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
            guid = str(_pick(p, "good_guid", "guid", default="")).strip() or None
            group = _pick(p, "group_name", "group", "guruh")
            group = (str(group).strip() or None) if group is not None else None
            unit = normalize_unit(_pick(p, "unit", "birlik"))
            selling = float(_pick(p, "selling_price", "price", "narx", default=0) or 0)
            # ostatka (1C dan) — amount / ostatka / stock
            amount = _pick(p, "amount", "ostatka", "stock", "qoldiq", default=None)
            has_amount = amount is not None
            try:
                amount = float(amount) if has_amount else 0.0
            except Exception:
                amount, has_amount = 0.0, False

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
                if has_amount:
                    existing.current_stock = round(amount, 2)   # ostatka 1C dan
                existing.is_market = _is_bozor(group)           # bozor guruhimi
                existing.is_active = True
                existing.updated_at = datetime.utcnow()
                updated += 1
                prod_obj = existing
            else:
                prod_obj = Product(
                    name=name,
                    product_code=code,
                    group_name=group,
                    unit=unit,
                    minimum_stock=10,
                    current_stock=round(amount, 2) if has_amount else 0,
                    purchase_price=0,
                    last_purchase_price=0,
                    selling_price=selling,
                    expiration_days=7,
                    is_active=True,
                    is_market=_is_bozor(group),
                    category_id=default_cat_id,
                )
                db.add(prod_obj)
                created += 1
            if guid:
                guid_to_product[guid] = prod_obj
        except Exception as e:
            errors.append({"code": str(_pick(p, "code", "good_code", default="?")), "error": str(e)})

    await db.flush()  # yangi tovarlar id olishi uchun

    # ── SHTRIX-KODLAR (barcodes) ──
    bc_added = 0
    if barcodes_list:
        # mavjud shtrixlar to'plami (takror qo'shmaslik uchun)
        seen = set()
        ex_bc = await db.execute(select(ProductBarcode.product_id, ProductBarcode.barcode))
        for pid, bc in ex_bc.all():
            seen.add((str(pid), bc))
        for b in barcodes_list:
            if not isinstance(b, dict):
                continue
            g = str(b.get("good_guid") or "").strip()
            code_bc = str(b.get("barcode") or "").strip()
            if not g or not code_bc:
                continue
            prod = guid_to_product.get(g)
            if not prod:
                continue
            key = (str(prod.id), code_bc)
            if key in seen:
                continue
            db.add(ProductBarcode(product_id=prod.id, barcode=code_bc))
            seen.add(key)
            bc_added += 1

    await db.commit()
    log.info("from-1c: received=%s created=%s updated=%s barcodes+=%s",
             len(products), created, updated, bc_added)
    return {
        "message": "Sinxronizatsiya yakunlandi",
        "total_received": len(products),
        "created": created,
        "updated": updated,
        "barcodes_added": bc_added,
        "errors": errors[:10],
    }


@router.get("/last-sample")
async def last_sample(key: str = ""):
    """1C oxirgi yuborgan namunani ko'rish (brauzerda). Shtrix/ostatka bor-yo'qligini tekshirish."""
    if key != SYNC_API_KEY:
        raise HTTPException(status_code=403, detail="key noto'g'ri")
    return {
        "izoh": "1C oxirgi yuborgan namuna. 'maydonlar' ro'yxatida barcode/shtrix/ostatka bor-yo'qligini ko'ring.",
        "tovarlar_namunasi": _LAST_1C_SAMPLE.get("from-1c") or "Hali from-1c kelmadi",
        "sotuvlar_namunasi": _LAST_1C_SAMPLE.get("sales-from-1c") or "Hali sales-from-1c kelmadi",
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
    if sales and isinstance(sales[0], dict):
        _LAST_1C_SAMPLE["sales-from-1c"] = {
            "vaqt": datetime.utcnow().isoformat(),
            "jami": len(sales),
            "maydonlar": list(sales[0].keys()),
            "birinchi_sotuv": sales[0],
        }
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

    # Barcha tovarlarni normalizatsiyalangan kod bo'yicha xaritaga olamiz.
    # (Kod ichidagi \xa0 / probel farqi tufayli sotuv tashlanmasin. Bir marta yuklanadi.)
    _pc = await db.execute(select(Product.id, Product.product_code, Product.selling_price))
    by_norm_code = {}
    for _pid, _pcode, _pprice in _pc.all():
        if _pcode:
            by_norm_code[_norm_code(_pcode)] = (_pid, float(_pprice or 0))

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

            # Tovarni NORMALIZATSIYALANGAN kod bo'yicha topamiz (probel/\xa0 farqi yo'q)
            prod = by_norm_code.get(_norm_code(code))
            if not prod:
                errors.append({"code": code, "error": "Tovar topilmadi (sayt da yo'q)"})
                continue
            product_id, product_price = prod

            # Sana + aniq vaqt (soatlik hisobot uchun sold_at)
            sale_date = date.today()
            sold_at = None
            _sd = _pick(s, "sale_date", "sana", "date")
            if _sd:
                try:
                    _dt = datetime.fromisoformat(str(_sd).replace("Z", ""))
                    sale_date = _dt.date()
                    sold_at = _dt
                except Exception:
                    pass

            doc_number = _pick(s, "doc_number", "doc", "chek", "check_number")
            doc_number = str(doc_number).strip() if doc_number not in (None, "") else None

            # Takrorlanmaslik: doc_number + product + SANA bo'yicha.
            # (Sana qo'shildi: 1C hujjat raqamini kunlar bo'yicha qayta ishlatsa,
            #  boshqa kundagi sotuv "takror" deb o'chib qolmasin. Keng oynani
            #  qayta yuborish xavfsiz bo'ladi.)
            if doc_number:
                dup_r = await db.execute(
                    select(Sale).where(
                        Sale.product_id == product_id,
                        Sale.notes == f"1C #{doc_number}",
                        Sale.sale_date == sale_date,
                    )
                )
                _existing = dup_r.scalar_one_or_none()
                if _existing:
                    # Eski yozuvda vaqt yo'q bo'lsa - qayta yuborishda to'ldiramiz
                    if sold_at is not None and getattr(_existing, "sold_at", None) is None:
                        _existing.sold_at = sold_at
                    skipped += 1
                    continue

            price = float(_pick(s, "unit_price", "narx", default=0) or product_price or 0)

            # Sotuv yozuvi
            sale = Sale(
                product_id=product_id,
                quantity=qty,
                unit_price=price,
                seller_id=sys_user.id,
                sale_date=sale_date,
                sold_at=sold_at,
                notes=f"1C #{doc_number}" if doc_number else "1C dan",
            )
            db.add(sale)

            # ESLATMA: ostatka endi 1C dan (from-1c amount) keladi - shu yerda kamaytirmaymiz
            # (aks holda ikki marta ayiriladi). Sotuv yozuvi faqat hisobot uchun saqlanadi.

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
    """Kodni solishtirish: barcha bo'sh joy (oddiy probel, \xa0 uzilmas probel, tab) olib tashlanadi."""
    return (str(c or "").replace("\xa0", "").replace("\t", "").replace("\n", "").replace(" ", "").strip())


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


# ===== NAPITKI (DocVision) webhook qabul qiluvchi =====
# DocVision hodisa bo'lganda shu URL ga JSON yuboradi. Biz kelgan xom xabarni
# saqlaymiz (ko'rish uchun), keyin strukturaga qarab integratsiya yozamiz.
_NAPITKI_SAMPLES = []
_REGOS_LAST_IID = None  # webhookdan olingan joriy integration ID


@router.post("/napitki-webhook")
async def napitki_webhook(request: Request):
    """DocVision webhook — kelgan XOM JSON ni saqlaydi (struktura ko'rish uchun)."""
    try:
        raw = await request.body()
        try:
            body = await request.json()
        except Exception:
            body = raw.decode("utf-8", "replace")
    except Exception as e:
        body = f"<o'qib bo'lmadi: {e}>"
    sample = {
        "vaqt": datetime.utcnow().isoformat(),
        "headers": {k: v for k, v in request.headers.items()},
        "query": dict(request.query_params),
        "body": body,
    }
    _NAPITKI_SAMPLES.insert(0, sample)
    del _NAPITKI_SAMPLES[10:]  # oxirgi 10 tasi
    # Joriy integration ID ni ushlab qolamiz (shlyuz uchun)
    global _REGOS_LAST_IID
    _iid = request.headers.get("connected-integration-id")
    if not _iid and isinstance(body, dict):
        _iid = body.get("connected_integration_id")
    if _iid:
        _REGOS_LAST_IID = _iid
    try:
        log.info("napitki-webhook keldi: %s", str(body)[:800])
    except Exception:
        pass
    return {"status": "ok"}


@router.get("/napitki-webhook")
async def napitki_webhook_verify():
    """DocVision URL ni tekshirsa (GET) - ok qaytaramiz."""
    return {"status": "ok"}


@router.get("/napitki-last")
async def napitki_last(key: str = ""):
    """Oxirgi kelgan napitki webhook xabarlarini ko'rsatadi (kalit bilan himoyalangan)."""
    if key != SYNC_API_KEY:
        raise HTTPException(status_code=403, detail="Noto'g'ri kalit")
    return {"jami": len(_NAPITKI_SAMPLES), "xabarlar": _NAPITKI_SAMPLES}


# ===== NAPITKI (REGOS) — tovarlarni tortib olish (PULL) =====
# REGOS shlyuzi (token shart emas, integration ID kalit vazifasini o'taydi).
REGOS_BASE = os.getenv("REGOS_BASE", "https://integration.regos.uz/gateway/out")
REGOS_IID_DEFAULT = os.getenv("REGOS_IID", "22558da4cd4a48caa296fd3640560a61")


def _regos_iid(override=None):
    # ustunlik: qo'lda berilgan > webhookdan olingan > env default
    return (override or _REGOS_LAST_IID or REGOS_IID_DEFAULT)


async def _regos_post(method: str, body: dict, iid=None):
    url = f"{REGOS_BASE}/{_regos_iid(iid)}/v1/{method}"
    async with httpx.AsyncClient(timeout=90) as client:
        r = await client.post(url, json=body)
        r.raise_for_status()
        return r.json()


async def _regos_list(method: str, filters=None, iid=None):
    resp = await _regos_post(method, {"filters": filters or []}, iid=iid)
    if not resp.get("ok"):
        raise RuntimeError(f"{method}: {resp.get('result')}")
    return resp.get("result", []) or []


@router.get("/napitki-pull")
async def napitki_pull(key: str = "", iid: str = "", db: AsyncSession = Depends(get_db)):
    """REGOS napitki tovarlarini tortib bazaga yozadi (is_market=false, R- prefiks).
    iid berilmasa - webhookdan olingan yoki env dagi ID ishlatiladi.
    Har 10 daqiqada cron (cron-job.org / Railway) bilan chaqiring."""
    if key != SYNC_API_KEY:
        raise HTTPException(status_code=403, detail="key noto'g'ri")
    iid = iid or None

    # 1) Tovarlar katalogi (docsale/get)
    try:
        items = await _regos_list("item/get", iid=iid)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"REGOS item xato (iid={_regos_iid(iid)}): {e}")

    # 2) Narxlar (itemprice/get, price_type_id=1) -> {item_id: value}
    price_map = {}
    try:
        prices = await _regos_list(
            "itemprice/get",
            [{"field": "price_type_id", "operator": "Equal", "value": "1"}],
            iid=iid,
        )
        for pr in prices:
            price_map[pr.get("item_id")] = float(pr.get("value") or 0)
    except Exception as e:
        log.warning("REGOS narx xato: %s", e)

    # 3) Default kategoriya (FK uchun)
    cat_r = await db.execute(select(Category).limit(1))
    cat = cat_r.scalar_one_or_none()
    if not cat:
        cat = Category(name="Default")
        db.add(cat)
        await db.flush()
    default_cat_id = cat.id

    # Mavjud R- tovarlar (kod bo'yicha xarita)
    ex_r = await db.execute(select(Product).where(Product.product_code.like("R-%")))
    by_code = {p.product_code: p for p in ex_r.scalars().all()}

    # Band shtrixlar (Product.barcode unique bo'lgani uchun)
    used_bc_r = await db.execute(select(Product.barcode).where(Product.barcode.isnot(None)))
    used_barcodes = set(b for (b,) in used_bc_r.all() if b)

    # Mavjud ProductBarcode juftliklari (takror qo'shmaslik)
    ex_pb = await db.execute(select(ProductBarcode.product_id, ProductBarcode.barcode))
    pb_seen = set((str(pid), bc) for pid, bc in ex_pb.all())

    created = updated = bc_added = 0
    new_products = []  # (Product, barcode) - flush dan keyin ProductBarcode qo'shish uchun

    for it in items:
        try:
            if not isinstance(it, dict):
                continue
            code = it.get("code")
            if code is None:
                continue
            pcode = f"R-{code}"
            name = (it.get("name") or "").strip()
            if not name:
                continue
            rid = it.get("id")
            barcode = (it.get("base_barcode") or "").replace("\xa0", "").replace(" ", "").strip()
            grp = it.get("group") or {}
            group_name = (grp.get("name") or "Напитки")[:100]
            u = it.get("unit") or {}
            unit = "dona" if u.get("type") == "pcs" else ((u.get("name") or "dona")[:20])
            price = round(price_map.get(rid, 0), 2)

            existing = by_code.get(pcode)
            if existing:
                existing.name = name
                existing.group_name = group_name
                existing.unit = unit
                if price > 0:
                    existing.selling_price = price
                existing.is_market = False
                existing.is_active = True
                existing.updated_at = datetime.utcnow()
                if barcode and not existing.barcode and barcode not in used_barcodes:
                    existing.barcode = barcode
                    used_barcodes.add(barcode)
                updated += 1
                if barcode:
                    kp = (str(existing.id), barcode)
                    if kp not in pb_seen:
                        db.add(ProductBarcode(product_id=existing.id, barcode=barcode))
                        pb_seen.add(kp)
                        bc_added += 1
            else:
                set_bc = barcode if (barcode and barcode not in used_barcodes) else None
                if set_bc:
                    used_barcodes.add(set_bc)
                prod = Product(
                    name=name,
                    product_code=pcode,
                    group_name=group_name,
                    unit=unit,
                    minimum_stock=10,
                    current_stock=0,
                    purchase_price=0,
                    last_purchase_price=0,
                    selling_price=price,
                    expiration_days=30,
                    is_active=True,
                    is_market=False,
                    barcode=set_bc,
                    category_id=default_cat_id,
                )
                db.add(prod)
                by_code[pcode] = prod
                new_products.append((prod, barcode))
                created += 1
        except Exception as e:
            log.warning("napitki item xato: %s", e)

    await db.flush()  # yangi tovarlar id olishi uchun

    for prod, barcode in new_products:
        if barcode:
            kp = (str(prod.id), barcode)
            if kp not in pb_seen:
                db.add(ProductBarcode(product_id=prod.id, barcode=barcode))
                pb_seen.add(kp)
                bc_added += 1

    await db.commit()
    log.info("napitki-pull: items=%s created=%s updated=%s bc+=%s", len(items), created, updated, bc_added)
    return {
        "message": "REGOS napitki sinxronizatsiya yakunlandi",
        "jami_tovar": len(items),
        "narxlar_topildi": len(price_map),
        "yaratildi": created,
        "yangilandi": updated,
        "shtrix_qoshildi": bc_added,
    }


# ===== NAPITKI (REGOS) — CHEK SAVDOSI (Variant A: chek summasi -> Umumiy Savdo) =====
def _ts_from_local_date(y, m, d):
    """Toshkent (UTC+5) sanasining 00:00 ini Unix timestamp ga (UTC)."""
    return int((datetime(y, m, d) - timedelta(hours=5) - datetime(1970, 1, 1)).total_seconds())


@router.get("/napitki-sales-pull")
async def napitki_sales_pull(
    key: str = "",
    date_from: str = "",
    date_to: str = "",
    iid: str = "",
    db: AsyncSession = Depends(get_db),
):
    """REGOS cheklarini (doccheque/get) tortib, har chek summasini (amount) kunlik
    'Напитки (REGOS)' tovariga sotuv qilib yozadi. Umumiy Savdoda napitki savdosi ko'rinadi.
    Sana: date_from/date_to = 'YYYY-MM-DD' (bermasa - bugun). Oraliq max 1 oy."""
    if key != SYNC_API_KEY:
        raise HTTPException(status_code=403, detail="key noto'g'ri")
    iid = iid or None

    local_today = (datetime.utcnow() + timedelta(hours=5)).date()

    def _pd(x):
        y, m, d = x.split("-")
        return int(y), int(m), int(d)

    if date_from:
        y, m, d = _pd(date_from)
        start_ts = _ts_from_local_date(y, m, d)
    else:
        start_ts = _ts_from_local_date(local_today.year, local_today.month, local_today.day)
    if date_to:
        y, m, d = _pd(date_to)
        end_ts = _ts_from_local_date(y, m, d) + 86400
    else:
        end_ts = start_ts + 86400
    if end_ts - start_ts > 32 * 86400:
        raise HTTPException(status_code=400, detail="Oraliq 1 oydan oshmasin")

    # Sotuvchi (tizim) foydalanuvchi
    sys_r = await db.execute(select(User).where(User.username == "1c_system"))
    sys_user = sys_r.scalar_one_or_none()
    if not sys_user:
        admin_r = await db.execute(select(User).where(User.role == "admin").limit(1))
        sys_user = admin_r.scalar_one_or_none()
    if not sys_user:
        raise HTTPException(status_code=500, detail="Sotuvchi foydalanuvchi yo'q")

    # 'Напитки (REGOS)' umumiy tovari (chek summasi shunga yoziladi)
    np_r = await db.execute(select(Product).where(Product.product_code == "R-CHEQUE"))
    np = np_r.scalar_one_or_none()
    if not np:
        cat_r = await db.execute(select(Category).limit(1))
        cat = cat_r.scalar_one_or_none()
        if not cat:
            cat = Category(name="Default")
            db.add(cat)
            await db.flush()
        np = Product(
            name="Напитки (REGOS savdo)", product_code="R-CHEQUE", group_name="Напитки",
            unit="dona", minimum_stock=0, current_stock=0, purchase_price=0,
            last_purchase_price=0, selling_price=0, expiration_days=30,
            is_active=True, is_market=False, category_id=cat.id,
        )
        db.add(np)
        await db.flush()

    # Cheklarni tortamiz (sahifalab, next_offset bo'yicha)
    cheques = []
    offset = 0
    for _ in range(300):
        body = {"start_date": start_ts, "end_date": end_ts, "limit": 500, "offset": offset}
        try:
            resp = await _regos_post("doccheque/get", body, iid=iid)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"REGOS doccheque xato: {e}")
        if not resp.get("ok"):
            raise HTTPException(status_code=502, detail=f"REGOS doccheque: {resp.get('result')}")
        batch = resp.get("result", []) or []
        cheques.extend(batch)
        nxt = resp.get("next_offset") or 0
        if not batch or not nxt or nxt <= offset:
            break
        offset = nxt

    # Dedup (notes bo'yicha - REGOS #uuid)
    ex = await db.execute(select(Sale.notes).where(Sale.notes.like("REGOS #%")))
    seen = set(n for (n,) in ex.all())

    added = skipped = 0
    total_amount = 0.0
    for ch in cheques:
        try:
            if not isinstance(ch, dict):
                continue
            if ch.get("status") != "Closed" or ch.get("is_return"):
                continue
            uuid = str(ch.get("uuid") or "").strip()
            if not uuid:
                continue
            note = f"REGOS #{uuid}"
            if note in seen:
                skipped += 1
                continue
            amount = float(ch.get("amount") or 0)
            if amount <= 0:
                continue
            ts = int(ch.get("date") or 0)
            ldt = (datetime.utcfromtimestamp(ts) + timedelta(hours=5)) if ts else datetime.utcnow()
            db.add(Sale(
                product_id=np.id,
                quantity=1,
                unit_price=round(amount, 2),
                seller_id=sys_user.id,
                sale_date=ldt.date(),
                sold_at=ldt,
                notes=note,
            ))
            seen.add(note)
            added += 1
            total_amount += amount
        except Exception as e:
            log.warning("napitki chek xato: %s", e)

    await db.commit()
    log.info("napitki-sales-pull: cheklar=%s qoshildi=%s summa=%s", len(cheques), added, round(total_amount))
    return {
        "message": "REGOS napitki savdosi (chek summasi) yozildi",
        "cheklar_topildi": len(cheques),
        "qoshildi": added,
        "otkazildi_takror": skipped,
        "jami_summa": round(total_amount),
    }
