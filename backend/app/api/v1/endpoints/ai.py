from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user, require_roles
from app.models.models import User
from app.ai.forecasting import AIForecastService

router = APIRouter()


@router.post("/run-forecast", dependencies=[Depends(require_roles("admin", "buyer"))])
async def run_ai_forecast(
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Trigger full AI forecast for all products."""
    service = AIForecastService(db)
    forecasts = await service.run_full_forecast()

    return {
        "message": f"AI tahlili tugadi. {len(forecasts)} ta mahsulot tahlil qilindi.",
        "forecasts": [
            {
                "product_id": f.product_id,
                "current_stock": f.current_stock,
                "forecast_demand": f.forecast_demand,
                "safety_stock": f.safety_stock,
                "recommended_order": f.recommended_order,
                "extra_orders": f.extra_orders_qty,
                "confidence": f"{f.confidence_score * 100:.0f}%",
                "model": f.model_used,
            }
            for f in forecasts
        ]
    }


@router.get("/latest")
async def get_latest_forecasts(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get latest AI forecast results."""
    from sqlalchemy import select, func
    from app.models.models import AIForecast, Product
    from datetime import date

    result = await db.execute(
        select(AIForecast, Product.name, Product.unit, Product.current_stock)
        .join(Product, AIForecast.product_id == Product.id)
        .where(AIForecast.forecast_date == date.today())
        .order_by(AIForecast.recommended_order.desc())
    )
    rows = result.all()

    return [
        {
            "product_name": name,
            "unit": unit,
            "current_stock": float(current_stock),
            "forecast_demand": float(f.forecast_demand or 0),
            "safety_stock": float(f.safety_stock or 0),
            "recommended_order": float(f.recommended_order or 0),
            "extra_orders": float(f.extra_orders_qty or 0),
            "confidence": float(f.confidence_score or 0),
            "model": f.model_used,
        }
        for f, name, unit, current_stock in rows
    ]
