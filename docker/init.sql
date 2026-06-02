CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TYPE user_role AS ENUM ('admin', 'seller', 'buyer', 'warehouse_manager', 'goods_receiver');
CREATE TYPE procurement_status AS ENUM (
    'draft','ai_generated','buyer_confirmed',
    'warehouse_approved','rejected','receiving','completed'
);
CREATE TYPE movement_type AS ENUM ('initial','in','out','waste','adjustment');

-- USERS
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    telegram_id BIGINT UNIQUE,
    username VARCHAR(100) UNIQUE NOT NULL,
    full_name VARCHAR(200) NOT NULL,
    phone VARCHAR(20),
    role user_role NOT NULL DEFAULT 'seller',
    hashed_password VARCHAR(255) NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- SUPPLIERS
CREATE TABLE suppliers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(200) NOT NULL,
    phone VARCHAR(20),
    address TEXT,
    rating DECIMAL(3,2) DEFAULT 5.0,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- CATEGORIES
CREATE TABLE categories (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(100) NOT NULL,
    description TEXT
);

-- PRODUCTS
CREATE TABLE products (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(200) NOT NULL,
    category_id UUID REFERENCES categories(id),
    barcode VARCHAR(100) UNIQUE,
    unit VARCHAR(20) NOT NULL DEFAULT 'kg',
    supplier_id UUID REFERENCES suppliers(id),
    minimum_stock DECIMAL(10,2) NOT NULL DEFAULT 10,
    current_stock DECIMAL(10,2) NOT NULL DEFAULT 0,
    purchase_price DECIMAL(10,2) NOT NULL DEFAULT 0,
    selling_price DECIMAL(10,2) NOT NULL DEFAULT 0,
    expiration_days INTEGER DEFAULT 7,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- INVENTORY SESSIONS (Admin tomonidan boshlangich ostatka)
CREATE TABLE inventory_sessions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_date DATE NOT NULL DEFAULT CURRENT_DATE,
    product_id UUID NOT NULL REFERENCES products(id),
    initial_stock DECIMAL(10,2) NOT NULL DEFAULT 0,  -- Admin kiritan boshlangich
    notes TEXT,
    admin_id UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_inv_date ON inventory_sessions(session_date, product_id);

-- SALES
CREATE TABLE sales (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    product_id UUID NOT NULL REFERENCES products(id),
    quantity DECIMAL(10,2) NOT NULL,
    unit_price DECIMAL(10,2) NOT NULL,
    seller_id UUID NOT NULL REFERENCES users(id),
    sale_date DATE NOT NULL DEFAULT CURRENT_DATE,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_sales_date ON sales(sale_date, product_id);

-- WASTE (Sotuvchi tomonidan buzilgan/chiqindi)
CREATE TABLE waste_records (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    product_id UUID NOT NULL REFERENCES products(id),
    quantity DECIMAL(10,2) NOT NULL,
    reason TEXT,
    seller_id UUID NOT NULL REFERENCES users(id),
    waste_date DATE NOT NULL DEFAULT CURRENT_DATE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_waste_date ON waste_records(waste_date, product_id);

-- EXTRA ORDERS
CREATE TABLE extra_orders (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    customer_name VARCHAR(200) NOT NULL,
    product_id UUID NOT NULL REFERENCES products(id),
    quantity DECIMAL(10,2) NOT NULL,
    delivery_date DATE,
    notes TEXT,
    is_fulfilled BOOLEAN DEFAULT FALSE,
    seller_id UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- AI FORECASTS
CREATE TABLE ai_forecasts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    product_id UUID NOT NULL REFERENCES products(id),
    forecast_date DATE NOT NULL DEFAULT CURRENT_DATE,
    current_stock DECIMAL(10,2),
    forecast_demand DECIMAL(10,2),
    safety_stock DECIMAL(10,2),
    recommended_order DECIMAL(10,2),
    confidence_score DECIMAL(4,3),
    extra_orders_qty DECIMAL(10,2) DEFAULT 0,
    model_used VARCHAR(50),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- PROCUREMENT ORDERS
CREATE TABLE procurement_orders (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    order_number VARCHAR(50) UNIQUE NOT NULL,
    status procurement_status NOT NULL DEFAULT 'draft',
    buyer_id UUID REFERENCES users(id),
    warehouse_manager_id UUID REFERENCES users(id),
    receiver_id UUID REFERENCES users(id),
    buyer_notes TEXT,
    warehouse_notes TEXT,
    total_estimated_cost DECIMAL(12,2) DEFAULT 0,
    total_actual_cost DECIMAL(12,2) DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    buyer_confirmed_at TIMESTAMPTZ,
    warehouse_approved_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);

-- PROCUREMENT ITEMS
CREATE TABLE procurement_items (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    order_id UUID NOT NULL REFERENCES procurement_orders(id) ON DELETE CASCADE,
    product_id UUID NOT NULL REFERENCES products(id),
    ai_recommended_qty DECIMAL(10,2),
    buyer_ordered_qty DECIMAL(10,2),
    received_qty DECIMAL(10,2),
    damaged_qty DECIMAL(10,2) DEFAULT 0,
    estimated_price DECIMAL(10,2),
    actual_price DECIMAL(10,2),
    supplier_id UUID REFERENCES suppliers(id),
    notes TEXT
);

-- STOCK MOVEMENTS (avtomatik log)
CREATE TABLE stock_movements (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    product_id UUID NOT NULL REFERENCES products(id),
    movement_type movement_type NOT NULL,
    quantity DECIMAL(10,2) NOT NULL,
    stock_before DECIMAL(10,2),
    stock_after DECIMAL(10,2),
    reference_id UUID,
    reference_type VARCHAR(50),
    user_id UUID REFERENCES users(id),
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_movements_product_date ON stock_movements(product_id, created_at);

-- RECEIVING LOGS
CREATE TABLE receiving_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    procurement_item_id UUID NOT NULL REFERENCES procurement_items(id),
    receiver_id UUID NOT NULL REFERENCES users(id),
    ordered_qty DECIMAL(10,2),
    received_qty DECIMAL(10,2),
    damaged_qty DECIMAL(10,2) DEFAULT 0,
    actual_price DECIMAL(10,2),
    invoice_number VARCHAR(100),
    notes TEXT,
    received_at TIMESTAMPTZ DEFAULT NOW()
);

-- NOTIFICATIONS
CREATE TABLE notifications (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id),
    type VARCHAR(50) NOT NULL,
    title VARCHAR(200) NOT NULL,
    message TEXT NOT NULL,
    data JSONB,
    is_read BOOLEAN DEFAULT FALSE,
    sent_to_telegram BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ==================== SEED DATA ====================

INSERT INTO categories (name) VALUES ('Sabzavotlar'),('Mevalar'),("Ko'katlar"),('Sitruslar');

-- Default password: Admin123!
INSERT INTO users (username, full_name, role, hashed_password) VALUES
    ('admin',      'System Admin',     'admin',             '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewdBPj/RK.s5uHAe'),
    ('seller1',    'Ali Valiyev',      'seller',            '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewdBPj/RK.s5uHAe'),
    ('buyer1',     'Bobur Karimov',    'buyer',             '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewdBPj/RK.s5uHAe'),
    ('warehouse1', 'Sardor Umarov',    'warehouse_manager', '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewdBPj/RK.s5uHAe'),
    ('receiver1',  'Jasur Toshmatov',  'goods_receiver',    '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewdBPj/RK.s5uHAe');

INSERT INTO suppliers (name, phone, rating) VALUES
    ('Yunusov Bozori','+998901234567',4.8),
    ('Chorsu Market', '+998901234568',4.5),
    ('Fergana Fermer', '+998901234569',4.9);

INSERT INTO products (name, category_id, unit, minimum_stock, current_stock, purchase_price, selling_price, expiration_days)
SELECT p.name, c.id, p.unit, p.min_s, p.cur_s, p.buy_p, p.sell_p, p.exp
FROM (VALUES
    ('Pomidor',   'Sabzavotlar', 'kg',    30, 0, 3500, 5000,  5),
    ('Bodring',   'Sabzavotlar', 'kg',    20, 0, 4000, 6000,  4),
    ('Karam',     'Sabzavotlar', 'kg',    25, 0, 2000, 3500, 10),
    ('Sabzi',     'Sabzavotlar', 'kg',    20, 0, 2500, 4000, 14),
    ('Banan',     'Mevalar',     'kg',    30, 0,12000,18000,  7),
    ('Olma',      'Mevalar',     'kg',    25, 0, 5000, 8000, 30),
    ('Limon',     'Sitruslar',   'kg',    15, 0, 8000,12000, 21),
    ('Apelsin',   'Sitruslar',   'kg',    20, 0, 7000,11000, 14),
    ('Ukrop',     'Ko''katlar',  'bunch', 20, 0, 1500, 3000,  3),
    ('Piyoz',     'Sabzavotlar', 'kg',    40, 0, 1500, 2500, 60)
) AS p(name,cat,unit,min_s,cur_s,buy_p,sell_p,exp)
JOIN categories c ON c.name = p.cat;
