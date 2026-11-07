from contextlib import suppress

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, Message, ReplyKeyboardMarkup, ReplyKeyboardRemove
import config
from database.requests import create_user, get_user
from handlers.admin_panel import admin_menu

router = Router()


def role_choice_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Я клиент — оставить заявку", callback_data="start_client")],
            [InlineKeyboardButton(text="Я мастер", callback_data="start_master")],
        ]
    )


class RegStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_phone = State()
    waiting_for_specialty = State()


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    user = await get_user(message.from_user.id)

    if message.from_user.id in config.ADMIN_IDS:
        if not user:
            role_title = "Артём (Диспетчер)" if message.from_user.id == config.ARTEM_ID else "Разработчик / Админ"
            await create_user(
                telegram_id=message.from_user.id,
                full_name=message.from_user.full_name or "Admin",
                phone="Admin",
                specialty=role_title,
                role="admin",
                is_approved=True,
            )
        await message.answer("Добро пожаловать в панель управления администратора!", reply_markup=admin_menu())
        return

    await state.clear()  # /start всегда сбрасывает незавершённый сценарий

    if user:
        if not user.is_approved:
            await message.answer("Ваша анкета находится на модерации у администратора. Ожидайте подтверждения.")
            return

        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="Передать заказ")],
                [KeyboardButton(text="Мой профиль")],
            ],
            resize_keyboard=True,
        )
        await message.answer("Главное меню мастера:", reply_markup=kb)
        return

    await message.answer("Здравствуйте! Выберите, кто вы:", reply_markup=role_choice_kb())


@router.callback_query(F.data == "start_master")
async def choose_master(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if await get_user(callback.from_user.id):
        await callback.message.answer("Вы уже есть в системе. Нажмите /start, чтобы открыть меню.")
        return
    with suppress(TelegramBadRequest):
        await callback.message.edit_reply_markup(reply_markup=None)
    await state.clear()
    await state.set_state(RegStates.waiting_for_name)
    await callback.message.answer("Это сервис обмена заказами для мастеров.\n\nВведите ваше имя:")


@router.message(RegStates.waiting_for_name)
async def reg_name(message: Message, state: FSMContext):
    await state.update_data(full_name=message.text.strip())
    await state.set_state(RegStates.waiting_for_phone)

    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Поделиться контактом", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await message.answer("Отправьте ваш номер телефона кнопкой ниже или напишите вручную:", reply_markup=kb)


@router.message(RegStates.waiting_for_phone)
async def reg_phone(message: Message, state: FSMContext):
    phone = message.contact.phone_number if message.contact else message.text.strip()
    await state.update_data(phone=phone)
    await state.set_state(RegStates.waiting_for_specialty)
    await message.answer("Укажите вашу специализацию (например: Электрик, Сантехник, Отделочник):", reply_markup=ReplyKeyboardRemove())


@router.message(RegStates.waiting_for_specialty)
async def reg_specialty(message: Message, state: FSMContext):
    data = await state.get_data()
    specialty = message.text.strip()

    await create_user(
        telegram_id=message.from_user.id,
        full_name=data["full_name"],
        phone=data["phone"],
        specialty=specialty,
        role="master",
        is_approved=False,
    )
    await state.clear()

    await message.answer("Анкета отправлена на проверку. Мы уведомим вас о решении.")

    approve_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Одобрить", callback_data=f"adm_appr_{message.from_user.id}"),
                InlineKeyboardButton(text="Отклонить", callback_data=f"adm_decl_{message.from_user.id}"),
            ]
        ]
    )
    admin_notify = (
        f"Новая регистрация мастера!\n\n"
        f"Имя: {data['full_name']}\n"
        f"Телефон: {data['phone']}\n"
        f"Специализация: {specialty}\n"
        f"TG ID: {message.from_user.id}"
    )

    for admin_id in config.ADMIN_IDS:
        try:
            await message.bot.send_message(chat_id=admin_id, text=admin_notify, reply_markup=approve_kb)
        except Exception:
            pass


@router.message(lambda msg: msg.text == "Мой профиль")
async def show_profile(message: Message):
    user = await get_user(message.from_user.id)
    if not user:
        await message.answer("Профиль не найден. Введите /start для регистрации.")
        return

    text = (
        f"Ваш профиль:\n\n"
        f"Имя: {user.full_name}\n"
        f"Телефон: {user.phone}\n"
        f"Специализация: {user.specialty}\n"
        f"Статус: {'Подтверждён' if user.is_approved else 'На проверке'}"
    )
    await message.answer(text)
