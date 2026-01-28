import asyncio
import aiosqlite
import uuid
from datetime import datetime
from aiogram import Bot, Dispatcher
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
import os
import hashlib
from html import escape

def safe_html(text: str) -> str:
    """Экранирует все пользовательские данные для безопасной отправки в HTML"""
    return escape(str(text), quote=False)

# === CONFIG ===
CHANNEL_ID = -1003636871446
REF_CHANNEL_ID = -1003881721950
BOT_TOKEN = "8550339613:AAHO_kfhWKXDbatTNq9ZWQk18NU3PnCMncg"
ADMIN_ID = 5117013161
DB_PATH = os.path.abspath("data.db")
REFERRAL_PERCENT = 0.50

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# === DB INIT ===
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                city TEXT DEFAULT '',
                referrer_id TEXT DEFAULT NULL,
                join_date TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS team_members (
                user_id TEXT PRIMARY KEY,
                join_date TEXT DEFAULT CURRENT_TIMESTAMP,
                total_earned REAL DEFAULT 0,
                withdrawn REAL DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                price_per_gram REAL NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                order_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                referrer_id TEXT DEFAULT NULL,
                product TEXT NOT NULL,
                weight REAL NOT NULL,
                total REAL NOT NULL,
                city TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                timestamp TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS withdrawals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                amount REAL NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                processed_at TEXT DEFAULT NULL
            )
        """)
        await db.commit()

# === UTILS ===
async def ensure_user(user_id: str, referrer_id: str = None):
    async with aiosqlite.connect(DB_PATH) as db:
        if referrer_id:
            await db.execute(
                "INSERT OR IGNORE INTO users (user_id, referrer_id, join_date) VALUES (?, ?, ?)",
                (user_id, referrer_id, datetime.now().isoformat())
            )
        else:
            await db.execute(
                "INSERT OR IGNORE INTO users (user_id, join_date) VALUES (?, ?)",
                (user_id, datetime.now().isoformat())
            )
        await db.commit()

async def get_user(user_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT city, referrer_id FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            return {"city": row[0] if row else "", "referrer_id": row[1] if row else None}

async def set_user_city(user_id: str, city: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO users (user_id, city, join_date)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET city = excluded.city
        """, (user_id, city))
        await db.commit()

async def is_team_member(user_id: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT 1 FROM team_members WHERE user_id = ?", (user_id,)) as cur:
            return await cur.fetchone() is not None

async def add_to_team(user_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO team_members (user_id, join_date) VALUES (?, ?)",
            (user_id, datetime.now().isoformat())
        )
        await db.commit()

async def get_referral_stats(user_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM users WHERE referrer_id = ?", (user_id,)
        ) as cur:
            invited = (await cur.fetchone())[0]
        
        async with db.execute(
            "SELECT total_earned, withdrawn FROM team_members WHERE user_id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
            earned = row[0] if row else 0
            withdrawn = row[1] if row else 0
        
        async with db.execute(
            "SELECT join_date FROM team_members WHERE user_id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
            join_date = row[0] if row else None
        
        return {
            "invited": invited,
            "earned": earned,
            "withdrawn": withdrawn,
            "profit": earned - withdrawn,
            "join_date": join_date
        }

async def save_order(user_id: str, referrer_id: str, product: str, weight: float, total: float, city: str):
    order_id = str(uuid.uuid4())[:8].upper()
    timestamp = datetime.now().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO orders (order_id, user_id, referrer_id, product, weight, total, city, status, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)",
            (order_id, user_id, referrer_id, product, weight, total, city, timestamp)
        )
        await db.commit()
    return order_id

async def mark_order_paid(order_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT total, referrer_id, user_id FROM orders WHERE order_id = ? AND status = 'pending'", (order_id,)
        ) as cur:
            row = await cur.fetchone()
            if not row:
                return False, None, None
            total, referrer_id, user_id = row
        
        await db.execute("UPDATE orders SET status = 'paid' WHERE order_id = ?", (order_id,))
        await db.commit()
        
        commission = 0
        if referrer_id:
            commission = total * REFERRAL_PERCENT
            async with aiosqlite.connect(DB_PATH) as db2:
                await db2.execute(
                    "UPDATE team_members SET total_earned = total_earned + ? WHERE user_id = ?",
                    (commission, referrer_id)
                )
                await db2.commit()
        
        return True, (referrer_id, commission), user_id

async def mark_order_cancelled(order_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE orders SET status = 'cancelled' WHERE order_id = ? AND status = 'pending'", (order_id,))
        await db.commit()
        return True

async def create_withdrawal_request(user_id: str, amount: float) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO withdrawals (user_id, amount, status, created_at) VALUES (?, ?, 'pending', ?)",
            (user_id, amount, datetime.now().isoformat())
        )
        await db.execute("SELECT last_insert_rowid()")
        rowid = (await db.fetchone())[0]
        await db.commit()
        return rowid

async def process_withdrawal(withdrawal_id: int, approved: bool):
    async with aiosqlite.connect(DB_PATH) as db:
        if approved:
            async with db.execute(
                "SELECT user_id, amount FROM withdrawals WHERE id = ? AND status = 'pending'", (withdrawal_id,)
            ) as cur:
                row = await cur.fetchone()
                if not row:
                    return False
                user_id, amount = row
            
            await db.execute(
                "UPDATE withdrawals SET status = 'approved', processed_at = ? WHERE id = ?",
                (datetime.now().isoformat(), withdrawal_id)
            )
            await db.execute(
                "UPDATE team_members SET withdrawn = withdrawn + ? WHERE user_id = ?",
                (amount, user_id)
            )
            await db.commit()
            return True
        else:
            await db.execute(
                "UPDATE withdrawals SET status = 'rejected', processed_at = ? WHERE id = ?",
                (datetime.now().isoformat(), withdrawal_id)
            )
            await db.commit()
            return True

def get_ref_hash(user_id: str) -> str:
    return hashlib.md5(str(user_id).encode()).hexdigest()[:6]

# === STATES ===
class BuyFlow(StatesGroup):
    choosing_product = State()
    choosing_amount = State()
    confirming = State()

class SettingsFlow(StatesGroup):
    entering_city = State()

# === HANDLERS ===
@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user_id = str(message.from_user.id)
    
    text = "🎉 Добро пожаловать!\nТут ты можешь купить стафф безопасно.\nВся работа проделывается опытными людьми.\nМы гарантируем наход товара при ненаходе — перезаклад!"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 Каталог", callback_data="menu_catalog")],
        [InlineKeyboardButton(text="🛠 Поддержка", callback_data="menu_support")],
        [InlineKeyboardButton(text="⚙️ Настройки", callback_data="menu_settings")]
    ])
    
    await message.answer(text, reply_markup=kb)

@dp.message(Command("work"))
async def cmd_work(message: Message, state: FSMContext):
    await state.clear()
    user_id = str(message.from_user.id)
    
    if not await is_team_member(user_id):
        return
    
    text = "🎉 Добро пожаловать!\nТут ты можешь купить стафф безопасно.\nВся работа проделывается опытными людьми.\nМы гарантируем наход товара при ненаходе — перезаклад!"
    
    kb1 = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Профиль", callback_data="menu_profile")],
        [InlineKeyboardButton(text="💼 Ворк", callback_data="menu_work")],
        [InlineKeyboardButton(text="💬 Написать в поддержку", url="https://t.me/feeddrugbot")]
    ])
    
    await message.answer(text, reply_markup=kb1)

@dp.callback_query(lambda c: c.data == "menu_profile")
async def show_profile(callback: CallbackQuery):
    user_id = str(callback.from_user.id)
    stats = await get_referral_stats(user_id)
    join_date = stats["join_date"]
    if join_date:
        join_date = join_date.split("T")[0]
    
    ref_link = f"https://t.me/drugrbot?start=ref_{get_ref_hash(user_id)}"
    
    text = (
        f"<b>👤 Профиль</b>\n\n"
        f"🆔 ID: <code>{safe_html(user_id)}</code>\n"
        f"📅 В команде с: {safe_html(join_date or '—')}\n"
        f"👥 Привлечено: {stats['invited']} чел.\n"
        f"🔗 Реф. ссылка: <a href='{ref_link}'>t.me/drugrbot?start=ref_{get_ref_hash(user_id)}</a>"
    )
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_mainw")]
        ])
    )

@dp.callback_query(lambda c: c.data == "menu_work")
async def show_work(callback: CallbackQuery):
    user_id = str(callback.from_user.id)
    stats = await get_referral_stats(user_id)
    
    text = (
        f"<b>💼 Ворк</b>\n\n"
        f"👥 Приглашённых: {stats['invited']}\n"
        f"💰 Заработано: {stats['earned']:.2f}₽ (50% от заказов)\n"
        f"📊 Профит: {stats['profit']:.2f}₽\n"
        f"💳 К выводу: {stats['profit']:.2f}₽\n\n"
        f"<i>Чтобы вывести средства, напишите:</i>\n"
        f"<code>/win сумма</code>"
    )
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_mainw")]
        ])
    )

@dp.callback_query(lambda c: c.data == "menu_settings")
async def show_settings(callback: CallbackQuery, state: FSMContext):
    user_id = str(callback.from_user.id)
    username = callback.from_user.username or "не указан"
    user = await get_user(user_id)
    city = user["city"] if user["city"] else "не выбран"
    
    text = (
        f"<b>⚙️ Настройки</b>\n"
        f"ID: <code>{safe_html(user_id)}</code>\n"
        f"Юзернейм: @{safe_html(username)}\n"
        f"Город: {safe_html(city)}"
    )
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏙 Выбрать город", callback_data="choose_city")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")]
        ])
    )

@dp.callback_query(lambda c: c.data == "choose_city")
async def choose_city(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("🏙 Введите название города:")
    await state.set_state(SettingsFlow.entering_city)

@dp.message(SettingsFlow.entering_city)
async def process_city_input(message: Message, state: FSMContext):
    city = message.text.strip()
    if not city:
        await message.answer("❌ Название не может быть пустым. Введите город:")
        return
    user_id = str(message.from_user.id)
    await set_user_city(user_id, city)
    await state.clear()
    await message.answer(f"✅ Город сохранён: <b>{safe_html(city)}</b>")
    await cmd_start(message, state)

@dp.callback_query(lambda c: c.data == "menu_catalog")
async def show_catalog(callback: CallbackQuery, state: FSMContext):
    user_id = str(callback.from_user.id)
    user = await get_user(user_id)
    if not user["city"]:
        await callback.answer("❌ Сначала укажите город в настройках!", show_alert=True)
        return

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id, name, price_per_gram FROM products") as cur:
            products = {str(r[0]): {"name": r[1], "price": r[2]} for r in await cur.fetchall()}
    
    if not products:
        await callback.answer("Каталог пуст", show_alert=True)
        return

    buttons = [
        [InlineKeyboardButton(
            text=f"{p['name']} ({p['price']}₽/г)",
            callback_data=f"prod_{p_id}"
        )]
        for p_id, p in products.items()
    ]
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")])
    await callback.message.edit_text(
        "Выберите товар:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await state.set_state(BuyFlow.choosing_product)

@dp.callback_query(lambda c: c.data.startswith("prod_"))
async def choose_amount(callback: CallbackQuery, state: FSMContext):
    product_id = callback.data[5:]
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT name, price_per_gram FROM products WHERE id = ?", (int(product_id),)
        ) as cur:
            row = await cur.fetchone()
            if not row:
                await callback.answer("Товар удалён", show_alert=True)
                return
            product = {"name": row[0], "price": row[1]}
    
    await state.update_data(product_id=product_id, price=product["price"])
    await callback.message.edit_text(
        f"Товар: <b>{safe_html(product['name'])}</b> ({product['price']}₽/г)\n"
        "Введите желаемый вес в граммах (от 0.1 до 5):"
    )
    await state.set_state(BuyFlow.choosing_amount)

@dp.message(BuyFlow.choosing_amount)
async def process_weight_input(message: Message, state: FSMContext):
    try:
        weight = float(message.text.strip().replace(',', '.'))
        if weight < 0.1 or weight > 5:
            raise ValueError
    except (ValueError, TypeError):
        await message.answer("❌ Введите число от 0.1 до 5 (например: 0.5, 1.25, 3):")
        return

    data = await state.get_data()
    if "price" not in data or "product_id" not in data:
        await message.answer("❌ Сессия устарела. Начните заново.")
        await state.clear()
        return

    total = round(weight * data["price"], 2)
    user_id = str(message.from_user.id)
    user = await get_user(user_id)
    city = user["city"] or "не указан"
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT name FROM products WHERE id = ?", (int(data["product_id"]),)
        ) as cur:
            row = await cur.fetchone()
            product_name = row[0] if row else "—"
    
    await state.update_data(weight=weight, total=total, product_name=product_name)
    await message.answer(
        f"<b>Подтверждение:</b>\n"
        f"Товар: {safe_html(product_name)}\n"
        f"Вес: {weight}г\n"
        f"Сумма: {total}₽\n"
        f"Город доставки: {safe_html(city)}\n\n"
        f"❗ После подтверждения напишите @feeddrugbot для оплаты",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"confirm_{data['product_id']}_{weight}_{total}")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="menu_catalog")]
        ])
    )
    await state.set_state(BuyFlow.confirming)

@dp.callback_query(lambda c: c.data.startswith("confirm_"))
async def confirm_order(callback: CallbackQuery, state: FSMContext):
    try:
        _, product_id, weight_str, total_str = callback.data.split("_")
        weight = float(weight_str)
        total = float(total_str)
        user_id = str(callback.from_user.id)
    except Exception:
        await callback.answer("❌ Ошибка данных", show_alert=True)
        return
    
    data = await state.get_data()
    product_name = data.get("product_name", "—")
    user = await get_user(user_id)
    city = user["city"] or "—"
    referrer_id = user["referrer_id"]
    
    order_id = await save_order(user_id, referrer_id, product_name, weight, total, city)
    
    username = f"@{callback.from_user.username}" if callback.from_user.username else "—"
    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ ОПЛАТИЛ", callback_data=f"paid_{order_id}"),
            InlineKeyboardButton(text="❌ НЕ ОПЛАТИЛ", callback_data=f"cancelled_{order_id}")
        ]
    ])
    
    await bot.send_message(
        CHANNEL_ID,
        f"🆕 <b>Новый заказ!</b>\n\n"
        f"🆔 ID: <code>{safe_html(order_id)}</code>\n"
        f"👤 Юзер: {safe_html(callback.from_user.first_name)} ({safe_html(username)})\n"
        f"📦 Товар: {safe_html(product_name)}\n"
        f"⚖️ Вес: {weight}г | 💰 Сумма: {total}₽\n"
        f"🏙 Город: {safe_html(city)}\n"
        f"🔗 Реферер: {safe_html(referrer_id or '—')}\n"
        f"⏳ Статус: <b>ожидает оплаты</b>",
        reply_markup=admin_kb
    )
    
    await callback.message.edit_text(
        f"✅ Заказ создан!\n<b>ID заказа:</b> <code>{safe_html(order_id)}</code>\n\n"
        f"💬 Напишите @feeddrugbot для оплаты и получения закладки",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💬 Написать в поддержку", url="https://t.me/feeddrugbot")]
        ])
    )
    await state.clear()

@dp.callback_query(lambda c: c.data.startswith("paid_"))
async def mark_paid(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Только админ", show_alert=True)
        return
    
    order_id = callback.data[5:]
    success, ref_data, user_id = await mark_order_paid(order_id)
    
    if not success:
        await callback.answer("❌ Заказ уже обработан или не найден", show_alert=True)
        return
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT user_id, total, referrer_id, product, weight FROM orders WHERE order_id = ?", (order_id,)
        ) as cur:
            row = await cur.fetchone()
            buyer_id, total, referrer_id, product, weight = row
    
    try:
        await bot.send_message(
            buyer_id,
            f"✅ Ваш заказ <code>{safe_html(order_id)}</code> оплачен!\n"
            f"Ожидайте сообщения от закладчика."
        )
    except:
        pass
    
    commission = 0
    ref_username = "—"
    buyer_username = "—"
    
    try:
        buyer_chat = await bot.get_chat(buyer_id)
        buyer_username = f"@{buyer_chat.username}" if buyer_chat.username else buyer_chat.first_name
    except:
        pass
    
    if ref_data and ref_data[0]:
        referrer_id, commission = ref_data
        try:
            ref_chat = await bot.get_chat(referrer_id)
            ref_username = f"@{ref_chat.username}" if ref_chat.username else ref_chat.first_name
        except:
            pass
        
        try:
            await bot.send_message(
                referrer_id,
                f"💰 <b>Начислено {commission:.2f}₽</b>\n"
                f"За заказ <code>{safe_html(order_id)}</code> вашего реферала {safe_html(buyer_username)}"
            )
        except:
            pass
        
        # ИСПРАВЛЕНО: убраны все ссылки и добавлено экранирование
        try:
            await bot.send_message(
                REF_CHANNEL_ID,
                f"💸 <b>НОВОЕ НАЧИСЛЕНИЕ!</b>\n\n"
                f"🆔 Заказ: <code>{safe_html(order_id)}</code>\n"
                f"👤 Реферер: {safe_html(ref_username)} (<code>{safe_html(referrer_id)}</code>)\n"
                f"🛒 Покупатель: {safe_html(buyer_username)} (<code>{safe_html(buyer_id)}</code>)\n"
                f"📦 Товар: {safe_html(product)} ({weight}г)\n"
                f"💰 Сумма заказа: {total:.2f}₽\n"
                f"📊 Профит рефера: {commission:.2f}₽ (50%)\n"
                f"⏰ {datetime.now().strftime('%d.%m.%Y %H:%M')}"
            )
        except Exception as e:
            print(f"⚠️ Не удалось отправить в канал рефералок: {e}")
    
    await callback.message.edit_text(
        callback.message.text.replace(
            "⏳ Статус: <b>ожидает оплаты</b>",
            f"✅ Статус: <b>оплачен</b>\n💵 Рефереру начислено: {commission:.2f}₽"
        ),
        reply_markup=None
    )
    await callback.answer("✅ Заказ оплачен", show_alert=True)

@dp.callback_query(lambda c: c.data.startswith("cancelled_"))
async def mark_cancelled(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Только админ", show_alert=True)
        return
    
    order_id = callback.data[10:]
    success = await mark_order_cancelled(order_id)
    
    if not success:
        await callback.answer("❌ Заказ уже обработан", show_alert=True)
        return
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT user_id FROM orders WHERE order_id = ?", (order_id,)
        ) as cur:
            row = await cur.fetchone()
            user_id = row[0] if row else None
    
    if user_id:
        try:
            await bot.send_message(
                user_id,
                f"❌ Ваш заказ <code>{safe_html(order_id)}</code> отменён (не оплачен)."
            )
        except:
            pass
    
    await callback.message.edit_text(
        callback.message.text.replace(
            "⏳ Статус: <b>ожидает оплаты</b>",
            "❌ Статус: <b>не оплачен</b>\n🚫 Рефереру ничего не начислено"
        ),
        reply_markup=None
    )
    await callback.answer("❌ Заказ отменён", show_alert=True)

@dp.callback_query(lambda c: c.data == "menu_support")
async def support(callback: CallbackQuery):
    await callback.message.edit_text(
        "🛠 Напишите @feeddrugbot для связи с поддержкой",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💬 Написать в поддержку", url="https://t.me/feeddrugbot")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")]
        ])
    )

@dp.callback_query(lambda c: c.data == "back_to_main")
async def back_to_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await cmd_start(callback.message, state)

@dp.callback_query(lambda c: c.data == "back_to_mainw")
async def back_to_mainw(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = str(callback.from_user.id)
    
    if not await is_team_member(user_id):
        await callback.answer("❌ Доступ запрещён", show_alert=True)
        return
    
    text = "🎉 Добро пожаловать!\nТут ты можешь купить стафф безопасно.\nВся работа проделывается опытными людьми.\nМы гарантируем наход товара при ненаходе — перезаклад!"
    
    kb1 = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Профиль", callback_data="menu_profile")],
        [InlineKeyboardButton(text="💼 Ворк", callback_data="menu_work")],
        [InlineKeyboardButton(text="💬 Написать в поддержку", url="https://t.me/feeddrugbot")]
    ])
    
    await callback.message.edit_text(text, reply_markup=kb1)
    await callback.answer()

# === WITHDRAWAL HANDLERS ===
@dp.message(Command("win"))
async def cmd_withdraw(message: Message):
    user_id = str(message.from_user.id)
    
    if not await is_team_member(user_id):
        await message.answer("❌ Вы не состоите в команде. Сначала получите приглашение от админа.")
        return
    
    try:
        _, amount_str = message.text.split()
        amount = float(amount_str)
        if amount <= 0:
            raise ValueError
    except (ValueError, TypeError):
        await message.answer(
            "❌ Неверный формат.\n"
            "Используйте: <code>/win 1500</code>\n"
            "Минимальная сумма вывода: 500₽"
        )
        return
    
    if amount < 500:
        await message.answer("❌ Минимальная сумма вывода: 500₽")
        return
    
    stats = await get_referral_stats(user_id)
    if amount > stats["profit"]:
        await message.answer(
            f"❌ Недостаточно средств для вывода.\n"
            f"Ваш профит: {stats['profit']:.2f}₽\n"
            f"Запрошено: {amount:.2f}₽"
        )
        return
    
    withdrawal_id = await create_withdrawal_request(user_id, amount)
    username = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name
    
    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"win_approve_{withdrawal_id}_{user_id}_{amount}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"win_reject_{withdrawal_id}_{user_id}")
        ]
    ])
    
    await bot.send_message(
        ADMIN_ID,
        f"📥 <b>НОВАЯ ЗАЯВКА НА ВЫВОД</b>\n\n"
        f"🆔 ID заявки: <code>{safe_html(withdrawal_id)}</code>\n"
        f"👤 Воркер: {safe_html(username)} (<code>{safe_html(user_id)}</code>)\n"
        f"💰 Сумма: {amount:.2f}₽\n"
        f"📊 Профит до вывода: {stats['profit']:.2f}₽\n"
        f"👥 Привлечено: {stats['invited']} чел.\n"
        f"⏰ {datetime.now().strftime('%d.%m.%Y %H:%M')}",
        reply_markup=admin_kb
    )
    
    await message.answer(
        f"✅ Заявка на вывод создана!\n\n"
        f"🆔 ID заявки: <code>{safe_html(withdrawal_id)}</code>\n"
        f"💰 Сумма: {amount:.2f}₽\n"
        f"⏳ Ожидайте подтверждения от админа."
    )

@dp.callback_query(lambda c: c.data.startswith("win_approve_"))
async def approve_withdrawal(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Только админ", show_alert=True)
        return
    
    try:
        _, _, withdrawal_id, user_id, amount_str = callback.data.split("_")
        withdrawal_id = int(withdrawal_id)
        amount = float(amount_str)
    except Exception as e:
        await callback.answer(f"❌ Ошибка данных: {e}", show_alert=True)
        return
    
    success = await process_withdrawal(withdrawal_id, True)
    
    if not success:
        await callback.answer("❌ Заявка уже обработана", show_alert=True)
        return
    
    try:
        await bot.send_message(
            user_id,
            f"✅ <b>ВЫВОД ПОДТВЕРЖДЁН!</b>\n\n"
            f"🆔 Заявка: <code>{safe_html(withdrawal_id)}</code>\n"
            f"💰 Сумма: {amount:.2f}₽\n"
            f"💳 Средства будут переведены в ближайшее время.\n"
            f"Спасибо за работу! 💪"
        )
    except:
        pass
    
    await callback.message.edit_text(
        callback.message.text + f"\n\n✅ <b>ПОДТВЕРЖДЕНО</b> админом {datetime.now().strftime('%H:%M')}\n"
        f"Сумма: {amount:.2f}₽ переведена"
    )
    await callback.answer("✅ Вывод подтверждён", show_alert=True)

@dp.callback_query(lambda c: c.data.startswith("win_reject_"))
async def reject_withdrawal(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Только админ", show_alert=True)
        return
    
    try:
        _, _, withdrawal_id, user_id = callback.data.split("_")
        withdrawal_id = int(withdrawal_id)
    except Exception as e:
        await callback.answer(f"❌ Ошибка данных: {e}", show_alert=True)
        return
    
    success = await process_withdrawal(withdrawal_id, False)
    
    if not success:
        await callback.answer("❌ Заявка уже обработана", show_alert=True)
        return
    
    try:
        await bot.send_message(
            user_id,
            f"❌ <b>ВЫВОД ОТКЛОНЁН</b>\n\n"
            f"🆔 Заявка: <code>{safe_html(withdrawal_id)}</code>\n"
            f"💬 Свяжитесь с админом для уточнения причины."
        )
    except:
        pass
    
    await callback.message.edit_text(
        callback.message.text + f"\n\n❌ <b>ОТКЛОНЁНО</b> админом {datetime.now().strftime('%H:%M')}"
    )
    await callback.answer("❌ Вывод отклонён", show_alert=True)

# === ADMIN COMMANDS ===
@dp.message(Command("delteam"))
async def cmd_delteam(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    
    try:
        _, user_id = message.text.split()
    except ValueError:
        await message.answer("❌ Укажите ID пользователя: /delteam 123456789")
        return
    
    if not await is_team_member(user_id):
        await message.answer(f"❌ Пользователь {user_id} не состоит в команде.")
        return
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM team_members WHERE user_id = ?", (user_id,))
        await db.commit()
    
    try:
        await bot.send_message(
            user_id,
            "⚠️ Вы удалены из команды.\n\n"
            "Больше не получаете реферальные начисления и доступ к ворк-меню.\n"
            "Ваши заказы как клиента сохранены."
        )
    except:
        pass
    
    await message.answer(f"✅ Пользователь {user_id} удалён из команды.")

@dp.message(Command("teamlist"))
async def cmd_teamlist(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT tm.user_id, tm.join_date, tm.total_earned, tm.withdrawn, u.referrer_id
            FROM team_members tm
            LEFT JOIN users u ON tm.user_id = u.user_id
            ORDER BY tm.total_earned DESC
        """) as cur:
            rows = await cur.fetchall()
    
    if not rows:
        await message.answer("📭 Команда пуста.")
        return
    
    text = "<b>👥 Состав команды:</b>\n\n"
    for user_id, join_date, earned, withdrawn, referrer_id in rows:
        try:
            chat = await bot.get_chat(user_id)
            username = f"@{chat.username}" if chat.username else chat.first_name
            name_part = f"{username}"
        except:
            name_part = "Неизвестно"
        
        profit = earned - withdrawn
        join_short = join_date.split("T")[0] if join_date else "—"
        text += (
            f"🆔 <code>{safe_html(user_id)}</code>\n"
            f"👤 {safe_html(name_part)}\n"
            f"💰 Заработано: {earned:.2f}₽ | Выведено: {withdrawn:.2f}₽ | Профит: {profit:.2f}₽\n"
            f"📅 В команде с: {safe_html(join_short)}\n"
            f"{'—' * 20}\n"
        )
    
    await message.answer(text[:4096])

@dp.message(Command("ad"))
async def cmd_admin_help(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    
    text = (
        "<b>🛠 Команды админа:</b>\n\n"
        "• <code>/team user_id</code> — добавить юзера в команду\n"
        "• <code>/delteam user_id</code> — удалить юзера из команды ⚠️\n"
        "• <code>/teamlist</code> — список команды с доходами 💰\n"
        "• <code>/users</code> — список юзеров с заказами\n"
        "• <code>/ord user_id</code> — заказы юзера\n"
        "• <code>/addprod Название Цена</code> — добавить товар\n"
        "• <code>/delprod ID</code> — удалить товар\n"
        "• <code>/prod</code> — список товаров\n"
        "• <code>/win</code> — обработка выводов (авто через кнопки)\n\n"
        "<b>В канале заказов:</b>\n"
        "✅ ОПЛАТИЛ — начислить рефералку\n"
        "❌ НЕ ОПЛАТИЛ — не начислять"
    )
    await message.answer(text)

@dp.message(Command("team"))
async def cmd_team(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        _, user_id = message.text.split()
        await add_to_team(user_id)
        try:
            await bot.send_message(
                user_id,
                "🎉 Вы добавлены в команду!\n"
                f"Ваша реф.ссылка: <code>ref_{get_ref_hash(user_id)}</code>\n"
                "Давайте её друзьям и получайте 50% от их заказов!\n\n"
                "<i>Для вывода заработка используйте команду:</i>\n"
                "<code>/win сумма</code>"
            )
        except:
            pass
        await message.answer(f"✅ Пользователь {user_id} добавлен в команду")
    except Exception as e:
        await message.answer(f"❌ Использование: /team user_id\nОшибка: {e}")

@dp.message(Command("users"))
async def admin_list_users_with_orders(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT DISTINCT o.user_id, u.referrer_id 
            FROM orders o 
            LEFT JOIN users u ON o.user_id = u.user_id
            ORDER BY o.timestamp DESC
        """) as cur:
            rows = await cur.fetchall()

        if not rows:
            await message.answer("📭 Нет пользователей с заказами.")
            return

        text = "<b>Пользователи с заказами:</b>\n\n"
        for user_id, referrer_id in rows:
            try:
                chat = await bot.get_chat(user_id)
                username = f"@{chat.username}" if chat.username else chat.first_name
                name_part = f"{username}"
            except Exception:
                name_part = "Неизвестно"

            text += f"ID: <code>{safe_html(user_id)}</code> | {safe_html(name_part)} | Реферер: {safe_html(referrer_id or '—')}\n"

        await message.answer(text[:4096])

@dp.message(Command("ord"))
async def admin_list_orders_by_user(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    try:
        _, user_id = message.text.split()
    except ValueError:
        await message.answer("❌ Укажите ID пользователя: /ord 123456789")
        return

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT order_id, product, weight, total, city, status, timestamp FROM orders WHERE user_id = ? ORDER BY timestamp DESC",
            (user_id,)
        ) as cur:
            rows = await cur.fetchall()

        if not rows:
            await message.answer(f"📭 У пользователя <code>{user_id}</code> нет заказов.")
            return

        text = f"<b>Заказы пользователя <code>{safe_html(user_id)}</code>:</b>\n\n"
        for row in rows:
            order_id, product, weight, total, city, status, ts = row
            short_ts = ts.replace("T", " ").split(".")[0][2:16].replace("-", ".")
            status_emoji = "✅" if status == "paid" else ("❌" if status == "cancelled" else "⏳")
            text += (
                f"{status_emoji} ID: <code>{safe_html(order_id)}</code>\n"
                f"Товар: {safe_html(product)} | {weight}г | {total}₽\n"
                f"Город: {safe_html(city)} | {short_ts} | {status}\n"
                f"{'—' * 20}\n"
            )

        await message.answer(text[:4096])

@dp.message(Command("addprod"))
async def admin_addprod(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        _, name, price = message.text.split(maxsplit=2)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("INSERT INTO products (name, price_per_gram) VALUES (?, ?)", (name, float(price)))
            await db.commit()
        await message.answer(f"✅ Товар '{safe_html(name)}' добавлен ({price}₽/г)")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}. Формат: /addprod Название Цена")

@dp.message(Command("delprod"))
async def admin_delprod(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        _, product_id = message.text.split()
        product_id = int(product_id)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("DELETE FROM products WHERE id = ?", (product_id,))
            await db.commit()
        await message.answer(f"✅ Товар ID={product_id} удалён")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}. Формат: /delprod ID")

@dp.message(Command("prod"))
async def admin_list_products(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id, name, price_per_gram FROM products") as cur:
            rows = await cur.fetchall()
    
    if not rows:
        await message.answer("📦 Каталог пуст.")
        return

    text = "<b>Список товаров:</b>\n\n"
    for pid, name, price in rows:
        text += f"ID: <code>{pid}</code> | {safe_html(name)} ({price}₽/г)\n"

    await message.answer(text)

# === LAUNCH ===
async def main():
    await init_db()
    me = await bot.get_me()
    print(f"✅ Бот @{me.username} запущен.")
    print(f"📢 Канал заказов: {CHANNEL_ID}")
    print(f"💸 Канал рефералок: {REF_CHANNEL_ID}")
    print(f"👑 Админ ID: {ADMIN_ID}")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

