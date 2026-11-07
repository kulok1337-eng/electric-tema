"""Прямые заявки от клиентов: без регистрации и без одобрения администратором."""
import logging
import re
from contextlib import suppress

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
import config
from database.requests import add_order, get_user
from handlers.admin import master_menu
from handlers.admin_panel import admin_menu
from handlers.order_notify import send_order_to_admins

router = Router()

BTN_CANCEL = "Отменить заявку"
BTN_SKIP_PHOTO = "Пропустить фото"
BTN_SEND = "Отправить заявку"
BTN_NEW = "Оставить заявку"

TOTAL_STEPS = 6

# Текст (не команда): команды вроде /start не должны попадать в поля анкеты
PLAIN_TEXT = F.text & ~F.text.startswith("/")


class ClientOrderStates(StatesGroup):
    name = State()
    phone = State()
    address = State()
    description = State()
    desired_time = State()
    photo = State()
    confirm = State()


def _kb(*rows: list[KeyboardButton]) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=list(rows), resize_keyboard=True)


def cancel_kb() -> ReplyKeyboardMarkup:
    return _kb([KeyboardButton(text=BTN_CANCEL)])


def phone_kb() -> ReplyKeyboardMarkup:
    return _kb([KeyboardButton(text="Поделиться номером", request_contact=True)], [KeyboardButton(text=BTN_CANCEL)])


def photo_kb() -> ReplyKeyboardMarkup:
    return _kb([KeyboardButton(text=BTN_SKIP_PHOTO)], [KeyboardButton(text=BTN_CANCEL)])


def confirm_kb() -> ReplyKeyboardMarkup:
    return _kb([KeyboardButton(text=BTN_SEND)], [KeyboardButton(text=BTN_CANCEL)])


def client_menu() -> ReplyKeyboardMarkup:
    return _kb([KeyboardButton(text=BTN_NEW)])


async def menu_for(user_id: int):
    """Какое меню вернуть после завершения/отмены заявки."""
    if user_id in config.ADMIN_IDS:
        return admin_menu()
    user = await get_user(user_id)
    if user and user.is_approved:
        return master_menu()
    if user:  # мастер на модерации — своё меню у него ещё не появилось
        return ReplyKeyboardRemove()
    return client_menu()


# ---------- вход в сценарий ----------

async def begin_client_flow(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(ClientOrderStates.name)
    await message.answer(
        "Оставьте заявку — мы свяжемся с вами. Это займёт около минуты.\n"
        "Отменить заполнение можно в любой момент: кнопка «Отменить заявку» или команда /cancel.\n\n"
        f"Шаг 1 из {TOTAL_STEPS}: как к вам обращаться?",
        reply_markup=cancel_kb(),
    )


@router.callback_query(F.data == "start_client")
async def choose_client(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    with suppress(TelegramBadRequest):
        await callback.message.edit_reply_markup(reply_markup=None)
    await begin_client_flow(callback.message, state)


@router.message(Command("client"))
@router.message(F.text == BTN_NEW)
async def start_client_command(message: Message, state: FSMContext):
    await begin_client_flow(message, state)


# ---------- отмена (работает на любом шаге) ----------

@router.message(StateFilter(ClientOrderStates), Command("cancel"))
@router.message(StateFilter(ClientOrderStates), F.text == BTN_CANCEL)
async def cancel_client_flow(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Заполнение заявки отменено, данные не сохранены. Чтобы начать заново, нажмите «Оставить заявку» или /client.",
        reply_markup=await menu_for(message.from_user.id),
    )


# ---------- шаги ----------

@router.message(ClientOrderStates.name, PLAIN_TEXT)
async def step_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if not 2 <= len(name) <= 100:
        await message.answer("Введите имя — от 2 до 100 символов.")
        return
    await state.update_data(name=name)
    await state.set_state(ClientOrderStates.phone)
    await message.answer(
        f"Шаг 2 из {TOTAL_STEPS}: номер телефона для связи. Нажмите кнопку «Поделиться номером» или введите вручную:",
        reply_markup=phone_kb(),
    )


@router.message(ClientOrderStates.phone, F.contact)
async def step_phone_contact(message: Message, state: FSMContext):
    phone = message.contact.phone_number.strip()
    if not phone.startswith("+"):
        phone = "+" + phone
    await _save_phone(message, state, phone)


@router.message(ClientOrderStates.phone, PLAIN_TEXT)
async def step_phone_text(message: Message, state: FSMContext):
    phone = message.text.strip()
    digits = re.sub(r"\D", "", phone)
    if not 10 <= len(digits) <= 15 or len(phone) > 32:
        await message.answer("Не похоже на номер телефона. Введите в формате +7 900 123-45-67 или нажмите «Поделиться номером».")
        return
    await _save_phone(message, state, phone)


async def _save_phone(message: Message, state: FSMContext, phone: str):
    await state.update_data(phone=phone)
    await state.set_state(ClientOrderStates.address)
    await message.answer(f"Шаг 3 из {TOTAL_STEPS}: адрес объекта (город, улица, дом, квартира):", reply_markup=cancel_kb())


@router.message(ClientOrderStates.address, PLAIN_TEXT)
async def step_address(message: Message, state: FSMContext):
    address = message.text.strip()
    if not 5 <= len(address) <= 255:
        await message.answer("Укажите адрес подробнее — от 5 до 255 символов.")
        return
    await state.update_data(address=address)
    await state.set_state(ClientOrderStates.description)
    await message.answer(f"Шаг 4 из {TOTAL_STEPS}: опишите, какие работы нужно выполнить:", reply_markup=cancel_kb())


@router.message(ClientOrderStates.description, PLAIN_TEXT)
async def step_description(message: Message, state: FSMContext):
    description = message.text.strip()
    if not 5 <= len(description) <= 1000:
        await message.answer("Опишите задачу подробнее — от 5 до 1000 символов.")
        return
    await state.update_data(description=description)
    await state.set_state(ClientOrderStates.desired_time)
    await message.answer(f"Шаг 5 из {TOTAL_STEPS}: когда вам удобно, чтобы мастер приехал? Укажите дату и время:", reply_markup=cancel_kb())


@router.message(ClientOrderStates.desired_time, PLAIN_TEXT)
async def step_time(message: Message, state: FSMContext):
    desired_time = message.text.strip()
    if not 2 <= len(desired_time) <= 128:
        await message.answer("Укажите удобное время — до 128 символов (например: завтра после 18:00).")
        return
    await state.update_data(desired_time=desired_time)
    await state.set_state(ClientOrderStates.photo)
    await message.answer(
        f"Шаг 6 из {TOTAL_STEPS}: прикрепите одно фото объекта (по желанию) или нажмите «Пропустить фото»:",
        reply_markup=photo_kb(),
    )


@router.message(ClientOrderStates.photo, F.photo)
async def step_photo(message: Message, state: FSMContext):
    await state.update_data(photo_id=message.photo[-1].file_id)
    await show_confirmation(message, state)


@router.message(ClientOrderStates.photo, F.text == BTN_SKIP_PHOTO)
async def step_skip_photo(message: Message, state: FSMContext):
    await state.update_data(photo_id=None)
    await show_confirmation(message, state)


async def show_confirmation(message: Message, state: FSMContext):
    data = await state.get_data()
    summary = (
        "Проверьте заявку:\n\n"
        f"Имя: {data['name']}\n"
        f"Телефон: {data['phone']}\n"
        f"Адрес: {data['address']}\n"
        f"Работы: {data['description']}\n"
        f"Удобное время: {data['desired_time']}\n"
        f"Фото: {'прикреплено' if data.get('photo_id') else 'нет'}"
    )
    await state.set_state(ClientOrderStates.confirm)
    await message.answer(summary, reply_markup=confirm_kb())


@router.message(ClientOrderStates.confirm, F.text == BTN_SEND)
async def send_client_order(message: Message, state: FSMContext):
    data = await state.get_data()
    await state.clear()  # сразу сбрасываем состояние: повторное нажатие не создаст дубль

    required = ("name", "phone", "address", "description", "desired_time")
    if not all(data.get(k) for k in required):
        await message.answer("Данные заявки потерялись. Пожалуйста, заполните её заново: /client", reply_markup=client_menu())
        return

    try:
        order = await add_order(
            master_id=config.CLIENT_MASTER_ID,
            client_phone=data["phone"],
            address=data["address"],
            description=data["description"],
            desired_date=data["desired_time"],
            photo_id=data.get("photo_id"),
            source=config.SOURCE_CLIENT,
            client_tg_id=message.from_user.id,
            client_name=data["name"],
            client_username=message.from_user.username,
        )
    except Exception:
        logging.exception("Не удалось сохранить клиентскую заявку от %s", message.from_user.id)
        await message.answer(
            "Не удалось сохранить заявку. Попробуйте ещё раз чуть позже: /client",
            reply_markup=await menu_for(message.from_user.id),
        )
        return

    await message.answer(
        f"Спасибо! Заявка #{order.id} отправлена. Мы свяжемся с вами по номеру {order.client_phone}.",
        reply_markup=await menu_for(message.from_user.id),
    )
    await send_order_to_admins(message.bot, order)


# ---------- запасные обработчики: неподходящий ввод на шагах ----------

@router.message(ClientOrderStates.confirm)
async def confirm_fallback(message: Message):
    await message.answer(f"Нажмите «{BTN_SEND}» или «{BTN_CANCEL}».")


@router.message(ClientOrderStates.photo)
async def photo_fallback(message: Message):
    await message.answer(f"Отправьте фото (одно) или нажмите «{BTN_SKIP_PHOTO}». Отмена — «{BTN_CANCEL}».")


@router.message(ClientOrderStates.phone)
async def phone_fallback(message: Message):
    await message.answer("Введите номер телефона текстом или нажмите «Поделиться номером».")


@router.message(StateFilter(ClientOrderStates))
async def text_fallback(message: Message):
    await message.answer(f"Пожалуйста, ответьте на вопрос текстом. Отмена — «{BTN_CANCEL}».")


# ---------- кнопки без активного сценария (например, после перезапуска бота состояние теряется) ----------

@router.message(F.text.in_({BTN_CANCEL, BTN_SEND, BTN_SKIP_PHOTO}))
async def stale_buttons(message: Message):
    await message.answer(
        "Эта заявка уже не активна (возможно, бот перезапускался). Чтобы заполнить заново, нажмите «Оставить заявку» или /client.",
        reply_markup=await menu_for(message.from_user.id),
    )
