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

# === CONFIG ===
CHANNEL_ID = -100 
BOT_TOKEN = "8550339613:AAHO_kfhWKXDbatTNq9ZWQk18NU3PnCMncg"
ADMIN_ID = 7710526060
DB_PATH = os.path.abspath("data.db")

# === INIT BOT ===
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# === DATABASE ===
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                balance REAL DEFAULT 0,
                city TEXT DEFAULT ''
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
            CREATE TABLE IF NOT EXISTS cities (
                name TEXT PRIMARY KEY
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                order_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                product TEXT NOT NULL,
                weight REAL NOT NULL,
                total REAL NOT NULL,
                city TEXT NOT NULL,
                timestamp TEXT NOT NULL
            )
        """)
        await db.commit()

# === UTILS ===
async def ensure_user(user_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
        await db.commit()

async def get_user(user_id: str):
    await ensure_user(user_id)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT balance, city FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            return {"balance": row[0], "city": row[1]}

async def set_user_city(user_id: str, city: str):
    await ensure_user(user_id)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET city = ? WHERE user_id = ?", (city, user_id))
        await db.commit()

async def add_balance(user_id: str, amount: float):
    await ensure_user(user_id)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        await db.commit()

async def deduct_balance(user_id: str, amount: float):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, user_id))
        await db.commit()

async def get_balance(user_id: str) -> float:
    await ensure_user(user_id)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,)) as cur:
            return (await cur.fetchone())[0]

async def get_products():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id, name, price_per_gram FROM products") as cur:
            rows = await cur.fetchall()
            return {str(row[0]): {"name": row[1], "price": row[2]} for row in rows}

async def get_product_by_id(product_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT name, price_per_gram FROM products WHERE id = ?", (int(product_id),)
        ) as cur:
            row = await cur.fetchone()
            return {"name": row[0], "price": row[1]} if row else None

async def add_product(name: str, price: float):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO products (name, price_per_gram) VALUES (?, ?)", (name, price))
        await db.commit()

async def delete_product(product_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM products WHERE id = ?", (product_id,))
        await db.commit()

async def save_order(user_id: str, product: str, weight: float, total: float, city: str):
    order_id = str(uuid.uuid4())[:8].upper()
    timestamp = datetime.now().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO orders (order_id, user_id, product, weight, total, city, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (order_id, user_id, product, weight, total, city, timestamp)
        )
        await db.commit()
    return order_id

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
    await ensure_user(user_id)

    text = "🎉 Добро пожаловать!\nТут ты можешь купить стафф безопасно.\nВся работа проделывается опытными людьми.\nМы гарантируем наход товара при ненаходе — перезаклад!"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 Каталог", callback_data="menu_catalog")],
        [InlineKeyboardButton(text="🛠 Поддержка", callback_data="menu_support")],
        [InlineKeyboardButton(text="⚙️ Настройки", callback_data="menu_settings")]
    ])
    await message.answer(text, reply_markup=kb)

@dp.callback_query(lambda c: c.data == "menu_settings")
async def show_settings(callback: CallbackQuery, state: FSMContext):
    user_id = str(callback.from_user.id)
    username = callback.from_user.username or "не указан"
    user = await get_user(user_id)
    city = user["city"] if user["city"] else "не выбран"
    balance = user["balance"]

    text = (
        f"<b>Профиль</b>\n"
        f"ID: <code>{user_id}</code>\n"
        f"Юзернейм: @{username}\n"
        f"Баланс: {balance}₽\n"
        f"Город: {city}"
    )

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏙 Выбрать город", callback_data="choose_city")],
            [InlineKeyboardButton(text="Пополнить баланс", url="https://t.me/feeddrugbot")],
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
    await message.answer(f"✅ Город сохранён: <b>{city}</b>")
    user = await get_user(user_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏙 Выбрать город", callback_data="choose_city")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")]
    ])
    await message.answer(
        f"<b>Профиль</b>\nБаланс: {user['balance']}₽\nГород: {user['city']}",
        reply_markup=kb
    )
    await state.clear()

@dp.callback_query(lambda c: c.data == "menu_catalog")
async def show_catalog(callback: CallbackQuery, state: FSMContext):
    user = await get_user(str(callback.from_user.id))
    if not user["city"]:
        await callback.answer("❌ Сначала укажите город в настройках!", show_alert=True)
        return

    products = await get_products()
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
    product = await get_product_by_id(product_id)
    if not product:
        await callback.answer("Товар удалён", show_alert=True)
        return

    await state.update_data(product_id=product_id, price=product["price"])
    await callback.message.edit_text(
        f"Товар: <b>{product['name']}</b> ({product['price']}₽/г)\n"
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
    balance = await get_balance(user_id)

    if balance < total:
        await message.answer(f"❌ Недостаточно средств. Нужно {total}₽, у вас {balance}₽.")
        return

    user = await get_user(user_id)
    city = user["city"] or "не указан"
    product = await get_product_by_id(data["product_id"])

    await state.update_data(weight=weight, total=total)
    confirm_data = f"buy:{data['product_id']}:{weight}:{total}"

    await message.answer(
        f"<b>Подтверждение:</b>\n"
        f"Товар: {product['name']}\n"
        f"Вес: {weight}г\n"
        f"Сумма: {total}₽\n"
        f"Город доставки: {city}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Подтвердить", callback_data=confirm_data)],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="menu_catalog")]
        ])
    )
    await state.set_state(BuyFlow.confirming)

@dp.callback_query(lambda c: c.data.startswith("buy:"))
async def execute_purchase(callback: CallbackQuery, state: FSMContext):
    try:
        _, product_id, weight_str, total_str = callback.data.split(":")
        weight = float(weight_str)
        total = float(total_str)
        user_id = str(callback.from_user.id)
    except Exception:
        await callback.answer("❌ Ошибка данных заказа", show_alert=True)
        return

    balance = await get_balance(user_id)
    if balance < total:
        await callback.answer("❌ Недостаточно средств", show_alert=True)
        return

    user = await get_user(user_id)
    city = user["city"] or "—"
    product = await get_product_by_id(product_id)
    if not product:
        await callback.answer("❌ Товар удалён", show_alert=True)
        return

    await deduct_balance(user_id, total)
    order_id = await save_order(user_id, product["name"], weight, total, city)

    # === УВЕДОМЛЕНИЕ В КАНАЛ ===
    try:
        username = f"@{callback.from_user.username}" if callback.from_user.username else "—"
        await bot.send_message(
            CHANNEL_ID,
            f"🆕 <b>Новый заказ!</b>\n\n"
            f"ID заказа: <code>{order_id}</code>\n"
            f"Юзер: <a href='tg://user?id={user_id}'>{callback.from_user.first_name}</a> ({username})\n"
            f"ID: <code>{user_id}</code>\n"
            f"Товар: {product['name']}\n"
            f"Вес: {weight}г | Сумма: {total}₽\n"
            f"Город: {city}"
        )
    except Exception as e:
        print(f"⚠️ Не удалось отправить в канал: {e}")

    # === ОТВЕТ ПОЛЬЗОВАТЕЛЮ ===
    await callback.message.edit_text(
        f"✅ Покупка успешна!\n<b>ID заказа:</b> <code>{order_id}</code>\n"
        f"<b>Напишите поддержке с ID заказа</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💬 Написать в поддержку", url="https://t.me/feeddrugbot")]
        ])
    )
    await state.clear()

@dp.callback_query(lambda c: c.data == "menu_support")
async def support(callback: CallbackQuery):
    await callback.message.edit_text(
        "🛠 Нажмите кнопку ниже, чтобы связаться с поддержкой:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💬 Написать в поддержку", url="https://t.me/feeddrugbot")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")]
        ])
    )

@dp.callback_query(lambda c: c.data == "back_to_main")
async def back_to_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await cmd_start(callback.message, state)

# === ADMIN COMMANDS ===

@dp.message(Command("users"))
async def admin_list_users_with_orders(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    async with aiosqlite.connect(DB_PATH) as db:
        # Получаем уникальных user_id из таблицы orders
        async with db.execute("""
            SELECT DISTINCT user_id FROM orders ORDER BY user_id
        """) as cur:
            rows = await cur.fetchall()

        if not rows:
            await message.answer("📭 Нет пользователей с заказами.")
            return

        text = "<b>Пользователи с заказами:</b>\n\n"
        for (user_id,) in rows:
            try:
                chat = await bot.get_chat(user_id)
                username = f"@{chat.username}" if chat.username else chat.first_name
                name_part = f"{username} ({chat.first_name})"
            except Exception:
                name_part = "Неизвестно"

            # Получаем баланс
            balance = await get_balance(user_id)

            text += f"ID: <code>{user_id}</code> | {name_part} | Баланс: {balance}₽\n"

        # Telegram ограничивает длину сообщения (~4096 символов)
        # Если много юзеров — разбиваем на части
        MAX_LEN = 4000
        if len(text) > MAX_LEN:
            parts = [text[i:i+MAX_LEN] for i in range(0, len(text), MAX_LEN)]
            for part in parts:
                await message.answer(part)
        else:
            await message.answer(text)

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
            "SELECT order_id, product, weight, total, city, timestamp FROM orders WHERE user_id = ? ORDER BY timestamp DESC",
            (user_id,)
        ) as cur:
            rows = await cur.fetchall()

        if not rows:
            await message.answer(f"📭 У пользователя <code>{user_id}</code> нет заказов.")
            return

        text = f"<b>Заказы пользователя <code>{user_id}</code>:</b>\n\n"
        for row in rows:
            order_id, product, weight, total, city, ts = row
            # Обрезаем timestamp до читаемого вида: 2026-01-24T15:30:45 → 24.01.26 15:30
            short_ts = ts.replace("T", " ").split(".")[0][2:16].replace("-", ".")
            text += (
                f"ID: <code>{order_id}</code>\n"
                f"Товар: {product}\n"
                f"Вес: {weight}г | Сумма: {total}₽\n"
                f"Город: {city}\n"
                f"Время: {short_ts}\n"
                f"{'—' * 20}\n"
            )

        # Разбиваем, если слишком длинно
        MAX_LEN = 4000
        if len(text) > MAX_LEN:
            parts = [text[i:i+MAX_LEN] for i in range(0, len(text), MAX_LEN)]
            for part in parts:
                await message.answer(part)
        else:
            await message.answer(text)
            
@dp.message(Command("bal"))
async def admin_bal(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        _, user_id, amount = message.text.split()
        await add_balance(user_id, float(amount))
        await message.answer(f"✅ Баланс {user_id} пополнен на {amount}₽")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}. Формат: /bal user_id сумма")

@dp.message(Command("addprod"))
async def admin_addprod(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        _, name, price = message.text.split(maxsplit=2)
        await add_product(name, float(price))
        await message.answer(f"✅ Товар '{name}' добавлен ({price}₽/г)")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}. Формат: /addprod Название Цена")

@dp.message(Command("delprod"))
async def admin_delprod(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        _, product_id = message.text.split()
        product_id = int(product_id)
        # Проверим, существует ли
        product = await get_product_by_id(str(product_id))
        if not product:
            await message.answer("❌ Товар с таким ID не найден")
            return
        await delete_product(product_id)
        await message.answer(f"✅ Товар '{product['name']}' (ID={product_id}) удалён")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}. Формат: /delprod ID")
        
        
@dp.message(Command("prod"))
async def admin_list_products(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    products = await get_products()
    if not products:
        await message.answer("📦 Каталог пуст.")
        return

    text = "<b>Список товаров:</b>\n\n"
    for p_id, p in products.items():
        text += f"ID: <code>{p_id}</code> | {p['name']} ({p['price']}₽/г)\n"

    await message.answer(text)
    
@dp.message(Command("order"))
async def admin_get_order(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        _, order_id = message.text.split()
    except ValueError:
        await message.answer("❌ Укажите ID заказа: /order ABC123")
        return

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT user_id, product, weight, total, city, timestamp FROM orders WHERE order_id = ?",
            (order_id,)
        ) as cur:
            row = await cur.fetchone()
            if not row:
                await message.answer("❌ Заказ не найден")
                return

            user_id, product, weight, total, city, ts = row
            try:
                chat = await bot.get_chat(user_id)
                username = f"@{chat.username}" if chat.username else chat.first_name
            except:
                username = "Неизвестно"

            await message.answer(
                f"<b>Заказ {order_id}</b>\n"
                f"Юзер: <code>{user_id}</code> ({username})\n"
                f"Товар: {product}\n"
                f"Вес: {weight}г\n"
                f"Сумма: {total}₽\n"
                f"Город: {city}\n"
                f"Время: {ts}"
            )

# === LAUNCH ===
async def main():
    await init_db()
    print("✅ Бот запущен. База данных инициализирована.")
    await dp.start_polling(bot)

if __name__ == "__main__":

    asyncio.run(main())

