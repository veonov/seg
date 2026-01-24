from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message, InlineKeyboardButton, InlineKeyboardMarkup,
    CallbackQuery, ReplyKeyboardRemove
)
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramForbiddenError

BOT_TOKEN = "8047216622:AAEKEEvzl1CqhhXMmyujNF_agaq04kHJkI8"
ADMIN_ID = 7710526060 # замени на свой ID

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Состояния
class Feedback(StatesGroup):
    waiting_for_message = State()
    replying = State()


user_feedbacks = {}

@dp.message(Command("start"))
async def start(msg: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Написать в поддержку", callback_data="support")]
    ])
    await msg.answer("Выберите действие:", reply_markup=kb)

@dp.callback_query(F.data == "support")
async def support_callback(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await call.message.answer("Напишите ваше обращение:")
    await state.set_state(Feedback.waiting_for_message)

@dp.message(Feedback.waiting_for_message)
async def get_feedback(msg: Message, state: FSMContext):
    user_id = msg.from_user.id
    username = msg.from_user.username or f"user{user_id}"
    text = msg.text

    # Сохраняем ID пользователя для ответа
    user_feedbacks[ADMIN_ID] = user_id

    # Кнопка "Ответить" для админа
    reply_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Ответить", callback_data=f"reply:{user_id}")]
    ])

    try:
        await bot.send_message(
            ADMIN_ID,
            f"Сообщение от @{username} ({user_id}):\n\n{text}",
            reply_markup=reply_kb
        )
        await msg.answer("Ваше обращение отправлено!")
    except Exception:
        await msg.answer("Не удалось отправить обращение. Попробуйте позже.")

    await state.clear()

# Обработка кнопки "Ответить"
@dp.callback_query(F.data.startswith("reply:"))
async def reply_to_user(call: CallbackQuery, state: FSMContext):
    user_id = int(call.data.split(":")[1])
    await state.update_data(reply_to=user_id)
    await call.message.answer("Введите ответ (он не будет отображаться здесь):")
    await state.set_state(Feedback.replying)
    await call.answer()

# Отправка ответа пользователю
@dp.message(Feedback.replying)
async def send_reply(msg: Message, state: FSMContext):
    data = await state.get_data()
    user_id = data.get("reply_to")

    if not user_id:
        await msg.answer("Ошибка: неизвестный получатель.")
        return

    try:
        await bot.send_message(user_id, f"Ответ от поддержки:\n\n{msg.text}")
        await msg.answer("✅ Ответ отправлен.", reply_markup=ReplyKeyboardRemove())
    except TelegramForbiddenError:
        await msg.answer("❌ Не могу отправить: пользователь заблокировал бота.")
    except Exception as e:
        await msg.answer(f"❌ Ошибка при отправке: {str(e)}")

    await state.clear()

if __name__ == "__main__":
    dp.run_polling(bot)