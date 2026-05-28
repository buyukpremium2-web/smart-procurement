# 🥦 Smart AI Procurement System
> Meva-Sabzavot Do'konlari uchun Sun'iy Intellekt asosida Zakupka Boshqaruv Tizimi

---

## 🏗️ Tizim Arxitekturasi

```
┌─────────────────────────────────────────────────────────┐
│                    NGINX (Port 80)                       │
│              Load Balancer + Reverse Proxy               │
└────────────┬──────────────────────────┬─────────────────┘
             │                          │
    ┌────────▼────────┐      ┌──────────▼──────────┐
    │  React Frontend │      │   FastAPI Backend    │
    │   (Port 3000)   │      │    (Port 8000)       │
    └─────────────────┘      └──────────┬──────────┘
                                        │
                        ┌───────────────┼───────────────┐
                        │               │               │
               ┌────────▼───┐  ┌────────▼──┐  ┌────────▼───┐
               │ PostgreSQL │  │   Redis   │  │  AI Module │
               │ (Port 5432)│  │(Port 6379)│  │  Prophet   │
               └────────────┘  └───────────┘  └────────────┘
                                        │
                             ┌──────────▼──────────┐
                             │   Telegram Bot       │
                             │   (aiogram 3.x)      │
                             └─────────────────────┘
```

---

## 👥 Foydalanuvchi Rollari va Jarayonlar

```
[Sotuvchi] → Sotuv kiritadi, Qo'shimcha zakazlar qo'shadi
     ↓
[AI Modul] → Sotuvlarni tahlil qiladi, prognoz beradi
     ↓
[Bozorchi] → AI tavsiyalarini ko'radi, zakaz shakllantiradi
     ↓
[Omborchi] → Zakazni tasdiqlaydi / rad etadi
     ↓
[Tovaroved] → Kelgan tovarni qabul qiladi, ombor yangilanadi
     ↓
[Ombor] → Yangilangan holat bilan tsikl takrorlanadi
```

---

## 🚀 O'rnatish va Ishga Tushirish

### Talablar
- Docker & Docker Compose
- Telegram Bot Token (@BotFather dan)

### 1. Loyihani klonlash
```bash
git clone <repo-url>
cd smart-procurement
```

### 2. Environment o'zgaruvchilarini sozlash
```bash
cp .env.example .env
# .env faylini tahrirlang va quyidagilarni to'ldiring:
# - TELEGRAM_BOT_TOKEN
# - SECRET_KEY (kamida 32 belgi)
# - Kerak bo'lsa DB parollari
```

### 3. Tizimni ishga tushirish
```bash
docker-compose up -d
```

### 4. Ma'lumotlar bazasini tekshirish
```bash
docker-compose logs db
docker-compose exec db psql -U admin -d procurement_db -c "\dt"
```

### 5. Kirish
- **Web Panel**: http://localhost
- **API Docs**: http://localhost/api/docs
- **Telegram Bot**: @your_bot_username

**Demo akkauntlar** (parol: `Admin123!`):
| Login | Rol |
|-------|-----|
| admin | Administrator |
| seller1 | Sotuvchi |
| buyer1 | Bozorchi |
| warehouse1 | Omborchi |
| receiver1 | Tovaroved |

---

## 📁 Loyiha Strukturasi

```
smart-procurement/
├── backend/                    # FastAPI Backend
│   ├── app/
│   │   ├── api/v1/
│   │   │   └── endpoints/      # REST API endpointlar
│   │   │       ├── auth.py     # JWT autentifikatsiya
│   │   │       ├── sales.py    # Sotuvlar moduli
│   │   │       ├── procurement.py # Zakupka workflow
│   │   │       ├── ai.py       # AI forecast endpointlar
│   │   │       └── ...
│   │   ├── ai/
│   │   │   └── forecasting.py  # 🤖 AI prognoz moduli
│   │   ├── core/
│   │   │   ├── config.py       # Sozlamalar
│   │   │   ├── database.py     # PostgreSQL ulanish
│   │   │   └── security.py     # JWT + RBAC
│   │   ├── models/
│   │   │   └── models.py       # SQLAlchemy modellari
│   │   └── main.py             # FastAPI ilovasi
│   ├── requirements.txt
│   └── Dockerfile
│
├── frontend/                   # React.js Frontend
│   └── src/
│       └── App.js              # Asosiy ilova (routing + pages)
│
├── telegram_bot/               # Telegram Bot (aiogram 3.x)
│   └── bot.py                  # Bot handlerlari va FSM
│
├── docker/
│   ├── init.sql                # DB schema + seed data
│   └── nginx.conf              # Nginx konfiguratsiya
│
├── docker-compose.yml          # Barcha servislar
├── .env.example                # Environment template
└── README.md
```

---

## 🤖 AI Prognoz Moduli

### Algoritmlar (ma'lumot miqdoriga qarab)

| Ma'lumot | Model | Ishonch |
|----------|-------|---------|
| 30+ kun | **Prophet** (Meta) | 85-95% |
| 7-30 kun | **Weighted Moving Average** | 60-80% |
| < 7 kun | **Simple Average** | 30-50% |

### Formula
```
buyurtma_miqdori = prognoz_talab + xavfsizlik_zaxirasi + qo'shimcha_zakazlar - joriy_ombor
```

### Qo'shimcha xususiyatlar (kelajak)
- 🌦️ Ob-havo ta'siri
- 💰 Narx prognozi
- 🦠 Buzilish prognozi
- ⭐ Yetkazuvchi reytingi

---

## 📊 API Endpointlar

| Method | Endpoint | Tavsif |
|--------|----------|--------|
| POST | `/api/v1/auth/login` | Tizimga kirish |
| GET | `/api/v1/auth/me` | Joriy foydalanuvchi |
| POST | `/api/v1/sales/` | Sotuv kiritish |
| GET | `/api/v1/sales/today` | Bugungi sotuvlar |
| GET | `/api/v1/sales/analytics` | Sotuv tahlili |
| POST | `/api/v1/ai/run-forecast` | AI tahlilni boshlash |
| GET | `/api/v1/ai/latest` | Oxirgi AI tavsiyalar |
| POST | `/api/v1/procurement/` | Zakaz yaratish |
| PATCH | `/api/v1/procurement/{id}/approve` | Zakazni tasdiqlash |
| PATCH | `/api/v1/procurement/{id}/reject` | Zakazni rad etish |

**Swagger UI**: http://localhost/api/docs

---

## 🔔 Telegram Bot Komandalar

```
/start          - Tizimga kirish
📦 Sotuv kiritish      - Yangi sotuv
📋 Qo'shimcha zakaz    - Mijoz zakazi
🤖 AI tavsiyalar       - AI prognozlar
✅ Zakazlarni tasdiqlash - Omborchi uchun
📥 Tovar qabul qilish  - Tovaroved uchun
```

---

## 🛠️ Texnologiyalar

| Komponent | Texnologiya |
|-----------|-------------|
| Backend | FastAPI + Python 3.11 |
| ORM | SQLAlchemy 2.0 (async) |
| Database | PostgreSQL 15 |
| Cache | Redis 7 |
| Auth | JWT (python-jose) |
| AI | Prophet + scikit-learn + pandas |
| Frontend | React.js |
| Bot | aiogram 3.x |
| Proxy | Nginx |
| Container | Docker + Docker Compose |

---

## 📞 Yordam

Muammolar uchun GitHub Issues dan foydalaning yoki t.me/yourhandle ga murojaat qiling.
