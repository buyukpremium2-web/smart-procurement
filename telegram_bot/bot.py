"""
Smart AI Procurement - Telegram Bot
Railway.app uchun optimallashtirilgan versiya
Redis yo'q bo'lsa ham ishlaydi (MemoryStorage fallback)
"""
import asyncio
import logging
import os
import json
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    WebAppInfo
)
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")

if not BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN environment variable is not set!")

logger.info(f"Backend URL: {BACKEND_URL}")

# Redis optional - fallback to MemoryStorage
try:
    REDIS_URL = os.getenv("REDIS_URL", "")
    if REDIS_URL:
        from aiogram.fsm.storage.redis import RedisStorage
        storage = RedisStorage.from_url(REDIS_URL)
        logger.info("Redis storage connected")
    else:
        storage = MemoryStorage()
        logger.info("Using MemoryStorage (no Redis)")
except Exception as e:
    logger.warning(f"Redis failed, using MemoryStorage: {e}")
    storage = MemoryStorage()

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

# In-memory token store (FSM data ga ham saqlaymiz)
user_tokens: dict[int, str] = {}
user_info: dict[int, dict] = {}


# =====================
# FSM STATES
# =====================
class LoginStates(StatesGroup):
    waiting_username = State()
    waiting_password = State()


class SaleStates(StatesGroup):
    choosing_product = State()
    entering_quantity = State()
    entering_price = State()
    selected_product = State()


class ExtraOrderStates(StatesGroup):
    customer_name = State()
    choosing_product = State()
    entering_quantity = State()
    delivery_date = State()


# =====================
# API HELPERS
# =====================
async def api_get(endpoint: str, token: str, params: dict = None) -> tuple[dict | list | None, int]:
    url = f"{BACKEND_URL}/api/v1/{endpoint.lstrip('/')}"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
                params=params or {}
            )
            logger.info(f"GET {url} -> {resp.status_code}")
            if resp.status_code == 200:
                return resp.json(), 200
            else:
                logger.error(f"API Error {resp.status_code}: {resp.text[:200]}")
                return None, resp.status_code
    except httpx.ConnectError as e:
        logger.error(f"Connection error to {url}: {e}")
        return None, 503
    except Exception as e:
        logger.error(f"API GET error: {e}")
        return None, 500


async def api_post(endpoint: str, data: dict, token: str = None, form: bool = False) -> tuple[dict | None, int]:
    url = f"{BACKEND_URL}/api/v1/{endpoint.lstrip('/')}"
    try:
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        async with httpx.AsyncClient(timeout=15.0) as client:
            if form:
                resp = await client.post(url, data=data, headers=headers)
            else:
                headers["Content-Type"] = "application/json"
                resp = await client.post(url, json=data, headers=headers)

            logger.info(f"POST {url} -> {resp.status_code}")
            if resp.status_code in (200, 201):
                return resp.json(), resp.status_code
            else:
                logger.error(f"API Error {resp.status_code}: {resp.text[:200]}")
                return None, resp.status_code
    except httpx.ConnectError as e:
        logger.error(f"Connection error to {url}: {e}")
        return None, 503
    except Exception as e:
        logger.error(f"API POST error: {e}")
        return None, 500


async def api_patch(endpoint: str, data: dict, token: str) -> tuple[dict | None, int]:
    url = f"{BACKEND_URL}/api/v1/{endpoint.lstrip('/')}"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.patch(
                url,
                json=data,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                }
            )
            logger.info(f"PATCH {url} -> {resp.status_code}")
            return resp.json() if resp.status_code == 200 else None, resp.status_code
    except Exception as e:
        logger.error(f"API PATCH error: {e}")
        return None, 500


def get_token(tg_id: int) -> str | None:
    return user_tokens.get(tg_id)


async def api_request(method: str, endpoint: str, json_data: dict = None, token: str = None) -> tuple[int, dict | None]:
    """Universal API so'rov - (status_code, result) qaytaradi"""
    url = f"{BACKEND_URL}/api/v1/{endpoint.lstrip('/')}"
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            if method == "GET":
                resp = await client.get(url, headers=headers)
            elif method == "POST":
                resp = await client.post(url, json=json_data or {}, headers=headers)
            elif method == "PATCH":
                resp = await client.patch(url, json=json_data or {}, headers=headers)
            else:
                return 400, None
            logger.info(f"{method} {url} -> {resp.status_code}")
            if resp.status_code in (200, 201):
                try:
                    return resp.status_code, resp.json()
                except Exception:
                    return resp.status_code, None
            return resp.status_code, None
    except httpx.ConnectError as e:
        logger.error(f"Connection error: {e}")
        return 503, None
    except Exception as e:
        logger.error(f"API request error: {e}")
        return 500, None


def get_user(tg_id: int) -> dict | None:
    return user_info.get(tg_id)


# =====================
# KEYBOARDS
# =====================
ROLE_LABELS = {
    "admin": "👑 Admin",
    "seller": "🧑‍💼 Sotuvchi",
    "buyer": "🛒 Bozorchi",
    "warehouse_manager": "🏭 Omborchi",
    "goods_receiver": "📥 Tovaroved",
}


def main_menu(role: str) -> ReplyKeyboardMarkup:
    """Faqat Web Panel tugmasi - asosiy ish web saytda"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🌐 Web Panel", web_app=WebAppInfo(url=BACKEND_URL))],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


# =====================
# /start & LOGIN
# =====================
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    tg_id = message.from_user.id

    web_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌐 Web Panelni ochish", web_app=WebAppInfo(url=BACKEND_URL))]
    ])

    # Allaqachon login qilganmi?
    token = get_token(tg_id)
    if token:
        user = get_user(tg_id)
        if user:
            role_label = ROLE_LABELS.get(user.get("role", ""), user.get("role", ""))
            await message.answer(
                f"👋 Xush kelibsiz, *{user['full_name']}*!\n"
                f"Rol: {role_label}\n\n"
                f"🔔 Bildirishnomalar yoqilgan.\n"
                f"👇 Pastdagi tugma orqali tizimga kiring:",
                parse_mode="Markdown",
                reply_markup=main_menu(user.get("role", ""))
            )
            return

    # Login so'raymiz
    await state.clear()
    await state.set_state(LoginStates.waiting_username)
    await message.answer(
        "🌿 *Buyuk Premium*\n\n"
        "Meva-Sabzavot Do'koni · ERP Tizimi\n\n"
        "🔐 Tizimga kirish uchun loginingizni yuboring:",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )


@router.message(Command("havola"))
async def cmd_havola(message: Message, state: FSMContext):
    """Admin: /havola @username — havola yaratadi"""
    tg_id = message.from_user.id

    # Admin ekanligini tekshiramiz
    status, result = await api_request("GET", f"users/check-telegram/{tg_id}")
    if not (status == 200 and result and result.get("allowed")):
        await message.answer("⛔️ Siz tizimda yo'qsiz.")
        return
    if result.get("role") != "admin":
        await message.answer("⛔️ Faqat admin havola yarata oladi.")
        return

    # /havola @username
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        # Username berilmagan - ro'yxat ko'rsatamiz
        st, users = await api_request("GET", f"users/list-for-bot/{tg_id}")
        if st == 200 and users:
            lines = ["👥 *Foydalanuvchilar:*\n"]
            for u in users:
                conn = "🟢 ulangan" if u["connected"] else "⚪️ ulanmagan"
                lines.append(f"`@{u['username']}` — {u['full_name']} {conn}")
            lines.append("\n📝 Havola yaratish:\n`/havola @username`")
            await message.answer("\n".join(lines), parse_mode="Markdown")
        else:
            await message.answer("Foydalanuvchilar topilmadi.")
        return

    target = parts[1].strip().lstrip("@")
    st, res = await api_request(
        "POST", "users/invite-by-username",
        json_data={"admin_telegram_id": tg_id, "target_username": target}
    )
    if st == 200 and res:
        await message.answer(
            f"✅ *Havola tayyor!*\n\n"
            f"👤 {res['target']} (@{res['username']})\n"
            f"🔑 Rol: {ROLE_LABELS.get(res['role'], res['role'])}\n\n"
            f"🔗 Havola (bir martalik):\n`{res['invite_link']}`\n\n"
            f"⚠️ Bu havolani faqat o'sha odamga yuboring.",
            parse_mode="Markdown"
        )
    elif st == 404:
        await message.answer(f"❌ `@{target}` topilmadi.", parse_mode="Markdown")
    else:
        await message.answer("❌ Havola yaratishda xato.")


@router.message(LoginStates.waiting_username)
async def process_username(message: Message, state: FSMContext):
    await state.update_data(username=message.text.strip())
    await state.set_state(LoginStates.waiting_password)
    await message.answer("🔑 Parolingizni yuboring:")


@router.message(LoginStates.waiting_password)
async def process_password(message: Message, state: FSMContext):
    data = await state.get_data()
    username = data.get("username", "")
    password = message.text.strip()

    # Parolni o'chir
    try:
        await message.delete()
    except Exception:
        pass

    await message.answer("⏳ Tekshirilmoqda...")

    result, status = await api_post(
        "auth/login",
        {"username": username, "password": password},
        form=True
    )

    await state.clear()

    if status == 200 and result:
        token = result["access_token"]
        user = result["user"]
        user_tokens[message.from_user.id] = token
        user_info[message.from_user.id] = user
        role_label = ROLE_LABELS.get(user["role"], user["role"])

        # Telegram ID ni avtomatik saqlash (bildirishnoma uchun)
        try:
            await api_patch(
                f"users/{user['id']}/telegram",
                {"telegram_id": message.from_user.id},
                token
            )
        except Exception as e:
            logger.error(f"Telegram ID saqlashda xato: {e}")

        await message.answer(
            f"✅ *Muvaffaqiyatli kirildi!*\n\n"
            f"Salom, *{user['full_name']}* 👋\n"
            f"Sizning rolingiz: {role_label}\n\n"
            f"🔔 Bildirishnomalar yoqildi",
            parse_mode="Markdown",
            reply_markup=main_menu(user["role"])
        )
    elif status == 503:
        await message.answer(
            "❌ *Backend serverga ulanib bo'lmadi!*\n\n"
            f"URL: `{BACKEND_URL}`\n"
            "Server ishlayotganini tekshiring.",
            parse_mode="Markdown"
        )
    else:
        await message.answer(
            "❌ Login yoki parol noto'g'ri.\n"
            "Qayta urinish uchun /start yuboring."
        )


# =====================
# SELLER HANDLERS
# =====================
@router.message(F.text == "📊 Bugungi sotuvlar")
async def today_sales(message: Message):
    tg_id = message.from_user.id
    token = get_token(tg_id)
    if not token:
        await message.answer("❌ Avval kiring: /start")
        return

    data, status = await api_get("sales/today", token)
    if status != 200 or not data:
        await message.answer(f"❌ Xatolik ({status}). Backend ishlayotganini tekshiring.")
        return

    text = f"📊 *Bugungi Sotuvlar*\n\n"
    text += f"📦 Tranzaksiyalar: *{data.get('count', 0)}*\n"
    text += f"💰 Jami tushum: *{data.get('total_revenue', 0):,.0f} so'm*\n\n"

    sales = data.get("sales", [])
    if not sales:
        text += "Bugun hali sotuv kiritilmagan."
    else:
        for sale in sales[:10]:
            text += f"• {sale['product_name']}: {sale['quantity']} — {sale['total_amount']:,.0f} so'm\n"

    await message.answer(text, parse_mode="Markdown")


@router.message(F.text == "📦 Sotuv kiritish")
async def start_sale(message: Message, state: FSMContext):
    tg_id = message.from_user.id
    token = get_token(tg_id)
    if not token:
        await message.answer("❌ Avval kiring: /start")
        return

    data, status = await api_get("products/", token)
    if status != 200 or not data:
        await message.answer(f"❌ Mahsulotlar ro'yxatini olishda xatolik ({status})")
        return

    products = [p for p in data if p.get("is_active", True) and float(p.get("current_stock", 0)) > 0]
    if not products:
        await message.answer("❌ Omborda mahsulot yo'q")
        return

    await state.update_data(products=products)
    await state.set_state(SaleStates.choosing_product)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"🥦 {p['name']} ({p['current_stock']} {p.get('unit','kg')})",
            callback_data=f"sale_prod_{i}"
        )]
        for i, p in enumerate(products[:20])
    ])
    await message.answer("📦 Mahsulot tanlang:", reply_markup=keyboard)


@router.callback_query(F.data.startswith("sale_prod_"), SaleStates.choosing_product)
async def sale_product_chosen(callback: CallbackQuery, state: FSMContext):
    idx = int(callback.data.split("_")[-1])
    data = await state.get_data()
    products = data.get("products", [])
    if idx >= len(products):
        await callback.answer("Xatolik!")
        return

    product = products[idx]
    await state.update_data(chosen_product=product)
    await state.set_state(SaleStates.entering_quantity)
    await callback.message.edit_text(
        f"✅ *{product['name']}* tanlandi\n"
        f"📦 Omborda: {product['current_stock']} {product.get('unit','kg')}\n\n"
        f"Miqdorni kiriting ({product.get('unit','kg')}):",
        parse_mode="Markdown"
    )
    await callback.answer()


@router.message(SaleStates.entering_quantity)
async def sale_quantity_entered(message: Message, state: FSMContext):
    try:
        qty = float(message.text.replace(",", "."))
        if qty <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ To'g'ri miqdor kiriting (masalan: 5.5)")
        return

    data = await state.get_data()
    product = data["chosen_product"]
    if qty > float(product["current_stock"]):
        await message.answer(
            f"❌ Omborda faqat {product['current_stock']} {product.get('unit','kg')} bor!"
        )
        return

    await state.update_data(quantity=qty)
    await state.set_state(SaleStates.entering_price)
    suggested = product.get("selling_price", 0)
    await message.answer(
        f"💰 Narxni kiriting (so'm):\n"
        f"_(Tavsiya etilgan: {suggested:,.0f} so'm)_",
        parse_mode="Markdown"
    )


@router.message(SaleStates.entering_price)
async def sale_price_entered(message: Message, state: FSMContext):
    try:
        price = float(message.text.replace(",", ".").replace(" ", ""))
        if price <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ To'g'ri narx kiriting (masalan: 5000)")
        return

    data = await state.get_data()
    product = data["chosen_product"]
    qty = data["quantity"]
    tg_id = message.from_user.id
    token = get_token(tg_id)

    result, status = await api_post(
        "sales/",
        {
            "product_id": product["id"],
            "quantity": qty,
            "unit_price": price,
        },
        token=token
    )

    await state.clear()

    if status == 200 and result:
        total = qty * price
        await message.answer(
            f"✅ *Sotuv kiritildi!*\n\n"
            f"📦 Mahsulot: {product['name']}\n"
            f"🔢 Miqdor: {qty} {product.get('unit','kg')}\n"
            f"💰 Narx: {price:,.0f} so'm\n"
            f"💵 Jami: *{total:,.0f} so'm*\n\n"
            f"🏪 Qoldi: {result.get('remaining_stock', '?')} {product.get('unit','kg')}",
            parse_mode="Markdown",
            reply_markup=main_menu(get_user(tg_id)["role"])
        )
    else:
        err = result.get("detail", "Noma'lum xatolik") if result else f"Status: {status}"
        await message.answer(
            f"❌ Xatolik: {err}",
            reply_markup=main_menu(get_user(tg_id)["role"])
        )


# =====================
# BUYER: AI RECOMMENDATIONS
# =====================
@router.message(F.text == "🤖 AI tavsiyalar")
async def ai_recommendations(message: Message):
    tg_id = message.from_user.id
    token = get_token(tg_id)
    if not token:
        await message.answer("❌ Avval kiring: /start")
        return

    await message.answer("🔄 AI tavsiyalar yuklanmoqda...")
    data, status = await api_get("ai/latest", token)

    if status != 200 or not data:
        await message.answer(
            f"❌ AI tavsiyalar topilmadi (status: {status})\n\n"
            "Avval AI tahlilni boshlash kerak.\n"
            "Admin paneldan yoki /run_ai buyrug'i bilan."
        )
        return

    if not data:
        await message.answer("📭 Bugun uchun AI tavsiyalar yo'q. /run_ai bilan yangilang.")
        return

    text = "🤖 *AI Tavsiyalari*\n\n"
    urgent = [f for f in data if f.get("recommended_order", 0) > 0]
    ok = [f for f in data if f.get("recommended_order", 0) <= 0]

    if urgent:
        text += f"🔴 *Buyurtma kerak ({len(urgent)} ta):*\n"
        for item in urgent[:8]:
            text += (
                f"\n▸ *{item['product_name']}*\n"
                f"  Ombor: {item.get('current_stock', 0)} {item.get('unit','kg')}\n"
                f"  Kerak: `{item.get('recommended_order', 0):.1f} {item.get('unit','kg')}`\n"
                f"  Ishonch: {item.get('confidence', 0)*100:.0f}%\n"
            )

    if ok:
        text += f"\n🟢 *Yetarli ({len(ok)} ta):* "
        text += ", ".join([f['product_name'] for f in ok[:5]])

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Zakaz yaratish", callback_data="create_order_from_ai")],
        [InlineKeyboardButton(text="🔄 Yangilash", callback_data="refresh_ai")]
    ])
    await message.answer(text, parse_mode="Markdown", reply_markup=kb)


@router.callback_query(F.data == "refresh_ai")
async def refresh_ai(callback: CallbackQuery):
    tg_id = callback.from_user.id
    token = get_token(tg_id)
    if not token:
        await callback.answer("❌ Avval kiring")
        return
    await callback.answer("🔄 AI qayta ishga tushirilmoqda...")
    result, status = await api_post("ai/run-forecast", {}, token=token)
    if status == 200:
        await callback.message.answer(
            f"✅ AI tahlil tugadi! {len(result.get('forecasts', []))} ta mahsulot tahlil qilindi.\n"
            "🤖 AI tavsiyalar tugmasini bosing."
        )
    else:
        await callback.message.answer(f"❌ AI tahlil xatolik: {status}")


@router.message(Command("run_ai"))
async def run_ai_command(message: Message):
    tg_id = message.from_user.id
    token = get_token(tg_id)
    if not token:
        await message.answer("❌ Avval kiring: /start")
        return

    user = get_user(tg_id)
    if user and user.get("role") not in ("admin", "buyer"):
        await message.answer("❌ Bu amal faqat admin va bozorchi uchun")
        return

    await message.answer("🤖 AI tahlil boshlanmoqda...")
    result, status = await api_post("ai/run-forecast", {}, token=token)
    if status == 200:
        count = len(result.get("forecasts", []))
        await message.answer(f"✅ AI tahlil tugadi!\n{count} ta mahsulot tahlil qilindi.\n\n🤖 AI tavsiyalar tugmasini bosing.")
    else:
        await message.answer(f"❌ Xatolik ({status}). Backend loglarini tekshiring.")


# =====================
# WAREHOUSE: APPROVE ORDERS
# =====================
@router.message(F.text == "✅ Tasdiqlash kutmoqda")
async def pending_orders(message: Message):
    tg_id = message.from_user.id
    token = get_token(tg_id)
    if not token:
        await message.answer("❌ Avval kiring: /start")
        return

    data, status = await api_get("procurement/", token, params={"status": "buyer_confirmed"})
    if status != 200:
        await message.answer(f"❌ Zakazlarni olishda xatolik ({status})")
        return

    if not data:
        await message.answer("✅ Hamma zakazlar ko'rib chiqilgan! Kutayotgan zakaz yo'q.")
        return

    for order in data[:5]:
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"wh_approve_{order['id']}"),
            InlineKeyboardButton(text="❌ Rad etish", callback_data=f"wh_reject_{order['id']}"),
        ]])
        await message.answer(
            f"📋 *{order['order_number']}*\n"
            f"💰 Taxminiy narx: {order.get('total_estimated_cost', 0):,.0f} so'm\n"
            f"📅 {order.get('created_at', '')[:10]}",
            parse_mode="Markdown",
            reply_markup=kb
        )


@router.callback_query(F.data.startswith("wh_approve_"))
async def warehouse_approve(callback: CallbackQuery):
    order_id = callback.data.replace("wh_approve_", "")
    tg_id = callback.from_user.id
    token = get_token(tg_id)
    if not token:
        await callback.answer("❌ Avval kiring")
        return

    result, status = await api_patch(
        f"procurement/{order_id}/approve",
        {"notes": "Telegram orqali tasdiqlandi"},
        token
    )
    if status == 200:
        await callback.message.edit_text(
            callback.message.text + "\n\n✅ *TASDIQLANDI*",
            parse_mode="Markdown"
        )
        await callback.answer("✅ Zakaz tasdiqlandi!")
    else:
        await callback.answer(f"❌ Xatolik: {status}")


@router.callback_query(F.data.startswith("wh_reject_"))
async def warehouse_reject(callback: CallbackQuery):
    order_id = callback.data.replace("wh_reject_", "")
    tg_id = callback.from_user.id
    token = get_token(tg_id)
    if not token:
        await callback.answer("❌ Avval kiring")
        return

    result, status = await api_patch(
        f"procurement/{order_id}/reject",
        {"notes": "Telegram orqali rad etildi"},
        token
    )
    if status == 200:
        await callback.message.edit_text(
            callback.message.text + "\n\n❌ *RAD ETILDI*",
            parse_mode="Markdown"
        )
        await callback.answer("✅ Zakaz rad etildi")
    else:
        await callback.answer(f"❌ Xatolik: {status}")


# =====================
# OMBOR HOLATI
# =====================
@router.message(F.text == "🏪 Ombor holati")
@router.message(F.text == "📊 Ombor holati")
async def stock_status(message: Message):
    tg_id = message.from_user.id
    token = get_token(tg_id)
    if not token:
        await message.answer("❌ Avval kiring: /start")
        return

    data, status = await api_get("products/", token)
    if status != 200 or not data:
        await message.answer(f"❌ Mahsulotlarni olishda xatolik ({status})")
        return

    text = "🏪 *Ombor Holati*\n\n"
    low = [p for p in data if float(p.get("current_stock", 0)) < float(p.get("minimum_stock", 10))]
    normal = [p for p in data if float(p.get("current_stock", 0)) >= float(p.get("minimum_stock", 10))]

    if low:
        text += f"🔴 *Kam qolgan ({len(low)} ta):*\n"
        for p in low:
            text += f"  ▸ {p['name']}: {p['current_stock']} {p.get('unit','kg')} (min: {p['minimum_stock']})\n"

    if normal:
        text += f"\n🟢 *Yetarli ({len(normal)} ta):*\n"
        for p in normal[:8]:
            text += f"  ▸ {p['name']}: {p['current_stock']} {p.get('unit','kg')}\n"

    await message.answer(text, parse_mode="Markdown")


# =====================
# ADMIN HANDLERS
# =====================
@router.message(F.text == "👥 Foydalanuvchilar")
async def list_users(message: Message):
    tg_id = message.from_user.id
    token = get_token(tg_id)
    if not token:
        await message.answer("❌ Avval kiring: /start")
        return

    user = get_user(tg_id)
    if not user or user.get("role") != "admin":
        await message.answer("❌ Bu sahifa faqat admin uchun")
        return

    # users/ endpoint mavjud bo'lsa ishlatamiz, bo'lmasa auth/me bilan tekshiramiz
    data, status = await api_get("users/", token)

    if status == 200 and data:
        text = "👥 *Foydalanuvchilar*\n\n"
        for u in data:
            role_label = ROLE_LABELS.get(u.get("role", ""), u.get("role", ""))
            status_icon = "🟢" if u.get("is_active") else "🔴"
            text += f"{status_icon} *{u['full_name']}* — {role_label}\n   @{u.get('username','')}\n\n"
        await message.answer(text, parse_mode="Markdown")
    else:
        # Fallback: faqat o'zi haqida ma'lumot
        me, me_status = await api_get("auth/me", token)
        if me_status == 200 and me:
            text = (
                "👥 *Foydalanuvchilar*\n\n"
                "_(To'liq ro'yxat uchun backend yangilanishi kerak)_\n\n"
                f"🟢 *{me.get('full_name','?')}* — {ROLE_LABELS.get(me.get('role',''), me.get('role',''))}\n"
                f"   @{me.get('username','')}\n\n"
                f"ℹ️ Boshqa foydalanuvchilarni ko'rish uchun:\n"
                f"`backend/app/api/v1/endpoints/users.py`\n"
                f"faylini GitHub ga qo'shing va Railway ga deploy qiling."
            )
            await message.answer(text, parse_mode="Markdown")
        else:
            await message.answer(
                "❌ Backend bilan ulanishda xatolik.\n\n"
                f"Backend URL: `{BACKEND_URL}`\n"
                "Railway dashboard dan loglarni tekshiring.",
                parse_mode="Markdown"
            )


@router.message(F.text == "🤖 AI tahlil")
async def admin_ai_menu(message: Message):
    tg_id = message.from_user.id
    token = get_token(tg_id)
    if not token:
        await message.answer("❌ Avval kiring: /start")
        return

    await message.answer("🔄 AI tahlil boshlanmoqda, biroz kuting...")
    result, status = await api_post("ai/run-forecast", {}, token=token)

    if status == 200 and result:
        count = len(result.get("forecasts", []))
        forecasts = result.get("forecasts", [])
        urgent = [f for f in forecasts if f.get("recommended_order", 0) > 0]

        text = f"✅ *AI Tahlil Tugadi!*\n\n"
        text += f"📊 Tahlil qilindi: *{count} ta mahsulot*\n"
        text += f"🔴 Buyurtma kerak: *{len(urgent)} ta*\n\n"

        if urgent:
            text += "🛒 *Eng muhim:*\n"
            for item in urgent[:5]:
                text += (
                    f"▸ {item.get('product_id','')[:8]}... → "
                    f"`{item.get('recommended_order',0):.1f}` {item.get('unit','kg')}\n"
                )
        text += "\n🤖 AI tavsiyalar tugmasini bosing."
        await message.answer(text, parse_mode="Markdown")
    elif status == 403:
        await message.answer("❌ Bu amal uchun ruxsat yo'q (faqat admin/buyer)")
    else:
        await message.answer(
            f"❌ AI tahlil xatolik (status: {status})\n\n"
            "Railway loglarini tekshiring:\n`railway logs`",
            parse_mode="Markdown"
        )



    tg_id = message.from_user.id
    token = get_token(tg_id)
    if not token:
        await message.answer("❌ Avval kiring: /start")
        return

    # Parallel requests
    today_data, t_status = await api_get("sales/today", token)
    ai_data, ai_status = await api_get("ai/latest", token)
    prods_data, p_status = await api_get("products/", token)

    text = "📊 *Admin Dashboard*\n\n"

    if t_status == 200 and today_data:
        text += f"💰 Bugungi tushum: *{today_data.get('total_revenue', 0):,.0f} so'm*\n"
        text += f"📦 Sotuvlar: *{today_data.get('count', 0)} ta*\n\n"

    if p_status == 200 and prods_data:
        low_stock = [p for p in prods_data if float(p.get("current_stock", 0)) < float(p.get("minimum_stock", 10))]
        text += f"🏪 Mahsulotlar: *{len(prods_data)} ta*\n"
        text += f"🔴 Kam qolgan: *{len(low_stock)} ta*\n\n"

    if ai_status == 200 and ai_data:
        urgent = [f for f in ai_data if f.get("recommended_order", 0) > 0]
        text += f"🤖 AI tavsiyalar: *{len(urgent)} ta mahsulot kerak*\n"
    else:
        text += "🤖 AI tavsiyalar: _Hali o'tkazilmagan_\n"

    await message.answer(text, parse_mode="Markdown")


@router.message(F.text == "⚙️ Sozlamalar")
async def settings_menu(message: Message):
    tg_id = message.from_user.id
    user = get_user(tg_id)
    await message.answer(
        f"⚙️ *Sozlamalar*\n\n"
        f"🖥️ Tizim versiyasi: 1.0.0\n"
        f"✅ Status: Faol\n\n"
        f"👤 Foydalanuvchi: {user.get('full_name', 'N/A') if user else 'N/A'}\n"
        f"🔑 Rol: {ROLE_LABELS.get(user.get('role',''), '') if user else 'N/A'}\n"
        f"🌐 Backend: `{BACKEND_URL}`",
        parse_mode="Markdown"
    )


# =====================
# ZAKAZLAR RO'YXATI
# =====================
@router.message(F.text == "📋 Zakazlar")
@router.message(F.text == "📊 Zakazlar ro'yxati")
async def list_orders(message: Message):
    tg_id = message.from_user.id
    token = get_token(tg_id)
    if not token:
        await message.answer("❌ Avval kiring: /start")
        return

    data, status = await api_get("procurement/", token)
    if status != 200 or not data:
        await message.answer(f"❌ Zakazlarni olishda xatolik ({status})")
        return

    if not data:
        await message.answer("📭 Hozircha zakazlar yo'q")
        return

    status_icons = {
        "draft": "📝",
        "ai_generated": "🤖",
        "buyer_confirmed": "🛒",
        "warehouse_approved": "✅",
        "rejected": "❌",
        "receiving": "📥",
        "completed": "🎉",
    }

    text = "📋 *So'nggi Zakazlar*\n\n"
    for order in data[:8]:
        icon = status_icons.get(order.get("status", ""), "📋")
        text += (
            f"{icon} *{order['order_number']}*\n"
            f"   Narx: {order.get('total_estimated_cost', 0):,.0f} so'm\n"
            f"   Status: `{order.get('status', '')}`\n\n"
        )

    await message.answer(text, parse_mode="Markdown")


# =====================
# CHIQISH
# =====================
@router.message(F.text == "🚪 Chiqish")
async def logout(message: Message, state: FSMContext):
    tg_id = message.from_user.id
    user_tokens.pop(tg_id, None)
    user_info.pop(tg_id, None)
    await state.clear()
    await message.answer(
        "👋 Tizimdan muvaffaqiyatli chiqdingiz.\n"
        "Qayta kirish uchun /start yuboring.",
        reply_markup=ReplyKeyboardRemove()
    )


# =====================
# UNKNOWN MESSAGES
# =====================
@router.message()
async def unknown_message(message: Message):
    tg_id = message.from_user.id
    user = get_user(tg_id)
    if user:
        await message.answer(
            "❓ Tushunmadim. Iltimos, tugmalardan foydalaning.",
            reply_markup=main_menu(user["role"])
        )
    else:
        await message.answer("👋 Tizimga kirish uchun /start yuboring.")


# =====================
# NOTIFICATION POLLER (background)
# =====================
async def notification_poller():
    """Har 10 soniyada backend dan yangi bildirishnomalarni oladi va botga yuboradi"""
    await asyncio.sleep(5)
    while True:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{BACKEND_URL}/api/v1/notifications/pending-telegram")
                if resp.status_code == 200:
                    notifs = resp.json()
                    for n in notifs:
                        tg_id = n.get("telegram_id")
                        if not tg_id:
                            continue
                        role_label = ROLE_LABELS.get(n.get("role", ""), n.get("role", ""))
                        text = (
                            f"{n['title']}\n\n"
                            f"{n['message']}\n\n"
                            f"👤 Sizga: {role_label}"
                        )
                        try:
                            await bot.send_message(tg_id, text)
                            # Yuborildi deb belgilaymiz
                            await client.post(f"{BACKEND_URL}/api/v1/notifications/{n['id']}/mark-sent")
                        except Exception as e:
                            logger.error(f"Notification yuborishda xato: {e}")
        except Exception as e:
            logger.error(f"Notification poller xato: {e}")
        await asyncio.sleep(10)


# =====================
# MAIN
# =====================
async def main():
    logger.info(f"Bot starting... Backend: {BACKEND_URL}")
    # Background notification poller
    asyncio.create_task(notification_poller())
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
