"""
Smart AI Procurement - Telegram Bot
Powered by aiogram 3.x
"""
import asyncio
import logging
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton
)
import httpx
import os

logging.basicConfig(level=logging.INFO)

# ✅ TUZATILDI: os.getenv() ga o'zgaruvchi NOMI beriladi, token emas
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8000")
REDIS_URL = os.getenv("REDIS_URL")

if not BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN environment variable is not set!")

bot = Bot(token=BOT_TOKEN)

if REDIS_URL:
    try:
        storage = RedisStorage.from_url(REDIS_URL)
        logging.info("Redis storage ishlatilmoqda")
    except Exception:
        logging.warning("Redis ulanmadi, MemoryStorage ishlatilmoqda")
        storage = MemoryStorage()
else:
    logging.info("REDIS_URL yo'q, MemoryStorage ishlatilmoqda")
    storage = MemoryStorage()

dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

# User JWT tokenlarini saqlash
user_tokens = {}
user_roles = {}


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


class ExtraOrderStates(StatesGroup):
    customer_name = State()
    choosing_product = State()
    entering_quantity = State()
    delivery_date = State()


class ReceiveStates(StatesGroup):
    choosing_order = State()
    entering_quantity = State()
    confirming = State()


# =====================
# KEYBOARDS
# =====================
def main_menu_keyboard(role: str) -> ReplyKeyboardMarkup:
    buttons = {
        "seller": [
            [KeyboardButton(text="📦 Sotuv kiritish")],
            [KeyboardButton(text="📋 Qo'shimcha zakaz")],
            [KeyboardButton(text="📊 Bugungi sotuvlar")],
            [KeyboardButton(text="🏪 Ombor holati")],
        ],
        "buyer": [
            [KeyboardButton(text="🤖 AI tavsiyalar")],
            [KeyboardButton(text="📝 Zakaz yaratish")],
            [KeyboardButton(text="💰 Narxlar")],
            [KeyboardButton(text="📊 Zakazlar")],
        ],
        "warehouse_manager": [
            [KeyboardButton(text="✅ Zakazlarni tasdiqlash")],
            [KeyboardButton(text="❌ Zakazlarni rad etish")],
            [KeyboardButton(text="📊 Ombor holati")],
        ],
        "goods_receiver": [
            [KeyboardButton(text="📥 Tovar qabul qilish")],
            [KeyboardButton(text="📄 Faktura yuklash")],
            [KeyboardButton(text="📊 Qabul tarixi")],
        ],
        "admin": [
            [KeyboardButton(text="📊 Dashboard")],
            [KeyboardButton(text="👥 Foydalanuvchilar")],
            [KeyboardButton(text="🤖 AI tahlil")],
            [KeyboardButton(text="⚙️ Sozlamalar")],
        ],
    }
    kb_buttons = buttons.get(role, buttons["seller"])
    kb_buttons.append([KeyboardButton(text="🚪 Chiqish")])
    return ReplyKeyboardMarkup(keyboard=kb_buttons, resize_keyboard=True)


# =====================
# API HELPERS
# =====================
async def api_get(endpoint: str, token: str):
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{BACKEND_URL}/api/v1/{endpoint}",
                headers={"Authorization": f"Bearer {token}"},
                timeout=10.0
            )
            return resp.json() if resp.status_code == 200 else None
    except Exception as e:
        logging.error(f"API GET xatolik: {e}")
        return None


async def api_post(endpoint: str, data: dict, token: str = None):
    try:
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{BACKEND_URL}/api/v1/{endpoint}",
                json=data,
                headers=headers,
                timeout=10.0
            )
            return resp.json(), resp.status_code
    except Exception as e:
        logging.error(f"API POST xatolik: {e}")
        return None, 500


# =====================
# AUTH CHECK HELPER
# =====================
def check_auth(tg_id: int) -> bool:
    return tg_id in user_tokens


# =====================
# HANDLERS
# =====================
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    tg_id = message.from_user.id
    if check_auth(tg_id):
        user_data = await api_get("auth/me", user_tokens[tg_id])
        if user_data:
            await message.answer(
                f"👋 Xush kelibsiz, *{user_data['full_name']}*!\n"
                f"Sizning rolingiz: `{user_data['role']}`",
                parse_mode="Markdown",
                reply_markup=main_menu_keyboard(user_data['role'])
            )
            return

    await state.set_state(LoginStates.waiting_username)
    await message.answer(
        "🔐 *Smart AI Procurement System*\n\n"
        "Tizimga kirish uchun login va parolingizni kiriting.\n\n"
        "Login kiriting:",
        parse_mode="Markdown"
    )


@router.message(LoginStates.waiting_username)
async def process_username(message: Message, state: FSMContext):
    await state.update_data(username=message.text)
    await state.set_state(LoginStates.waiting_password)
    await message.answer("🔑 Parol kiriting:")


@router.message(LoginStates.waiting_password)
async def process_password(message: Message, state: FSMContext):
    data = await state.get_data()
    username = data.get("username")
    password = message.text

    try:
        await message.delete()
    except Exception:
        pass

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{BACKEND_URL}/api/v1/auth/login",
                data={"username": username, "password": password},
                timeout=10.0
            )
    except Exception:
        await state.clear()
        await message.answer("❌ Server bilan bog'lanishda xatolik. Keyinroq urinib ko'ring.")
        return

    if resp.status_code == 200:
        result = resp.json()
        token = result["access_token"]
        user = result["user"]
        user_tokens[message.from_user.id] = token
        user_roles[message.from_user.id] = user["role"]
        await state.clear()

        await message.answer(
            f"✅ Muvaffaqiyatli kirildi!\n\n"
            f"Salom, *{user['full_name']}* 👋\n"
            f"Rol: `{user['role']}`",
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard(user["role"])
        )
    else:
        await state.clear()
        await message.answer(
            "❌ Login yoki parol noto'g'ri.\n"
            "/start buyrug'ini yuboring."
        )


# =====================
# ✅ SOTUV KIRITISH
# =====================
@router.message(F.text == "📦 Sotuv kiritish")
async def start_sale(message: Message, state: FSMContext):
    tg_id = message.from_user.id
    if not check_auth(tg_id):
        await message.answer("❌ Avval tizimga kiring: /start")
        return

    products = await api_get("products/", user_tokens[tg_id])
    if not products:
        await message.answer("❌ Mahsulotlar ro'yxatini olishda xatolik")
        return

    text = "📦 *Sotuv kiritish*\n\nMahsulot nomini kiriting:\n\n"
    for i, p in enumerate(products[:15], 1):
        text += f"{i}. {p['name']} ({p.get('unit', 'kg')})\n"

    await state.update_data(products=products)
    await state.set_state(SaleStates.choosing_product)
    await message.answer(text, parse_mode="Markdown")


@router.message(SaleStates.choosing_product)
async def sale_product_chosen(message: Message, state: FSMContext):
    await state.update_data(product_name=message.text)
    await state.set_state(SaleStates.entering_quantity)
    await message.answer("📏 Miqdorni kiriting (kg/dona):")


@router.message(SaleStates.entering_quantity)
async def sale_quantity_entered(message: Message, state: FSMContext):
    try:
        qty = float(message.text.replace(",", "."))
        await state.update_data(quantity=qty)
        await state.set_state(SaleStates.entering_price)
        await message.answer("💰 Narxni kiriting (so'm):")
    except ValueError:
        await message.answer("❌ Raqam kiriting. Masalan: 5.5")


@router.message(SaleStates.entering_price)
async def sale_price_entered(message: Message, state: FSMContext):
    tg_id = message.from_user.id
    try:
        price = float(message.text.replace(",", ".").replace(" ", ""))
        data = await state.get_data()

        sale_data = {
            "product_name": data["product_name"],
            "quantity": data["quantity"],
            "price_per_unit": price,
            "total_amount": data["quantity"] * price,
        }

        result, status = await api_post("sales/", sale_data, user_tokens[tg_id])
        await state.clear()

        if status in (200, 201):
            await message.answer(
                f"✅ *Sotuv saqlandi!*\n\n"
                f"📦 Mahsulot: {sale_data['product_name']}\n"
                f"📏 Miqdor: {sale_data['quantity']}\n"
                f"💰 Jami: {sale_data['total_amount']:,.0f} so'm",
                parse_mode="Markdown"
            )
        else:
            await message.answer("❌ Sotuvni saqlashda xatolik yuz berdi")
    except ValueError:
        await message.answer("❌ Raqam kiriting. Masalan: 15000")


# =====================
# ✅ QO'SHIMCHA ZAKAZ
# =====================
@router.message(F.text == "📋 Qo'shimcha zakaz")
async def start_extra_order(message: Message, state: FSMContext):
    tg_id = message.from_user.id
    if not check_auth(tg_id):
        await message.answer("❌ Avval tizimga kiring: /start")
        return

    await state.set_state(ExtraOrderStates.customer_name)
    await message.answer("👤 Mijoz ismini kiriting:")


@router.message(ExtraOrderStates.customer_name)
async def extra_order_customer(message: Message, state: FSMContext):
    await state.update_data(customer_name=message.text)
    await state.set_state(ExtraOrderStates.choosing_product)
    await message.answer("📦 Mahsulot nomini kiriting:")


@router.message(ExtraOrderStates.choosing_product)
async def extra_order_product(message: Message, state: FSMContext):
    await state.update_data(product_name=message.text)
    await state.set_state(ExtraOrderStates.entering_quantity)
    await message.answer("📏 Miqdorni kiriting:")


@router.message(ExtraOrderStates.entering_quantity)
async def extra_order_quantity(message: Message, state: FSMContext):
    try:
        qty = float(message.text.replace(",", "."))
        data = await state.get_data()
        tg_id = message.from_user.id

        order_data = {
            "customer_name": data["customer_name"],
            "product_name": data["product_name"],
            "quantity": qty,
        }

        result, status = await api_post("sales/extra-order", order_data, user_tokens[tg_id])
        await state.clear()

        if status in (200, 201):
            await message.answer(
                f"✅ *Qo'shimcha zakaz saqlandi!*\n\n"
                f"👤 Mijoz: {order_data['customer_name']}\n"
                f"📦 Mahsulot: {order_data['product_name']}\n"
                f"📏 Miqdor: {qty}",
                parse_mode="Markdown"
            )
        else:
            await message.answer("❌ Zakazni saqlashda xatolik")
    except ValueError:
        await message.answer("❌ Raqam kiriting")


# =====================
# AI TAVSIYALAR
# =====================
@router.message(F.text == "🤖 AI tavsiyalar")
async def ai_recommendations(message: Message):
    tg_id = message.from_user.id
    if not check_auth(tg_id):
        await message.answer("❌ Avval tizimga kiring: /start")
        return

    await message.answer("🔄 AI tahlil yuklanmoqda...")
    data = await api_get("ai/latest", user_tokens[tg_id])

    if not data:
        await message.answer("❌ Tavsiyalar topilmadi. Avval AI tahlil o'tkazing.")
        return

    text = "🤖 *AI Tavsiyalari*\n\n"
    for item in data[:10]:
        emoji = "🔴" if item["recommended_order"] > 0 else "🟢"
        text += (
            f"{emoji} *{item['product_name']}*\n"
            f"  📦 Omborda: {item['current_stock']} {item['unit']}\n"
            f"  📈 Prognoz: {item['forecast_demand']:.1f} {item['unit']}\n"
            f"  🛒 Buyurtma: *{item['recommended_order']:.1f} {item['unit']}*\n"
            f"  🎯 Ishonch: {item['confidence']*100:.0f}%\n\n"
        )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Zakaz yaratish", callback_data="create_from_ai")]
    ])
    await message.answer(text, parse_mode="Markdown", reply_markup=keyboard)


# =====================
# BUGUNGI SOTUVLAR
# =====================
@router.message(F.text == "📊 Bugungi sotuvlar")
async def today_sales(message: Message):
    tg_id = message.from_user.id
    if not check_auth(tg_id):
        await message.answer("❌ Avval tizimga kiring: /start")
        return

    data = await api_get("sales/today", user_tokens[tg_id])
    if not data:
        await message.answer("❌ Ma'lumot olishda xatolik")
        return

    text = "📊 *Bugungi Sotuvlar*\n\n"
    text += f"Jami tranzaksiyalar: {data['count']}\n"
    text += f"Jami tushum: *{data['total_revenue']:,.0f} so'm*\n\n"

    for sale in data.get('sales', [])[:10]:
        text += f"• {sale['product_name']}: {sale['quantity']} — {sale['total_amount']:,.0f} so'm\n"

    await message.answer(text, parse_mode="Markdown")


# =====================
# OMBOR HOLATI
# =====================
@router.message(F.text == "🏪 Ombor holati")
async def warehouse_status(message: Message):
    tg_id = message.from_user.id
    if not check_auth(tg_id):
        await message.answer("❌ Avval tizimga kiring: /start")
        return

    data = await api_get("products/stock", user_tokens[tg_id])
    if not data:
        await message.answer("❌ Ombor ma'lumotlarini olishda xatolik")
        return

    text = "🏪 *Ombor Holati*\n\n"
    for item in data[:15]:
        emoji = "🔴" if item.get("stock", 0) < item.get("min_stock", 10) else "🟢"
        text += f"{emoji} {item['name']}: *{item.get('stock', 0)}* {item.get('unit', 'kg')}\n"

    await message.answer(text, parse_mode="Markdown")


# =====================
# ZAKAZLARNI TASDIQLASH
# =====================
@router.message(F.text == "✅ Zakazlarni tasdiqlash")
async def pending_approvals(message: Message):
    tg_id = message.from_user.id
    if not check_auth(tg_id):
        await message.answer("❌ Avval tizimga kiring: /start")
        return

    data = await api_get("procurement/?status=buyer_confirmed", user_tokens[tg_id])
    if not data:
        await message.answer("📭 Tasdiqlash kutayotgan zakazlar yo'q")
        return

    for order in data:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"approve_{order['id']}"),
                InlineKeyboardButton(text="❌ Rad etish", callback_data=f"reject_{order['id']}"),
            ]
        ])
        text = (
            f"📋 *{order['order_number']}*\n"
            f"Holat: {order['status']}\n"
            f"Narx: {order['total_estimated_cost']:,.0f} so'm"
        )
        await message.answer(text, parse_mode="Markdown", reply_markup=keyboard)


@router.callback_query(F.data.startswith("approve_"))
async def approve_order(callback: CallbackQuery):
    order_id = callback.data.split("_")[1]
    tg_id = callback.from_user.id
    if not check_auth(tg_id):
        await callback.answer("❌ Avval tizimga kiring")
        return

    data, status = await api_post(
        f"procurement/{order_id}/approve",
        {"notes": "Telegram orqali tasdiqlandi"},
        user_tokens[tg_id]
    )
    if status == 200:
        await callback.message.edit_text(f"✅ Zakaz tasdiqlandi!\n{callback.message.text}")
        await callback.answer("✅ Muvaffaqiyatli tasdiqlandi")
    else:
        await callback.answer("❌ Xatolik yuz berdi")


@router.callback_query(F.data.startswith("reject_"))
async def reject_order(callback: CallbackQuery):
    order_id = callback.data.split("_")[1]
    tg_id = callback.from_user.id
    if not check_auth(tg_id):
        await callback.answer("❌ Avval tizimga kiring")
        return

    data, status = await api_post(
        f"procurement/{order_id}/reject",
        {"notes": "Telegram orqali rad etildi"},
        user_tokens[tg_id]
    )
    if status == 200:
        await callback.message.edit_text(f"❌ Zakaz rad etildi.\n{callback.message.text}")
        await callback.answer("✅ Rad etildi")
    else:
        await callback.answer("❌ Xatolik yuz berdi")


# =====================
# ✅ TOVAR QABUL QILISH
# =====================
@router.message(F.text == "📥 Tovar qabul qilish")
async def receive_goods(message: Message, state: FSMContext):
    tg_id = message.from_user.id
    if not check_auth(tg_id):
        await message.answer("❌ Avval tizimga kiring: /start")
        return

    data = await api_get("procurement/?status=approved", user_tokens[tg_id])
    if not data:
        await message.answer("📭 Qabul qilish uchun tovar yo'q")
        return

    text = "📥 *Qabul qilinishi kerak bo'lgan tovarlar:*\n\n"
    keyboard_buttons = []
    for order in data[:10]:
        text += f"• {order['order_number']} — {order.get('total_estimated_cost', 0):,.0f} so'm\n"
        keyboard_buttons.append([
            InlineKeyboardButton(
                text=f"📥 {order['order_number']}",
                callback_data=f"receive_{order['id']}"
            )
        ])

    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    await message.answer(text, parse_mode="Markdown", reply_markup=keyboard)


@router.callback_query(F.data.startswith("receive_"))
async def confirm_receive(callback: CallbackQuery):
    order_id = callback.data.split("_")[1]
    tg_id = callback.from_user.id
    if not check_auth(tg_id):
        await callback.answer("❌ Avval tizimga kiring")
        return

    data, status = await api_post(
        f"procurement/{order_id}/receive",
        {"notes": "Telegram orqali qabul qilindi"},
        user_tokens[tg_id]
    )
    if status == 200:
        await callback.message.edit_text(f"✅ Tovar qabul qilindi!\n{callback.message.text}")
        await callback.answer("✅ Muvaffaqiyatli qabul qilindi")
    else:
        await callback.answer("❌ Xatolik yuz berdi")


# =====================
# CHIQISH
# =====================
@router.message(F.text == "🚪 Chiqish")
async def logout(message: Message, state: FSMContext):
    user_tokens.pop(message.from_user.id, None)
    user_roles.pop(message.from_user.id, None)
    await state.clear()
    await message.answer(
        "👋 Tizimdan chiqdingiz.\n"
        "Qaytib kirish uchun /start bosing."
    )


# =====================
# MAIN
# =====================
async def main():
    logging.info("Bot ishga tushmoqda...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
