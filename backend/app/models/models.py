import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, Boolean, DateTime, Date, Numeric,
    Integer, ForeignKey, Text, Enum as SAEnum, BigInteger, JSON
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.core.database import Base
import enum


class UserRole(str, enum.Enum):
    admin = "admin"
    seller = "seller"
    buyer = "buyer"
    warehouse_manager = "warehouse_manager"
    goods_receiver = "goods_receiver"


class ProcurementStatus(str, enum.Enum):
    draft = "draft"
    ai_generated = "ai_generated"
    buyer_confirmed = "buyer_confirmed"
    warehouse_approved = "warehouse_approved"
    rejected = "rejected"
    receiving = "receiving"
    completed = "completed"


class MovementType(str, enum.Enum):
    initial = "initial"
    incoming = "in"
    outgoing = "out"
    waste = "waste"
    adjustment = "adjustment"


class User(Base):
    __tablename__ = "users"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    telegram_id = Column(BigInteger, unique=True, nullable=True)
    username = Column(String(100), unique=True, nullable=False)
    full_name = Column(String(200), nullable=False)
    phone = Column(String(20))
    role = Column(SAEnum(UserRole), nullable=False, default=UserRole.seller)
    hashed_password = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)


class Category(Base):
    __tablename__ = "categories"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    products = relationship("Product", back_populates="category")


class Supplier(Base):
    __tablename__ = "suppliers"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(200), nullable=False)
    phone = Column(String(20))
    address = Column(Text)
    rating = Column(Numeric(3, 2), default=5.0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class Product(Base):
    __tablename__ = "products"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(200), nullable=False)
    category_id = Column(UUID(as_uuid=True), ForeignKey("categories.id"))
    barcode = Column(String(100), unique=True, nullable=True)
    unit = Column(String(20), nullable=False, default="kg")
    supplier_id = Column(UUID(as_uuid=True), ForeignKey("suppliers.id"))
    minimum_stock = Column(Numeric(10, 2), nullable=False, default=10)
    current_stock = Column(Numeric(10, 2), nullable=False, default=0)
    purchase_price = Column(Numeric(10, 2), nullable=False, default=0)
    selling_price = Column(Numeric(10, 2), nullable=False, default=0)
    expiration_days = Column(Integer, default=7)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    category = relationship("Category", back_populates="products")
    supplier = relationship("Supplier")


class InventorySession(Base):
    """Admin tomonidan kunning boshida boshlangich ostatka kiritiladi"""
    __tablename__ = "inventory_sessions"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_date = Column(Date, nullable=False)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id"), nullable=False)
    initial_stock = Column(Numeric(10, 2), nullable=False, default=0)
    notes = Column(Text)
    admin_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    product = relationship("Product")
    admin = relationship("User")


class Sale(Base):
    __tablename__ = "sales"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id"), nullable=False)
    quantity = Column(Numeric(10, 2), nullable=False)
    unit_price = Column(Numeric(10, 2), nullable=False)
    seller_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    sale_date = Column(Date, nullable=False)
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    product = relationship("Product")
    seller = relationship("User")


class WasteRecord(Base):
    """Sotuvchi tomonidan buzilgan/chiqindi mahsulot kiritiladi"""
    __tablename__ = "waste_records"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id"), nullable=False)
    quantity = Column(Numeric(10, 2), nullable=False)
    reason = Column(Text)
    seller_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    waste_date = Column(Date, nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    product = relationship("Product")
    seller = relationship("User")


class ExtraOrder(Base):
    __tablename__ = "extra_orders"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_name = Column(String(200), nullable=False)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id"), nullable=False)
    quantity = Column(Numeric(10, 2), nullable=False)
    delivery_date = Column(Date)
    notes = Column(Text)
    is_fulfilled = Column(Boolean, default=False)
    seller_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    product = relationship("Product")
    seller = relationship("User")


class AIForecast(Base):
    __tablename__ = "ai_forecasts"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id"), nullable=False)
    forecast_date = Column(Date, nullable=False)
    current_stock = Column(Numeric(10, 2))
    forecast_demand = Column(Numeric(10, 2))
    safety_stock = Column(Numeric(10, 2))
    recommended_order = Column(Numeric(10, 2))
    confidence_score = Column(Numeric(4, 3))
    extra_orders_qty = Column(Numeric(10, 2), default=0)
    model_used = Column(String(50))
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    product = relationship("Product")


class ProcurementOrder(Base):
    __tablename__ = "procurement_orders"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_number = Column(String(50), unique=True, nullable=False)
    status = Column(SAEnum(ProcurementStatus), nullable=False, default=ProcurementStatus.draft)
    buyer_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    warehouse_manager_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    receiver_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    buyer_notes = Column(Text)
    warehouse_notes = Column(Text)
    total_estimated_cost = Column(Numeric(12, 2), default=0)
    total_actual_cost = Column(Numeric(12, 2), default=0)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    buyer_confirmed_at = Column(DateTime(timezone=True))
    warehouse_approved_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    items = relationship("ProcurementItem", back_populates="order", cascade="all, delete-orphan")
    buyer = relationship("User", foreign_keys=[buyer_id])
    warehouse_manager = relationship("User", foreign_keys=[warehouse_manager_id])


class ProcurementItem(Base):
    __tablename__ = "procurement_items"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(UUID(as_uuid=True), ForeignKey("procurement_orders.id", ondelete="CASCADE"), nullable=False)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id"), nullable=False)
    ai_recommended_qty = Column(Numeric(10, 2))
    buyer_ordered_qty = Column(Numeric(10, 2))
    received_qty = Column(Numeric(10, 2))
    damaged_qty = Column(Numeric(10, 2), default=0)
    estimated_price = Column(Numeric(10, 2))
    actual_price = Column(Numeric(10, 2))
    supplier_id = Column(UUID(as_uuid=True), ForeignKey("suppliers.id"))
    notes = Column(Text)
    order = relationship("ProcurementOrder", back_populates="items")
    product = relationship("Product")


class StockMovement(Base):
    __tablename__ = "stock_movements"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id"), nullable=False)
    movement_type = Column(SAEnum(MovementType), nullable=False)
    quantity = Column(Numeric(10, 2), nullable=False)
    stock_before = Column(Numeric(10, 2))
    stock_after = Column(Numeric(10, 2))
    reference_id = Column(UUID(as_uuid=True))
    reference_type = Column(String(50))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class Notification(Base):
    __tablename__ = "notifications"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    type = Column(String(50), nullable=False)
    title = Column(String(200), nullable=False)
    message = Column(Text, nullable=False)
    data = Column(JSON)
    is_read = Column(Boolean, default=False)
    sent_to_telegram = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
