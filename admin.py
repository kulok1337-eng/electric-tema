from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, KeyboardButton, Message, ReplyKeyboardMarkup
import config
from database.requests import approve_user, close_order, delete_user, get_order, update_order_status
from handlers.order_notify import client_status_text, is_client_order, notify_owner

router = Router()


def master_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Передать заказ")], [KeyboardButton(text="Мой профиль")]],
        resize_keyboard=True,
    )


class CloseDealStates(StatesGroup):
    waiting_for_amount = State()


@router.callback_query(F.data.startswith("adm_appr_"))
async def handle_approve_master(callback: CallbackQuery):
    if callback.from_user.id not in config.ADMIN_IDS:
        return

    user_id = int(callback.data.split("_")[2])
    await approve_user(user_id)
    await callback.message.edit_text(f"{callback.message.text}\n\n[Мастер успешно одобрен]")
    await callback.bot.send_message(chat_id=user_id, text="Ваша анкета одобрена! Теперь вы можете передавать заказы через меню бота.", reply_markup=master_menu())


@router.callback_query(F.data.startswith("adm_decl_"))
async def handle_decline_master(callback: CallbackQuery):
    if callback.from_user.id not in config.ADMIN_IDS:
        return

    user_id = int(callback.data.split("_")[2])
    await delete_user(user_id)
    await callback.message.edit_text(f"{callback.message.text}\n\n[Регистрация отклонена]")
    await callback.bot.send_message(chat_id=user_id, text="К сожалению, доступ к сервису не был подтверждён.")


@router.callback_query(F.data.startswith("ord_stat_"))
async def handle_status_change(callback: CallbackQuery):
    if callback.from_user.id not in config.ADMIN_IDS:
        return

    parts = callback.data.split("_", 3)
    order_id = int(parts[2])
    new_status = parts[3]

    await update_order_status(order_id, new_status)
    order = await get_order(order_id)

    status_ru = {"in_progress": "В работе", "canceled": "Отклонён"}.get(new_status, new_status)
    await callback.answer(f"Статус изменён: {status_ru}")

    if order:
        if is_client_order(order):
            text = client_status_text(order.id, new_status, status_ru)
        else:
            text = f"Статус вашей заявки #{order.id} изменён на: {status_ru}"
        await notify_owner(callback.bot, order, text)


@router.callback_query(F.data.startswith("ord_close_"))
async def start_closing_order(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in config.ADMIN_IDS:
        return

    order_id = int(callback.data.split("_")[2])
    await state.update_data(closing_order_id=order_id)
    await state.set_state(CloseDealStates.waiting_for_amount)
    await callback.message.answer(f"Введите стоимость работы без материалов для заказа #{order_id} (только число):")


@router.message(CloseDealStates.waiting_for_amount)
async def process_closing_amount(message: Message, state: FSMContext):
    if message.from_user.id not in config.ADMIN_IDS:
        return

    try:
        deal_amount = float(message.text.strip().replace(",", "."))
    except ValueError:
        await message.answer("Введите число корректно (например: 15000).")
        return

    data = await state.get_data()
    order_id = data["closing_order_id"]
    order = await get_order(order_id)
    is_client = is_client_order(order)
    if is_client:
        # Прямая заявка клиента: партнёра нет, комиссия не начисляется
        percent, commission = 0.0, 0.0
    else:
        percent = config.get_partner_percent(deal_amount)
        commission = round(deal_amount * percent / 100.0, 2)

    await close_order(order_id, deal_amount, commission)
    await state.clear()

    if is_client:
        await message.answer(
            f"Заказ #{order_id} закрыт.\nСтоимость работы: {deal_amount} руб.\n"
            "Прямая заявка клиента: партнёрская комиссия не начисляется."
        )
    else:
        await message.answer(f"Заказ #{order_id} закрыт.\nСтоимость работы: {deal_amount} руб.\nПартнёру ({percent:g}%): {commission} руб.\nВам ({100 - percent:g}%): {round(deal_amount - commission, 2)} руб.")

    if order:
        if is_client:
            text = f"Заявка #{order_id} выполнена. Спасибо, что обратились!"
        else:
            text = (
                f"Заказ #{order_id} успешно закрыт!\n\n"
                f"Стоимость работы: {deal_amount} руб.\n"
                f"Ваша выплата ({percent:g}%): {commission} руб."
            )
        await notify_owner(message.bot, order, text)
