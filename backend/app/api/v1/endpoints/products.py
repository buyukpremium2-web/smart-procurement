from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel
from typing import Optional
from uuid import UUID

from app.core.database import get_db
from app.core.security import get_current_user, require_roles
from app.models.models import Product, Category, User, ProductBarcode

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
    scope: str = Query("bozor", description="'bozor' = faqat bozor guruhlari, 'all' = hamma (menejer)"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    q = select(Product).where(Product.is_active == True)
    if scope != "all":
        # Bozorchi/oddiy: faqat bozor guruhlari
        q = q.where(Product.is_market == True)
    q = q.order_by(Product.name)
    result = await db.execute(q)
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
            "is_market": p.is_market,
        }
        for p in products
    ]


@router.get("/by-barcode/{barcode}")
async def product_by_barcode(
    barcode: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Skaner uchun: shtrix-kod bo'yicha tovarni topish (menejer - hamma tovar)."""
    code = (barcode or "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="Shtrix-kod bo'sh")

    # 1) product_barcodes jadvalidan (1C shtrixlari)
    r = await db.execute(
        select(Product).join(ProductBarcode, ProductBarcode.product_id == Product.id)
        .where(ProductBarcode.barcode == code, Product.is_active == True).limit(1)
    )
    p = r.scalar_one_or_none()
    # 2) topilmasa - Product.barcode ustunidan
    if not p:
        r2 = await db.execute(
            select(Product).where(Product.barcode == code, Product.is_active == True).limit(1)
        )
        p = r2.scalar_one_or_none()
    # 3) topilmasa - kod bo'yicha (product_code)
    if not p:
        r3 = await db.execute(
            select(Product).where(Product.product_code == code, Product.is_active == True).limit(1)
        )
        p = r3.scalar_one_or_none()

    if not p:
        raise HTTPException(status_code=404, detail="Bu shtrix-kodli tovar topilmadi")

    # tovarning barcha shtrixlari
    bcs_r = await db.execute(select(ProductBarcode.barcode).where(ProductBarcode.product_id == p.id))
    bcs = [b for (b,) in bcs_r.all()]

    return {
        "id": str(p.id),
        "name": p.name,
        "product_code": p.product_code or "",
        "group_name": p.group_name or "",
        "unit": p.unit,
        "current_stock": float(p.current_stock),
        "minimum_stock": float(p.minimum_stock),
        "selling_price": float(p.selling_price),
        "purchase_price": float(p.purchase_price),
        "is_market": p.is_market,
        "barcodes": bcs,
        "scanned": code,
    }


@router.get("/{product_id}/label")
async def product_label_info(
    product_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Ценник (narx yorlig'i) uchun tovar ma'lumoti: nom, narx, birlik, kod, shtrix."""
    r = await db.execute(select(Product).where(Product.id == product_id))
    p = r.scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="Tovar topilmadi")
    bcs_r = await db.execute(select(ProductBarcode.barcode).where(ProductBarcode.product_id == p.id))
    bcs = [b for (b,) in bcs_r.all()]
    if not bcs and p.barcode:
        bcs = [p.barcode]
    return {
        "id": str(p.id),
        "name": p.name,
        "product_code": p.product_code or "",
        "unit": p.unit,
        "selling_price": float(p.selling_price),
        "barcode": bcs[0] if bcs else (p.barcode or p.product_code or ""),
        "barcodes": bcs,
    }


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
