"""
Savdo hisoboti endpointlari.

GET /api/v1/reports/sales-summary?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD&scope=all|bozor
  - date_from/date_to berilmasa -> BUGUNGI kun (default).
  - Umumiy savdo summasi, dona, sotuv qatorlari, cheklar soni, o'rtacha chek.
  - Kunlar kesimida seriya (diagramma uchun).
  - Guruhlar (group_name) bo'yicha savdo, dona va ulush (%).
  - Foyda/marja: FAQAT tannarxi (purchase_price>0) bor tovarlar bo'yicha hisoblanadi.
    Hozir 1C tannarx yubormaydi (34523 tadan ~33 tasida bor), shuning uchun qamrov
    kichik. Bekzod 1C feed'iga cost qo'shib, u Product.purchase_price ga yozilgach,
    foyda/marja avtomat to'liq ishlaydi - bu kod o'zgarmaydi.

To'lov turi (naqd/karta) hozircha YO'Q - 1C sales feed'ida payment_type yo'q.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from datetime import date
from typing import Optional

from app.core.database import get_db
from app.models.models import Sale, Product

router = APIRouter()


def _resolve_range(date_from: Optional[date], date_to: Optional[date]):
    today = date.today()
    if date_to is None:
        date_to = today
    if date_from is None:
        date_from = date_to
    if date_from > date_to:
        date_from, date_to = date_to, date_from
    return date_from, date_to


def _f(x) -> float:
    try:
        return round(float(x or 0), 2)
    except Exception:
        return 0.0


@router.get("/sales-summary")
async def sales_summary(
    date_from: Optional[date] = Query(None, description="YYYY-MM-DD (bo'sh -> bugun)"),
    date_to: Optional[date] = Query(None, description="YYYY-MM-DD (bo'sh -> bugun)"),
    scope: str = Query("all", description="all yoki bozor"),
    db: AsyncSession = Depends(get_db),
):
    date_from, date_to = _resolve_range(date_from, date_to)

    amount = Sale.quantity * Sale.unit_price
    filters = [Sale.sale_date >= date_from, Sale.sale_date <= date_to]
    bozor_only = (scope == "bozor")

    def _scoped(q):
        return q.where(Product.is_market.is_(True)) if bozor_only else q

    # ── Umumiy ko'rsatkichlar ──────────────────────────────────────────
    totals_q = _scoped(
        select(
            func.coalesce(func.sum(amount), 0),
            func.coalesce(func.sum(Sale.quantity), 0),
            func.count(Sale.id),
            func.count(func.distinct(Sale.notes)),
        )
        .select_from(Sale).join(Product, Product.id == Sale.product_id)
        .where(and_(*filters))
    )
    t = (await db.execute(totals_q)).one()
    total_sales = _f(t[0])
    total_qty = _f(t[1])
    lines_count = int(t[2] or 0)
    receipts_count = int(t[3] or 0)
    avg_receipt = round(total_sales / receipts_count, 2) if receipts_count else 0.0

    # ── Foyda (faqat tannarxli tovarlar) ───────────────────────────────
    profit_expr = Sale.quantity * (Sale.unit_price - Product.purchase_price)
    prof_q = _scoped(
        select(
            func.coalesce(func.sum(profit_expr), 0),        # foyda (qamrov ichида)
            func.coalesce(func.sum(amount), 0),             # o'sha qamrovdagi savdo
            func.count(Sale.id),                            # nechta qator qamraldi
        )
        .select_from(Sale).join(Product, Product.id == Sale.product_id)
        .where(and_(*filters, Product.purchase_price > 0))
    )
    pr = (await db.execute(prof_q)).one()
    profit = _f(pr[0])
    profit_base_sales = _f(pr[1])
    profit_lines = int(pr[2] or 0)
    margin_pct = round(profit / profit_base_sales * 100, 1) if profit_base_sales else None
    if profit_lines == 0:
        profit = None
        margin_pct = None

    # ── Kunlar kesimida (diagramma) ────────────────────────────────────
    days_q = _scoped(
        select(Sale.sale_date, func.coalesce(func.sum(amount), 0))
        .select_from(Sale).join(Product, Product.id == Sale.product_id)
        .where(and_(*filters))
        .group_by(Sale.sale_date).order_by(Sale.sale_date)
    )
    days = [{"date": d.isoformat(), "value": _f(v)} for d, v in (await db.execute(days_q)).all()]

    # ── Guruhlar bo'yicha ──────────────────────────────────────────────
    group_q = _scoped(
        select(
            func.coalesce(Product.group_name, "—"),
            func.coalesce(func.sum(amount), 0),
            func.coalesce(func.sum(Sale.quantity), 0),
            func.count(Sale.id),
        )
        .select_from(Sale).join(Product, Product.id == Sale.product_id)
        .where(and_(*filters))
        .group_by(Product.group_name).order_by(func.sum(amount).desc())
    )
    groups = []
    for gname, gsales, gqty, glines in (await db.execute(group_q)).all():
        gs = _f(gsales)
        groups.append({
            "group": gname or "—",
            "sales": gs,
            "qty": _f(gqty),
            "lines": int(glines or 0),
            "share_pct": round(gs / total_sales * 100, 1) if total_sales else 0.0,
        })

    return {
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "scope": "bozor" if bozor_only else "all",
        "total_sales": total_sales,
        "total_qty": total_qty,
        "lines_count": lines_count,
        "receipts_count": receipts_count,
        "avg_receipt": avg_receipt,
        "profit": profit,                 # None -> tannarx yo'q
        "margin_pct": margin_pct,         # None -> tannarx yo'q
        "profit_lines": profit_lines,     # nechta sotuv qatori tannarxli edi
        "days": days,
        "groups": groups,
        "by_payment": None,               # 1C payment_type qo'shgach to'ladi
    }
