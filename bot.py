"""
Telegram-бот для записи клиентов в барбершоп.

Как устроен диалог (это называется «машина состояний», FSM):
  выбор услуги -> выбор даты -> выбор времени -> имя -> телефон -> подтверждение

Запуск:  python bot.py
"""

import asyncio
import html
import logging
from datetime import date, datetime

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
import db
from schedule import available_dates, format_date, free_slots, normalize_phone

router = Router()

# Тексты кнопок главного меню (используются и для создания кнопок, и для их обработки)
BTN_BOOK = "✂️ Записаться"
BTN_MY = "📋 Мои записи"
BTN_ABOUT = "ℹ️ О нас"
MENU_BUTTONS = {BTN_BOOK, BTN_MY, BTN_ABOUT}


# ---------- Состояния диалога записи ----------

class Booking(StatesGroup):
    service = State()
    date = State()
    time = State()
    name = State()
    phone = State()
    confirm = State()


# ---------- Клавиатуры ----------

def main_menu() -> ReplyKeyboardMarkup:
    """Постоянное меню внизу экрана."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_BOOK)],
            [KeyboardButton(text=BTN_MY), KeyboardButton(text=BTN_ABOUT)],
        ],
        resize_keyboard=True,
    )


def phone_keyboard() -> ReplyKeyboardMarkup:
    """Кнопка «Отправить номер» — Telegram сам подставит номер клиента."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Отправить мой номер", request_contact=True)],
            [KeyboardButton(text="❌ Отмена")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def services_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for code, (title, price, _minutes) in config.SERVICES.items():
        kb.button(text=f"{title} — {price} ₽", callback_data=f"svc:{code}")
    kb.button(text="❌ Отмена", callback_data="cancel")
    kb.adjust(1)  # по одной кнопке в ряд
    return kb.as_markup()


def dates_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for d in available_dates(date.today(), config.DAYS_AHEAD, config.DAYS_OFF):
        kb.button(text=format_date(d), callback_data=f"date:{d.isoformat()}")
    kb.adjust(2)
    kb.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data="back:service"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="cancel"),
    )
    return kb.as_markup()


def times_keyboard(slots: list[str]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for slot in slots:
        kb.button(text=slot, callback_data=f"time:{slot}")
    kb.adjust(4)
    kb.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data="back:date"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="cancel"),
    )
    return kb.as_markup()


def confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data="confirm")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")],
    ])


# ---------- Вспомогательные функции ----------

def booking_text(service_code: str, day: str, time: str,
                 name: str | None = None, phone: str | None = None,
                 price: int | None = None) -> str:
    title, current_price, _ = config.SERVICES[service_code]
    # Цена из записи в базе; если её нет (новая или старая запись) — текущая из config.py
    if price is None:
        price = current_price
    lines = [
        f"<b>Услуга:</b> {title} — {price} ₽",
        f"<b>Дата:</b> {format_date(date.fromisoformat(day))}",
        f"<b>Время:</b> {time}",
    ]
    # html.escape защищает от «сломанного» текста, если клиент введёт символы < или >
    if name:
        lines.append(f"<b>Имя:</b> {html.escape(name)}")
    if phone:
        lines.append(f"<b>Телефон:</b> {html.escape(phone)}")
    return "\n".join(lines)


async def show_services(message: Message, state: FSMContext) -> None:
    await state.set_state(Booking.service)
    await message.answer("Выберите услугу:", reply_markup=services_keyboard())


# ---------- Общие команды ----------

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        f"Здравствуйте, {html.escape(message.from_user.first_name)}! 👋\n"
        f"Это бот <b>{config.SHOP_NAME}</b>.\n\n"
        "Здесь можно записаться на стрижку за минуту, без звонков.",
        reply_markup=main_menu(),
    )


@router.message(Command("myid"))
async def cmd_myid(message: Message) -> None:
    """Помогает владельцу узнать свой ID, чтобы вписать его в .env как ADMIN_ID."""
    await message.answer(f"Ваш Telegram ID: <code>{message.from_user.id}</code>")


@router.message(F.text == BTN_ABOUT)
async def about(message: Message) -> None:
    prices = "\n".join(f"• {t} — {p} ₽" for t, p, _ in config.SERVICES.values())
    await message.answer(
        f"<b>{config.SHOP_NAME}</b>\n"
        f"📍 {config.SHOP_ADDRESS}\n"
        f"📞 {config.SHOP_PHONE}\n"
        f"🕙 Ежедневно с {config.WORK_START_HOUR}:00 до {config.WORK_END_HOUR + 1}:00\n\n"
        f"<b>Услуги и цены:</b>\n{prices}"
    )


# ---------- Отмена (работает на любом шаге) ----------

@router.callback_query(F.data == "cancel")
async def cancel_inline(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("Запись отменена. Возвращайтесь, когда будет удобно 🙂")
    await callback.answer()


@router.message(F.text == "❌ Отмена")
async def cancel_text(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Запись отменена.", reply_markup=main_menu())


# ---------- Шаг 1: услуга ----------

@router.message(F.text == BTN_BOOK)
async def start_booking(message: Message, state: FSMContext) -> None:
    await state.clear()
    await show_services(message, state)


@router.callback_query(Booking.service, F.data.startswith("svc:"))
async def choose_service(callback: CallbackQuery, state: FSMContext) -> None:
    code = callback.data.split(":", 1)[1]
    if code not in config.SERVICES:
        await callback.answer("Такой услуги нет", show_alert=True)
        return
    await state.update_data(service=code)
    await state.set_state(Booking.date)
    await callback.message.edit_text("Выберите дату:", reply_markup=dates_keyboard())
    await callback.answer()


# ---------- Шаг 2: дата ----------

@router.callback_query(Booking.date, F.data.startswith("date:"))
async def choose_date(callback: CallbackQuery, state: FSMContext) -> None:
    day = callback.data.split(":", 1)[1]
    booked = db.get_booked_times(config.DB_PATH, day)
    slots = free_slots(date.fromisoformat(day), datetime.now(), booked,
                       config.WORK_START_HOUR, config.WORK_END_HOUR)
    if not slots:
        await callback.answer("На этот день свободного времени нет. Выберите другой.",
                              show_alert=True)
        return
    await state.update_data(date=day)
    await state.set_state(Booking.time)
    await callback.message.edit_text(
        f"{format_date(date.fromisoformat(day))}. Выберите время:",
        reply_markup=times_keyboard(slots),
    )
    await callback.answer()


# ---------- Шаг 3: время ----------

@router.callback_query(Booking.time, F.data.startswith("time:"))
async def choose_time(callback: CallbackQuery, state: FSMContext) -> None:
    time = callback.data.split(":", 1)[1]   # "time:14:00" -> "14:00"
    data = await state.get_data()
    # Проверяем ещё раз: вдруг, пока клиент думал, время занял кто-то другой
    if time in db.get_booked_times(config.DB_PATH, data["date"]):
        await callback.answer("Это время только что заняли. Выберите другое.", show_alert=True)
        return
    await state.update_data(time=time)
    await state.set_state(Booking.name)
    await callback.message.edit_text(booking_text(data["service"], data["date"], time))
    await callback.message.answer("Как вас зовут?")
    await callback.answer()


# ---------- Кнопки «Назад» ----------

@router.callback_query(F.data == "back:service")
async def back_to_service(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Booking.service)
    await callback.message.edit_text("Выберите услугу:", reply_markup=services_keyboard())
    await callback.answer()


@router.callback_query(F.data == "back:date")
async def back_to_date(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Booking.date)
    await callback.message.edit_text("Выберите дату:", reply_markup=dates_keyboard())
    await callback.answer()


# ---------- Шаг 4: имя ----------

# ~F.text.in_(MENU_BUTTONS): если клиент нажал кнопку меню, это не имя
@router.message(Booking.name, F.text, ~F.text.in_(MENU_BUTTONS))
async def enter_name(message: Message, state: FSMContext) -> None:
    name = message.text.strip()
    if not (2 <= len(name) <= 50):
        await message.answer("Пожалуйста, введите имя (от 2 до 50 символов).")
        return
    await state.update_data(name=name)
    await state.set_state(Booking.phone)
    await message.answer(
        "Оставьте номер телефона: нажмите кнопку ниже или напишите его.",
        reply_markup=phone_keyboard(),
    )


# ---------- Шаг 5: телефон ----------

@router.message(Booking.phone, F.contact)
async def enter_phone_contact(message: Message, state: FSMContext) -> None:
    phone = normalize_phone(message.contact.phone_number) or message.contact.phone_number
    await ask_confirm(message, state, phone)


@router.message(Booking.phone, F.text, ~F.text.in_(MENU_BUTTONS))
async def enter_phone_text(message: Message, state: FSMContext) -> None:
    phone = normalize_phone(message.text)
    if phone is None:
        await message.answer("Не похоже на номер телефона. Пример: +7 900 123-45-67")
        return
    await ask_confirm(message, state, phone)


async def ask_confirm(message: Message, state: FSMContext, phone: str) -> None:
    await state.update_data(phone=phone)
    await state.set_state(Booking.confirm)
    data = await state.get_data()
    # Убираем клавиатуру с телефоном и возвращаем главное меню
    await message.answer("Проверьте данные:", reply_markup=main_menu())
    await message.answer(
        booking_text(data["service"], data["date"], data["time"], data["name"], phone),
        reply_markup=confirm_keyboard(),
    )


# ---------- Шаг 6: подтверждение ----------

@router.callback_query(Booking.confirm, F.data == "confirm")
async def confirm_booking(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    price = config.SERVICES[data["service"]][1]  # фиксируем цену в момент записи
    booking_id = db.add_booking(
        config.DB_PATH, callback.from_user.id, data["name"], data["phone"],
        data["service"], price, data["date"], data["time"],
    )
    if booking_id is None:
        await state.set_state(Booking.date)
        await callback.message.edit_text(
            "Увы, это время только что заняли 😔 Выберите другую дату или время:",
            reply_markup=dates_keyboard(),
        )
        await callback.answer()
        return

    await state.clear()
    details = booking_text(data["service"], data["date"], data["time"],
                           data["name"], data["phone"], price)
    await callback.message.edit_text(
        f"✅ <b>Вы записаны!</b> Номер записи: {booking_id}\n\n{details}\n\n"
        f"📍 {config.SHOP_ADDRESS}\nЖдём вас!"
    )
    await callback.answer("Готово!")

    # Уведомляем владельца
    if config.ADMIN_ID:
        try:
            await bot.send_message(config.ADMIN_ID, f"🔔 <b>Новая запись №{booking_id}</b>\n\n{details}")
        except Exception as e:  # например, владелец ещё не нажал /start в боте
            logging.warning("Не удалось уведомить владельца: %s", e)


# ---------- Мои записи (для клиента) ----------

@router.message(F.text == BTN_MY)
async def my_bookings(message: Message) -> None:
    rows = db.get_user_bookings(config.DB_PATH, message.from_user.id, date.today().isoformat())
    if not rows:
        await message.answer("У вас пока нет записей.", reply_markup=main_menu())
        return
    for row in rows:
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🗑 Отменить запись", callback_data=f"del:{row['id']}")
        ]])
        await message.answer(
            f"Запись №{row['id']}\n" + booking_text(row["service"], row["date"], row["time"],
                                                    price=row["price"]),
            reply_markup=kb,
        )


@router.callback_query(F.data.startswith("del:"))
async def delete_booking(callback: CallbackQuery, bot: Bot) -> None:
    booking_id = int(callback.data.split(":", 1)[1])
    row = db.get_booking(config.DB_PATH, booking_id)
    is_admin = callback.from_user.id == config.ADMIN_ID
    owner_id = None if is_admin else callback.from_user.id
    if row and db.cancel_booking(config.DB_PATH, booking_id, owner_id):
        await callback.message.edit_text(f"Запись №{booking_id} отменена.")
        await callback.answer()
        if config.ADMIN_ID and not is_admin:
            try:
                await bot.send_message(
                    config.ADMIN_ID,
                    f"❌ Клиент отменил запись №{booking_id}\n\n"
                    + booking_text(row["service"], row["date"], row["time"],
                                   row["name"], row["phone"], row["price"]),
                )
            except Exception as e:
                logging.warning("Не удалось уведомить владельца: %s", e)
    else:
        await callback.answer("Запись не найдена или уже отменена.", show_alert=True)


# ---------- Панель владельца ----------

@router.message(Command("admin"))
async def admin_panel(message: Message) -> None:
    if message.from_user.id != config.ADMIN_ID:
        await message.answer("Эта команда только для владельца.")
        return
    rows = db.get_all_bookings(config.DB_PATH, date.today().isoformat())
    if not rows:
        await message.answer("Предстоящих записей нет.")
        return
    await message.answer(f"<b>Предстоящие записи: {len(rows)}</b>")
    for row in rows:
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🗑 Отменить", callback_data=f"del:{row['id']}")
        ]])
        await message.answer(
            f"№{row['id']}\n" + booking_text(row["service"], row["date"], row["time"],
                                             row["name"], row["phone"], row["price"]),
            reply_markup=kb,
        )


# ---------- Если клиент пишет что-то непонятное ----------

@router.message()
async def fallback(message: Message, state: FSMContext) -> None:
    current = await state.get_state()
    if current in (Booking.service.state, Booking.date.state, Booking.time.state,
                   Booking.confirm.state):
        await message.answer("Пожалуйста, выберите вариант кнопкой выше 👆")
    else:
        await message.answer("Выберите действие в меню ниже 👇", reply_markup=main_menu())


# ---------- Запуск ----------

async def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    if not config.BOT_TOKEN:
        raise SystemExit("Не найден BOT_TOKEN. Создайте файл .env по образцу .env.example")

    db.init_db(config.DB_PATH)
    bot = Bot(config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)
    logging.info("Бот запущен. Остановить: Ctrl+C")
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот остановлен.")
