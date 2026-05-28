import React, { createContext, useContext, useState, useEffect } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate, Link, useNavigate, useLocation } from 'react-router-dom';

// ==================== AUTH CONTEXT ====================
const AuthContext = createContext(null);

export const useAuth = () => useContext(AuthContext);

const API_BASE = process.env.REACT_APP_API_URL || 'http://localhost:8000/api/v1';

async function apiCall(endpoint, options = {}) {
  const token = localStorage.getItem('token');
  const res = await fetch(`${API_BASE}/${endpoint}`, {
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    ...options,
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem('token');
    const savedUser = localStorage.getItem('user');
    if (token && savedUser) {
      setUser(JSON.parse(savedUser));
    }
    setLoading(false);
  }, []);

  const login = async (username, password) => {
    const form = new URLSearchParams({ username, password });
    const res = await fetch(`${API_BASE}/auth/login`, { method: 'POST', body: form });
    if (!res.ok) throw new Error('Login yoki parol noto'g'ri');
    const data = await res.json();
    localStorage.setItem('token', data.access_token);
    localStorage.setItem('user', JSON.stringify(data.user));
    setUser(data.user);
    return data.user;
  };

  const logout = () => {
    localStorage.clear();
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, login, logout, loading, apiCall }}>
      {children}
    </AuthContext.Provider>
  );
}

// ==================== LOGIN PAGE ====================
function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState({ username: '', password: '' });
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError('');
    try {
      const user = await login(form.username, form.password);
      navigate(`/${user.role}`);
    } catch {
      setError("Login yoki parol noto'g'ri");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={styles.loginPage}>
      <div style={styles.loginCard}>
        <div style={styles.loginLogo}>
          <span style={{ fontSize: 48 }}>🥦</span>
          <h1 style={styles.loginTitle}>Smart Procurement</h1>
          <p style={styles.loginSubtitle}>Meva-Sabzavot Do'konlari uchun AI ERP</p>
        </div>
        <form onSubmit={handleSubmit} style={styles.form}>
          <input
            style={styles.input}
            placeholder="Login"
            value={form.username}
            onChange={e => setForm(p => ({ ...p, username: e.target.value }))}
          />
          <input
            style={styles.input}
            type="password"
            placeholder="Parol"
            value={form.password}
            onChange={e => setForm(p => ({ ...p, password: e.target.value }))}
          />
          {error && <p style={styles.error}>{error}</p>}
          <button style={styles.loginBtn} disabled={loading}>
            {loading ? 'Kirilmoqda...' : 'Kirish →'}
          </button>
        </form>
        <p style={styles.hint}>Demo: admin / Admin123!</p>
      </div>
    </div>
  );
}

// ==================== SIDEBAR ====================
const roleMenus = {
  admin: [
    { path: '/admin', icon: '📊', label: 'Dashboard' },
    { path: '/admin/products', icon: '🥦', label: 'Mahsulotlar' },
    { path: '/admin/ai', icon: '🤖', label: 'AI Tahlil' },
    { path: '/admin/procurement', icon: '📋', label: 'Zakazlar' },
    { path: '/admin/users', icon: '👥', label: 'Foydalanuvchilar' },
  ],
  seller: [
    { path: '/seller', icon: '📊', label: 'Bugungi holat' },
    { path: '/seller/sale', icon: '💰', label: 'Sotuv kiritish' },
    { path: '/seller/extra-orders', icon: '📋', label: "Qo'shimcha zakazlar" },
    { path: '/seller/stock', icon: '🏪', label: 'Ombor' },
  ],
  buyer: [
    { path: '/buyer', icon: '🤖', label: 'AI Tavsiyalar' },
    { path: '/buyer/create-order', icon: '📝', label: 'Zakaz yaratish' },
    { path: '/buyer/orders', icon: '📋', label: 'Zakazlarim' },
    { path: '/buyer/suppliers', icon: '🏭', label: 'Yetkazuvchilar' },
  ],
  warehouse_manager: [
    { path: '/warehouse', icon: '📊', label: 'Ombor holati' },
    { path: '/warehouse/pending', icon: '⏳', label: 'Tasdiqlash kutmoqda' },
    { path: '/warehouse/history', icon: '📋', label: 'Tarix' },
  ],
  goods_receiver: [
    { path: '/receiver', icon: '📥', label: 'Qabul qilish' },
    { path: '/receiver/history', icon: '📋', label: 'Qabul tarixi' },
  ],
};

function Sidebar() {
  const { user, logout } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const menu = roleMenus[user?.role] || [];

  const roleLabels = {
    admin: 'Admin',
    seller: 'Sotuvchi',
    buyer: 'Bozorchi',
    warehouse_manager: 'Omborchi',
    goods_receiver: 'Tovaroved',
  };

  return (
    <aside style={styles.sidebar}>
      <div style={styles.sidebarLogo}>
        <span style={{ fontSize: 28 }}>🥦</span>
        <span style={styles.sidebarTitle}>SmartPro</span>
      </div>
      <div style={styles.userBadge}>
        <div style={styles.avatar}>{user?.full_name?.[0]}</div>
        <div>
          <div style={styles.userName}>{user?.full_name}</div>
          <div style={styles.userRole}>{roleLabels[user?.role]}</div>
        </div>
      </div>
      <nav style={styles.nav}>
        {menu.map(item => (
          <Link
            key={item.path}
            to={item.path}
            style={{
              ...styles.navItem,
              ...(location.pathname === item.path ? styles.navItemActive : {}),
            }}
          >
            <span style={styles.navIcon}>{item.icon}</span>
            <span>{item.label}</span>
          </Link>
        ))}
      </nav>
      <button onClick={() => { logout(); navigate('/login'); }} style={styles.logoutBtn}>
        🚪 Chiqish
      </button>
    </aside>
  );
}

// ==================== LAYOUT ====================
function Layout({ children }) {
  return (
    <div style={styles.layout}>
      <Sidebar />
      <main style={styles.main}>{children}</main>
    </div>
  );
}

// ==================== DASHBOARD ====================
function StatCard({ icon, label, value, color }) {
  return (
    <div style={{ ...styles.statCard, borderTop: `3px solid ${color}` }}>
      <div style={{ fontSize: 32 }}>{icon}</div>
      <div>
        <div style={styles.statValue}>{value}</div>
        <div style={styles.statLabel}>{label}</div>
      </div>
    </div>
  );
}

function AdminDashboard() {
  const [stats, setStats] = useState({ sales: [], products: [], forecasts: [] });
  const { apiCall } = useAuth();

  useEffect(() => {
    Promise.all([
      apiCall('sales/today').catch(() => null),
      apiCall('ai/latest').catch(() => []),
    ]).then(([today, forecasts]) => {
      setStats({ today, forecasts: forecasts || [] });
    });
  }, []);

  const urgentItems = stats.forecasts.filter(f => f.recommended_order > 0);

  return (
    <div style={styles.page}>
      <h1 style={styles.pageTitle}>📊 Bosh Panel</h1>

      <div style={styles.statsGrid}>
        <StatCard icon="💰" label="Bugungi tushum" value={`${(stats.today?.total_revenue || 0).toLocaleString()} so'm`} color="#10b981" />
        <StatCard icon="📦" label="Tranzaksiyalar" value={stats.today?.count || 0} color="#3b82f6" />
        <StatCard icon="🔴" label="Kam tovar" value={urgentItems.length} color="#ef4444" />
        <StatCard icon="🤖" label="AI tahlil" value="Aktiv" color="#8b5cf6" />
      </div>

      {urgentItems.length > 0 && (
        <div style={styles.section}>
          <h2 style={styles.sectionTitle}>🔴 Urgently Needed - AI Tavsiyalari</h2>
          <div style={styles.table}>
            <div style={styles.tableHeader}>
              <span>Mahsulot</span>
              <span>Omborda</span>
              <span>Prognoz</span>
              <span>Buyurtma</span>
              <span>Ishonch</span>
            </div>
            {urgentItems.slice(0, 10).map((item, i) => (
              <div key={i} style={styles.tableRow}>
                <span><strong>{item.product_name}</strong></span>
                <span style={{ color: item.current_stock < 20 ? '#ef4444' : '#10b981' }}>
                  {item.current_stock} {item.unit}
                </span>
                <span>{item.forecast_demand?.toFixed(1)} {item.unit}</span>
                <span style={{ color: '#f59e0b', fontWeight: 600 }}>
                  {item.recommended_order?.toFixed(1)} {item.unit}
                </span>
                <span>{(item.confidence * 100).toFixed(0)}%</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ==================== SELLER: SALE ENTRY ====================
function SaleEntry() {
  const { apiCall } = useAuth();
  const [products, setProducts] = useState([]);
  const [form, setForm] = useState({ product_id: '', quantity: '', unit_price: '' });
  const [msg, setMsg] = useState('');

  useEffect(() => {
    apiCall('products/').then(setProducts).catch(console.error);
  }, []);

  const handleSubmit = async () => {
    if (!form.product_id || !form.quantity || !form.unit_price) {
      setMsg('Barcha maydonlarni to'ldiring');
      return;
    }
    try {
      const result = await apiCall('sales/', {
        method: 'POST',
        body: JSON.stringify({
          product_id: form.product_id,
          quantity: parseFloat(form.quantity),
          unit_price: parseFloat(form.unit_price),
        }),
      });
      setMsg(`✅ Sotuv kiritildi! Qoldi: ${result.remaining_stock}`);
      setForm({ product_id: '', quantity: '', unit_price: '' });
    } catch (e) {
      setMsg(`❌ Xatolik: ${e.message}`);
    }
  };

  return (
    <div style={styles.page}>
      <h1 style={styles.pageTitle}>💰 Sotuv Kiritish</h1>
      <div style={styles.card}>
        <select
          style={styles.input}
          value={form.product_id}
          onChange={e => setForm(p => ({ ...p, product_id: e.target.value }))}
        >
          <option value="">Mahsulot tanlang...</option>
          {products.map(p => (
            <option key={p.id} value={p.id}>
              {p.name} — Omborda: {p.current_stock} {p.unit}
            </option>
          ))}
        </select>
        <input
          style={styles.input}
          type="number"
          placeholder="Miqdor (kg/dona)"
          value={form.quantity}
          onChange={e => setForm(p => ({ ...p, quantity: e.target.value }))}
        />
        <input
          style={styles.input}
          type="number"
          placeholder="Narx (so'm)"
          value={form.unit_price}
          onChange={e => setForm(p => ({ ...p, unit_price: e.target.value }))}
        />
        <button style={styles.primaryBtn} onClick={handleSubmit}>
          ✅ Sotuv kiritish
        </button>
        {msg && <p style={{ marginTop: 12, color: msg.includes('✅') ? '#10b981' : '#ef4444' }}>{msg}</p>}
      </div>
    </div>
  );
}

// ==================== BUYER: AI RECOMMENDATIONS ====================
function AIRecommendations() {
  const { apiCall } = useAuth();
  const [forecasts, setForecasts] = useState([]);
  const [running, setRunning] = useState(false);
  const [selected, setSelected] = useState({});

  useEffect(() => {
    apiCall('ai/latest').then(setForecasts).catch(() => {});
  }, []);

  const runAI = async () => {
    setRunning(true);
    try {
      const result = await apiCall('ai/run-forecast', { method: 'POST' });
      setForecasts(result.forecasts || []);
    } catch (e) {
      alert('AI tahlil xatolik: ' + e.message);
    } finally {
      setRunning(false);
    }
  };

  const toggle = (id) => setSelected(p => ({ ...p, [id]: !p[id] }));

  return (
    <div style={styles.page}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <h1 style={styles.pageTitle}>🤖 AI Tavsiyalari</h1>
        <button style={styles.primaryBtn} onClick={runAI} disabled={running}>
          {running ? '🔄 Tahlil qilinmoqda...' : '🚀 AI Tahlilni boshlash'}
        </button>
      </div>

      {forecasts.length === 0 ? (
        <div style={styles.empty}>
          <p>Hali tavsiyalar yo'q. AI tahlilni boshlang.</p>
        </div>
      ) : (
        <>
          <div style={styles.table}>
            <div style={styles.tableHeader}>
              <span>✓</span>
              <span>Mahsulot</span>
              <span>Omborda</span>
              <span>Prognoz talabi</span>
              <span>Xavfsizlik zaxirasi</span>
              <span>Tavsiya zakaz</span>
              <span>Ishonch</span>
            </div>
            {forecasts.map((f, i) => (
              <div
                key={i}
                style={{
                  ...styles.tableRow,
                  background: selected[i] ? '#f0fdf4' : undefined,
                  cursor: 'pointer',
                }}
                onClick={() => toggle(i)}
              >
                <span>{selected[i] ? '☑️' : '⬜'}</span>
                <span><strong>{f.product_name}</strong></span>
                <span style={{ color: f.current_stock < 20 ? '#ef4444' : '#10b981' }}>
                  {f.current_stock} {f.unit}
                </span>
                <span>{f.forecast_demand?.toFixed(1)} {f.unit}</span>
                <span>{f.safety_stock?.toFixed(1)} {f.unit}</span>
                <span style={{ color: '#f59e0b', fontWeight: 700 }}>
                  {f.recommended_order > 0 ? `${f.recommended_order?.toFixed(1)} ${f.unit}` : '— Yetarli'}
                </span>
                <span>{((f.confidence || 0) * 100).toFixed(0)}%</span>
              </div>
            ))}
          </div>
          <button style={{ ...styles.primaryBtn, marginTop: 16 }}>
            📝 Tanlanganlarga zakaz yaratish
          </button>
        </>
      )}
    </div>
  );
}

// ==================== WAREHOUSE: PENDING ORDERS ====================
function PendingOrders() {
  const { apiCall } = useAuth();
  const [orders, setOrders] = useState([]);

  useEffect(() => {
    apiCall('procurement/?status=buyer_confirmed').then(setOrders).catch(() => {});
  }, []);

  const approve = async (id) => {
    try {
      await apiCall(`procurement/${id}/approve`, {
        method: 'PATCH',
        body: JSON.stringify({ notes: 'Web panel orqali tasdiqlandi' }),
      });
      setOrders(o => o.filter(x => x.id !== id));
    } catch (e) { alert('Xatolik: ' + e.message); }
  };

  const reject = async (id) => {
    const notes = prompt('Rad etish sababi:');
    if (!notes) return;
    try {
      await apiCall(`procurement/${id}/reject`, {
        method: 'PATCH',
        body: JSON.stringify({ notes }),
      });
      setOrders(o => o.filter(x => x.id !== id));
    } catch (e) { alert('Xatolik: ' + e.message); }
  };

  return (
    <div style={styles.page}>
      <h1 style={styles.pageTitle}>⏳ Tasdiqlash Kutayotgan Zakazlar</h1>
      {orders.length === 0 ? (
        <div style={styles.empty}><p>✅ Hamma zakazlar ko'rib chiqilgan!</p></div>
      ) : (
        orders.map(order => (
          <div key={order.id} style={styles.orderCard}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <div>
                <h3 style={{ margin: 0, color: '#1e293b' }}>{order.order_number}</h3>
                <p style={{ margin: '4px 0', color: '#64748b', fontSize: 14 }}>
                  Taxminiy narx: <strong>{order.total_estimated_cost?.toLocaleString()} so'm</strong>
                </p>
                <p style={{ margin: 0, color: '#94a3b8', fontSize: 12 }}>
                  {new Date(order.created_at).toLocaleString('uz-UZ')}
                </p>
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                <button style={styles.approveBtn} onClick={() => approve(order.id)}>✅ Tasdiqlash</button>
                <button style={styles.rejectBtn} onClick={() => reject(order.id)}>❌ Rad etish</button>
              </div>
            </div>
          </div>
        ))
      )}
    </div>
  );
}

// ==================== ROUTER ====================
function ProtectedRoute({ children, roles }) {
  const { user, loading } = useAuth();
  if (loading) return <div style={styles.loading}>Yuklanmoqda...</div>;
  if (!user) return <Navigate to="/login" />;
  if (roles && !roles.includes(user.role)) return <Navigate to={`/${user.role}`} />;
  return <Layout>{children}</Layout>;
}

export default function App() {
  return (
    <AuthProvider>
      <Router>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/admin" element={<ProtectedRoute roles={['admin']}><AdminDashboard /></ProtectedRoute>} />
          <Route path="/seller" element={<ProtectedRoute roles={['seller', 'admin']}><SaleEntry /></ProtectedRoute>} />
          <Route path="/seller/sale" element={<ProtectedRoute roles={['seller', 'admin']}><SaleEntry /></ProtectedRoute>} />
          <Route path="/buyer" element={<ProtectedRoute roles={['buyer', 'admin']}><AIRecommendations /></ProtectedRoute>} />
          <Route path="/warehouse/pending" element={<ProtectedRoute roles={['warehouse_manager', 'admin']}><PendingOrders /></ProtectedRoute>} />
          <Route path="/warehouse" element={<ProtectedRoute roles={['warehouse_manager', 'admin']}><PendingOrders /></ProtectedRoute>} />
          <Route path="/" element={<Navigate to="/login" />} />
        </Routes>
      </Router>
    </AuthProvider>
  );
}

// ==================== STYLES ====================
const styles = {
  loginPage: { minHeight: '100vh', background: 'linear-gradient(135deg, #0f172a 0%, #1e293b 50%, #0f4c3a 100%)', display: 'flex', alignItems: 'center', justifyContent: 'center' },
  loginCard: { background: 'white', borderRadius: 16, padding: 40, width: 380, boxShadow: '0 25px 50px rgba(0,0,0,0.4)' },
  loginLogo: { textAlign: 'center', marginBottom: 28 },
  loginTitle: { margin: '8px 0 4px', fontSize: 22, fontWeight: 700, color: '#1e293b' },
  loginSubtitle: { margin: 0, color: '#64748b', fontSize: 13 },
  form: { display: 'flex', flexDirection: 'column', gap: 12 },
  input: { border: '1.5px solid #e2e8f0', borderRadius: 8, padding: '10px 14px', fontSize: 15, outline: 'none', width: '100%', boxSizing: 'border-box' },
  error: { color: '#ef4444', fontSize: 13, margin: 0 },
  loginBtn: { background: '#10b981', color: 'white', border: 'none', borderRadius: 8, padding: '12px 0', fontSize: 15, fontWeight: 600, cursor: 'pointer' },
  hint: { textAlign: 'center', color: '#94a3b8', fontSize: 12, marginTop: 12 },
  layout: { display: 'flex', minHeight: '100vh', background: '#f8fafc' },
  sidebar: { width: 240, background: '#0f172a', display: 'flex', flexDirection: 'column', padding: '0 0 20px', flexShrink: 0 },
  sidebarLogo: { display: 'flex', alignItems: 'center', gap: 10, padding: '20px 20px 16px', borderBottom: '1px solid #1e293b' },
  sidebarTitle: { color: 'white', fontWeight: 700, fontSize: 18 },
  userBadge: { display: 'flex', alignItems: 'center', gap: 10, padding: '16px 20px', borderBottom: '1px solid #1e293b' },
  avatar: { width: 36, height: 36, borderRadius: '50%', background: '#10b981', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'white', fontWeight: 700, flexShrink: 0 },
  userName: { color: 'white', fontSize: 14, fontWeight: 600 },
  userRole: { color: '#64748b', fontSize: 12 },
  nav: { flex: 1, padding: '12px 12px' },
  navItem: { display: 'flex', alignItems: 'center', gap: 10, padding: '10px 12px', borderRadius: 8, color: '#94a3b8', textDecoration: 'none', marginBottom: 2, fontSize: 14 },
  navItemActive: { background: '#1e293b', color: '#10b981' },
  navIcon: { fontSize: 18 },
  logoutBtn: { background: 'none', border: '1px solid #334155', color: '#94a3b8', borderRadius: 8, padding: '10px 20px', margin: '0 12px', cursor: 'pointer', fontSize: 13 },
  main: { flex: 1, overflow: 'auto' },
  page: { padding: 28 },
  pageTitle: { fontSize: 22, fontWeight: 700, color: '#1e293b', marginBottom: 24, marginTop: 0 },
  statsGrid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 16, marginBottom: 28 },
  statCard: { background: 'white', borderRadius: 12, padding: '20px', display: 'flex', alignItems: 'center', gap: 16, boxShadow: '0 1px 3px rgba(0,0,0,0.1)' },
  statValue: { fontSize: 22, fontWeight: 700, color: '#1e293b' },
  statLabel: { fontSize: 13, color: '#64748b' },
  section: { background: 'white', borderRadius: 12, padding: 24, boxShadow: '0 1px 3px rgba(0,0,0,0.1)' },
  sectionTitle: { fontSize: 16, fontWeight: 600, color: '#1e293b', margin: '0 0 16px' },
  table: { borderRadius: 8, overflow: 'hidden', border: '1px solid #e2e8f0' },
  tableHeader: { display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', background: '#f8fafc', padding: '12px 16px', fontSize: 12, fontWeight: 600, color: '#64748b', textTransform: 'uppercase' },
  tableRow: { display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', padding: '12px 16px', borderTop: '1px solid #f1f5f9', fontSize: 14 },
  card: { background: 'white', borderRadius: 12, padding: 24, maxWidth: 480, boxShadow: '0 1px 3px rgba(0,0,0,0.1)', display: 'flex', flexDirection: 'column', gap: 12 },
  primaryBtn: { background: '#10b981', color: 'white', border: 'none', borderRadius: 8, padding: '12px 20px', fontSize: 14, fontWeight: 600, cursor: 'pointer' },
  empty: { background: 'white', borderRadius: 12, padding: 40, textAlign: 'center', color: '#94a3b8' },
  orderCard: { background: 'white', borderRadius: 12, padding: '20px 24px', marginBottom: 12, boxShadow: '0 1px 3px rgba(0,0,0,0.1)' },
  approveBtn: { background: '#10b981', color: 'white', border: 'none', borderRadius: 8, padding: '8px 16px', cursor: 'pointer', fontSize: 13, fontWeight: 600 },
  rejectBtn: { background: '#ef4444', color: 'white', border: 'none', borderRadius: 8, padding: '8px 16px', cursor: 'pointer', fontSize: 13, fontWeight: 600 },
  loading: { display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh', fontSize: 18, color: '#64748b' },
};
