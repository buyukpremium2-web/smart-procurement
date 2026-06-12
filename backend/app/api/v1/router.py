from fastapi import APIRouter
from app.api.v1.endpoints import (
    auth, products, sales, extra_orders,
    procurement, ai, warehouse, receiving,
    notifications, dashboard, users, inventory, ledger, journal, sync, devices
)

api_router = APIRouter()

api_router.include_router(auth.router,        prefix="/auth",         tags=["Auth"])
api_router.include_router(users.router,       prefix="/users",        tags=["Users"])
api_router.include_router(products.router,    prefix="/products",     tags=["Products"])
api_router.include_router(sales.router,       prefix="/sales",        tags=["Sales"])
api_router.include_router(extra_orders.router,prefix="/extra-orders", tags=["Extra Orders"])
api_router.include_router(procurement.router, prefix="/procurement",  tags=["Procurement"])
api_router.include_router(ai.router,          prefix="/ai",           tags=["AI"])
api_router.include_router(warehouse.router,   prefix="/warehouse",    tags=["Warehouse"])
api_router.include_router(receiving.router,   prefix="/receiving",    tags=["Receiving"])
api_router.include_router(notifications.router,prefix="/notifications",tags=["Notifications"])
api_router.include_router(dashboard.router,   prefix="/dashboard",    tags=["Dashboard"])
api_router.include_router(inventory.router,   prefix="/inventory",    tags=["Inventory"])
api_router.include_router(ledger.router,      prefix="/ledger",       tags=["Ledger"])
api_router.include_router(journal.router,     prefix="/journal",      tags=["Journal"])
api_router.include_router(sync.router,        prefix="/sync",         tags=["1C Sync"])
api_router.include_router(devices.router,     prefix="/devices",      tags=["Devices"])
