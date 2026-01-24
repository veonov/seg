import asyncio
import aiosqlite
import uuid
from datetime import datetime
from urllib.parse import quote
from aiogram import Bot, Dispatcher
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

# === CONFIG ===
BOT_TOKEN = "8550339613:AAHO_kfhWKXDbatTNq9ZWQk18NU3PnCMncg"
ADMIN_ID = 7710526060  # Замени на свой Telegram ID
DB_PATH = "data.db"

# === INIT BOT ===
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
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

async def get_cities():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT name FROM cities") as cur:
            return [row[0] async for row in cur]

async def add_city(name: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO cities (name) VALUES (?)", (name,))
        await db.commit()
        
async def save_order(user_id: str, product: str, weight: float, total: float, city: str):
    order_id = str(uuid.uuid4())[:8].upper()
    timestamp = datetime.now().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
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

    # Проверяем, существует ли уже запись
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,)) as cur:
            already_exists = await cur.fetchone() is not None

    # ВСЕГДА создаём запись, если её нет (гарантируем наличие в БД)
    await ensure_user(user_id)

    if already_exists:
        text = "👋 С возвращением! Рады видеть вас "
    else:
        text = "🎉Добро пожаловать!\nТут ты можешь купить стафф безопасно \nВся работа проделываеться опытными людьми \nМы гарантируем наход товара при ненаходе перезаклад!"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 Каталог", callback_data="menu_catalog")],
        [InlineKeyboardButton(text="🛠 Поддержка", callback_data="menu_support")],
        [InlineKeyboardButton(text="⚙️ Настройки", callback_data="menu_settings")]
    ])
    await message.answer(text, reply_markup=kb)


@dp.callback_query(lambda c: c.data == "menu_settings")
async def show_settings(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    username = callback.from_user.username or "не указан"
    user = await get_user(str(user_id))
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
            [InlineKeyboardButton(text="Пополнить баланс ", url="https://t.me/feeddrugbot")],
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

    # Показываем профиль (как после /start)
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
        [InlineKeyboardButton(text=p["name"], callback_data=f"prod_{p_id}")]
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
    weights = ["0.5", "1", "2", "3", "4"]
    buttons = [
        [InlineKeyboardButton(text=f"{w}г", callback_data=f"weight_{w}") for w in weights[i:i+2]]
        for i in range(0, len(weights), 2)
    ]
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_catalog")])
    await callback.message.edit_text(
        f"Товар: <b>{product['name']}</b>\nВыберите вес:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await state.set_state(BuyFlow.choosing_amount)

@dp.callback_query(lambda c: c.data.startswith("weight_"))
async def confirm_purchase(callback: CallbackQuery, state: FSMContext):
    weight = float(callback.data[7:])
    user_id = str(callback.from_user.id)
    data = await state.get_data()

    # Проверка, что всё необходимое есть
    if "product_id" not in data or "price" not in data:
        await callback.answer("❌ Сессия устарела. Начните заново.", show_alert=True)
        await state.clear()
        await cmd_start(callback.message, state)
        return

    total = round(weight * data["price"], 2)
    balance = await get_balance(user_id)

    if balance < total:
        await callback.answer("❌ Недостаточно средств!\nПополните баланс у @feeddrugbot", show_alert=True)
        return

    user = await get_user(user_id)
    city = user["city"] or "не указан"

    # Получаем название товара по ID для отображения
    product = await get_product_by_id(data["product_id"])
    if not product:
        await callback.answer("❌ Товар удалён", show_alert=True)
        return

    # Формируем короткий callback: buy:<product_id>:<weight>:<total>
    confirm_data = f"buy:{data['product_id']}:{weight}:{total}"

    await callback.message.edit_text(
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
        await callback.answer("❌ Недостаточно средств!\nПополните баланс у @feeddrugbot", show_alert=True)
        return

    user = await get_user(user_id)
    city = user["city"] or "—"

    product = await get_product_by_id(product_id)
    if not product:
        await callback.answer("❌ Товар удалён", show_alert=True)
        return

    await deduct_balance(user_id, total)
    order_id = await save_order(user_id, product["name"], weight, total, city)

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

            # Получаем username или имя из Telegram (опционально)
            try:
                user = await bot.get_chat(user_id)
                username = f"@{user.username}" if user.username else f"{user.first_name}"
            except Exception:
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

