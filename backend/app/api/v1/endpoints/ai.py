from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import date

from app.core.database import get_db
from app.core.security import get_current_user, require_roles
from app.models.models import User, AIForecast, Product
from app.ai.forecasting import AIForecastService

router = APIRouter()


@router.post("/run-forecast")
async def run_ai_forecast(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "buyer"))
):
    """Barcha mahsulotlar uchun AI tahlil o'tkazish."""
    try:
        service = AIForecastService(db)
        forecasts = await service.run_full_forecast()
        return {
            "message": f"AI tahlili tugadi. {len(forecasts)} ta mahsulot tahlil qilindi.",
            "forecasts": [
                {
                    "product_id": f.product_id,
                    "current_stock": float(f.current_stock or 0),
                    "forecast_demand": float(f.forecast_demand or 0),
                    "safety_stock": float(f.safety_stock or 0),
                    "recommended_order": float(f.recommended_order or 0),
                    "extra_orders": float(f.extra_orders_qty or 0),
                    "confidence": float(f.confidence_score or 0),
                    "model": f.model_used,
                }
                for f in forecasts
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI tahlil xatolik: {str(e)}")


@router.get("/latest")
async def get_latest_forecasts(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Bugungi AI tavsiyalarini olish."""
    today = date.today()

    result = await db.execute(
        select(AIForecast, Product.name, Product.unit, Product.current_stock)
        .join(Product, AIForecast.product_id == Product.id)
        .where(AIForecast.forecast_date == today)
        .order_by(AIForecast.recommended_order.desc())
    )
    rows = result.all()

    if not rows:
        return []  # Bo'sh list — 404 emas

    return [
        {
            "product_name": str(name),
            "unit": str(unit),
            "current_stock": float(current_stock or 0),
            "forecast_demand": float(f.forecast_demand or 0),
            "safety_stock": float(f.safety_stock or 0),
            "recommended_order": float(f.recommended_order or 0),
            "extra_orders": float(f.extra_orders_qty or 0),
            "confidence": float(f.confidence_score or 0),
            "model": str(f.model_used or "unknown"),
        }
        for f, name, unit, current_stock in rows
    ]


@router.get("/health")
async def ai_health():
    """AI modul tekshiruvi."""
    checks = {}
    try:
        import pandas
        checks["pandas"] = pandas.__version__
    except ImportError:
        checks["pandas"] = "NOT INSTALLED"

    try:
        import numpy
        checks["numpy"] = numpy.__version__
    except ImportError:
        checks["numpy"] = "NOT INSTALLED"

    try:
        import prophet
        checks["prophet"] = "OK"
    except ImportError:
        checks["prophet"] = "NOT INSTALLED (will use fallback)"

    try:
        import sklearn
        checks["sklearn"] = sklearn.__version__
    except ImportError:
        checks["sklearn"] = "NOT INSTALLED"

    return {"status": "ok", "libraries": checks}
