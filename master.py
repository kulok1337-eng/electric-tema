from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
import config
from database.requests import add_order, get_user
from handlers.order_notify import send_order_to_admins

router = Router()


class CreateOrderStates(StatesGroup):
    client_phone = State()
    address = State()
    description = State()
    desired_date = State()
    photo = State()
    confirm = State()


@router.message(F.text == "Передать заказ")
async def start_order_creation(message: Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    if not user or not user.is_approved:
        await message.answer("У вас нет доступа к передаче заказов.")
        return

    await state.set_state(CreateOrderStates.client_phone)
    await message.answer("Шаг 1 из 5: Введите номер телефона клиента:")


@router.message(CreateOrderStates.client_phone)
async def process_phone(message: Message, state: FSMContext):
    await state.update_data(client_phone=message.text.strip())
    await state.set_state(CreateOrderStates.address)
    await message.answer("Шаг 2 из 5: Введите адрес или район объекта:")


@router.message(CreateOrderStates.address)
async def process_address(message: Message, state: FSMContext):
    await state.update_data(address=message.text.strip())
    await state.set_state(CreateOrderStates.description)
    await message.answer("Шаг 3 из 5: Опишите задачу (какие работы требуются):")


@router.message(CreateOrderStates.description)
async def process_desc(message: Message, state: FSMContext):
    await state.update_data(description=message.text.strip())
    await state.set_state(CreateOrderStates.desired_date)
    await message.answer("Шаг 4 из 5: Укажите удобную дату и время для визита:")


@router.message(CreateOrderStates.desired_date)
async def process_date(message: Message, state: FSMContext):
    await state.update_data(desired_date=message.text.strip())
    await state.set_state(CreateOrderStates.photo)

    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Пропустить фото", callback_data="skip_order_photo")]])
    await message.answer("Шаг 5 из 5: Прикрепите фото объекта или нажмите кнопку ниже:", reply_markup=kb)


@router.message(CreateOrderStates.photo, F.photo)
async def process_photo(message: Message, state: FSMContext):
    photo_id = message.photo[-1].file_id
    await state.update_data(photo_id=photo_id)
    await show_order_confirmation(message, state)


@router.callback_query(CreateOrderStates.photo, F.data == "skip_order_photo")
async def process_skip_photo(callback: CallbackQuery, state: FSMContext):
    await state.update_data(photo_id=None)
    await callback.message.delete()
    await show_order_confirmation(callback.message, state)


async def show_order_confirmation(message: Message, state: FSMContext):
    data = await state.get_data()
    summary = (
        f"Проверьте правильность заявки:\n\n"
        f"Телефон клиента: {data['client_phone']}\n"
        f"Адрес: {data['address']}\n"
        f"Описание: {data['description']}\n"
        f"Дата и время: {data['desired_date']}\n"
        f"Фото: {'Прикреплено' if data.get('photo_id') else 'Отсутствует'}"
    )

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Отправить заказ", callback_data="order_confirm_send"),
                InlineKeyboardButton(text="Отменить", callback_data="order_cancel"),
            ]
        ]
    )
    await state.set_state(CreateOrderStates.confirm)
    await message.answer(summary, reply_markup=kb)


@router.callback_query(CreateOrderStates.confirm, F.data == "order_confirm_send")
async def send_order(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    order = await add_order(
        master_id=callback.from_user.id,
        client_phone=data["client_phone"],
        address=data["address"],
        description=data["description"],
        desired_date=data["desired_date"],
        photo_id=data.get("photo_id"),
        source=config.SOURCE_MASTER,
    )
    await state.clear()
    await callback.message.edit_text(f"Заявка #{order.id} успешно отправлена! Мы уведомим вас о смене статуса.")

    master = await get_user(callback.from_user.id)
    await send_order_to_admins(callback.bot, order, master)


@router.callback_query(CreateOrderStates.confirm, F.data == "order_cancel")
async def cancel_order(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Создание заявки отменено.")
