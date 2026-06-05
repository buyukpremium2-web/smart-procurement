"""
AI Forecasting Module
Uses statistical methods + Prophet for demand forecasting
"""
import pandas as pd
import numpy as np
from datetime import date, timedelta
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.models.models import Sale, ExtraOrder, Product, AIForecast


class ForecastResult:
    def __init__(
        self,
        product_id: str,
        current_stock: float,
        forecast_demand: float,
        safety_stock: float,
        recommended_order: float,
        confidence_score: float,
        extra_orders_qty: float,
        model_used: str,
    ):
        self.product_id = product_id
        self.current_stock = current_stock
        self.forecast_demand = forecast_demand
        self.safety_stock = safety_stock
        self.recommended_order = max(0, recommended_order)
        self.confidence_score = confidence_score
        self.extra_orders_qty = extra_orders_qty
        self.model_used = model_used


class AIForecastService:
    """
    Forecasting engine for fruit & vegetable procurement.
    
    Formula:
        recommended_order = forecast_demand + safety_stock + extra_orders - current_stock
    
    Models used (in priority order):
        1. Prophet (if enough data: 30+ days)
        2. Weighted moving average (7-30 days)
        3. Simple average (< 7 days)
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.safety_stock_factor = 0.25  # 25% buffer

    async def run_full_forecast(self) -> List[ForecastResult]:
        """Run AI forecast for all active products."""
        result = await self.db.execute(
            select(Product).where(Product.is_active == True)
        )
        products = result.scalars().all()

        forecasts = []
        for product in products:
            forecast = await self.forecast_product(product)
            forecasts.append(forecast)

            # Save to DB
            db_forecast = AIForecast(
                product_id=product.id,
                forecast_date=date.today(),
                current_stock=float(product.current_stock),
                forecast_demand=forecast.forecast_demand,
                safety_stock=forecast.safety_stock,
                recommended_order=forecast.recommended_order,
                confidence_score=forecast.confidence_score,
                extra_orders_qty=forecast.extra_orders_qty,
                model_used=forecast.model_used,
            )
            self.db.add(db_forecast)

        await self.db.commit()
        return forecasts

    async def forecast_product(self, product: Product) -> ForecastResult:
        """Forecast demand for a single product."""
        # Get sales history
        sales_data = await self._get_sales_history(str(product.id), days=90)
        extra_orders = await self._get_extra_orders(str(product.id))

        current_stock = float(product.current_stock)

        if len(sales_data) >= 30:
            forecast_demand, confidence, model = self._prophet_forecast(sales_data)
        elif len(sales_data) >= 7:
            forecast_demand, confidence, model = self._weighted_moving_average(sales_data)
        else:
            forecast_demand, confidence, model = self._simple_average(sales_data, product)

        safety_stock = forecast_demand * self.safety_stock_factor
        recommended_order = forecast_demand + safety_stock + extra_orders - current_stock

        return ForecastResult(
            product_id=str(product.id),
            current_stock=current_stock,
            forecast_demand=round(forecast_demand, 2),
            safety_stock=round(safety_stock, 2),
            recommended_order=round(recommended_order, 2),
            confidence_score=round(confidence, 3),
            extra_orders_qty=round(extra_orders, 2),
            model_used=model,
        )

    async def _get_sales_history(self, product_id: str, days: int = 90) -> pd.DataFrame:
        """Fetch sales history from DB."""
        start_date = date.today() - timedelta(days=days)
        result = await self.db.execute(
            select(Sale.sale_date, func.sum(Sale.quantity).label("qty"))
            .where(Sale.product_id == product_id, Sale.sale_date >= start_date)
            .group_by(Sale.sale_date)
            .order_by(Sale.sale_date)
        )
        rows = result.all()

        if not rows:
            return pd.DataFrame(columns=["ds", "y"])

        df = pd.DataFrame(rows, columns=["ds", "y"])
        df["ds"] = pd.to_datetime(df["ds"])
        df["y"] = df["y"].astype(float)
        return df

    async def _get_extra_orders(self, product_id: str) -> float:
        """Get pending extra orders quantity."""
        result = await self.db.execute(
            select(func.sum(ExtraOrder.quantity))
            .where(
                ExtraOrder.product_id == product_id,
                ExtraOrder.is_fulfilled == False,
                ExtraOrder.delivery_date >= date.today()
            )
        )
        total = result.scalar()
        return float(total or 0)

    def _prophet_forecast(self, df: pd.DataFrame):
        """Prophet-based forecasting for 30+ days of data."""
        try:
            from prophet import Prophet
            model = Prophet(
                yearly_seasonality=False,
                weekly_seasonality=True,
                daily_seasonality=False,
                changepoint_prior_scale=0.05,
            )
            model.fit(df)
            future = model.make_future_dataframe(periods=7)
            forecast = model.predict(future)
            next_7_days = forecast.tail(7)["yhat"].sum()
            demand_7_days = max(0, next_7_days)

            # Confidence based on data size
            confidence = min(0.95, 0.6 + (len(df) / 100) * 0.35)
            return demand_7_days, confidence, "prophet"

        except ImportError:
            return self._weighted_moving_average(df)

    def _weighted_moving_average(self, df: pd.DataFrame):
        """Weighted moving average - recent days weighted more."""
        if len(df) == 0:
            return 0, 0.3, "default"

        values = df["y"].values
        n = len(values)
        # Recent data gets higher weights
        weights = np.arange(1, n + 1)
        wma = np.average(values, weights=weights)
        daily_demand = wma
        weekly_demand = daily_demand * 7

        confidence = 0.5 + min(0.3, n / 100)
        return weekly_demand, confidence, "weighted_moving_average"

    def _simple_average(self, df: pd.DataFrame, product: Product):
        """Simple average or minimum stock-based fallback."""
        if len(df) > 0:
            avg_daily = df["y"].mean()
            weekly_demand = avg_daily * 7
            confidence = 0.3
        else:
            # Use minimum stock as baseline
            weekly_demand = float(product.minimum_stock) * 2
            confidence = 0.2

        return weekly_demand, confidence, "simple_average"
