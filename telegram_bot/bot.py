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
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
import httpx
import os

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8000")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")

bot = Bot(token=BOT_TOKEN)
storage = RedisStorage.from_url(REDIS_URL)
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

# User sessions stored in Redis via FSM
user_tokens = {}  # telegram_id -> jwt_token


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


async def api_get(endpoint: str, token: str):
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{BACKEND_URL}/api/v1/{endpoint}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10.0
        )
        return resp.json() if resp.status_code == 200 else None


async def api_post(endpoint: str, data: dict, token: str):
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{BACKEND_URL}/api/v1/{endpoint}",
            json=data,
            headers={"Authorization": f"Bearer {token}"},
            timeout=10.0
        )
        return resp.json(), resp.status_code


# =====================
# HANDLERS
# =====================
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    tg_id = message.from_user.id
    if tg_id in user_tokens:
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

    await message.delete()  # Delete password from chat

    # Authenticate with backend
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{BACKEND_URL}/api/v1/auth/login",
            data={"username": username, "password": password},
        )

    if resp.status_code == 200:
        result = resp.json()
        token = result["access_token"]
        user = result["user"]
        user_tokens[message.from_user.id] = token
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
            "❌ Login yoki parol noto'g'ri. Qaytadan urinib ko'ring.\n"
            "/start buyrug'ini yuboring."
        )


@router.message(F.text == "🤖 AI tavsiyalar")
async def ai_recommendations(message: Message):
    tg_id = message.from_user.id
    if tg_id not in user_tokens:
        await message.answer("❌ Avval tizimga kiring: /start")
        return

    await message.answer("🔄 AI tahlil yuklanmoqda...")
    data = await api_get("ai/latest", user_tokens[tg_id])

    if not data:
        await message.answer("❌ Tavsiyalar topilmadi. Avval AI tahlil o'tkazing.")
        return

    text = "🤖 *AI Tavsiyalari*\n\n"
    for item in data[:10]:  # Top 10
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


@router.message(F.text == "📊 Bugungi sotuvlar")
async def today_sales(message: Message):
    tg_id = message.from_user.id
    if tg_id not in user_tokens:
        await message.answer("❌ Avval tizimga kiring: /start")
        return

    data = await api_get("sales/today", user_tokens[tg_id])
    if not data:
        await message.answer("❌ Ma'lumot olishda xatolik")
        return

    text = f"📊 *Bugungi Sotuvlar*\n\n"
    text += f"Jami tranzaksiyalar: {data['count']}\n"
    text += f"Jami tushum: *{data['total_revenue']:,.0f} so'm*\n\n"

    for sale in data['sales'][:10]:
        text += f"• {sale['product_name']}: {sale['quantity']} {sale.get('unit','kg')} — {sale['total_amount']:,.0f} so'm\n"

    await message.answer(text, parse_mode="Markdown")


@router.message(F.text == "✅ Zakazlarni tasdiqlash")
async def pending_approvals(message: Message):
    tg_id = message.from_user.id
    if tg_id not in user_tokens:
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
    if tg_id not in user_tokens:
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
    if tg_id not in user_tokens:
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


@router.message(F.text == "🚪 Chiqish")
async def logout(message: Message, state: FSMContext):
    user_tokens.pop(message.from_user.id, None)
    await state.clear()
    await message.answer("👋 Tizimdan chiqdingiz. Qaytib kirish uchun /start")


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
