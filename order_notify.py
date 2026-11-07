"""Общие функции для заявок: карточка для администраторов и уведомление автора заявки.

Здесь нет роутера — модуль только импортируется из других обработчиков.
"""
import logging

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
import config

CAPTION_LIMIT = 1024  # лимит Telegram на подпись к фото


def is_client_order(order) -> bool:
    return bool(order) and getattr(order, "source", config.SOURCE_MASTER) == config.SOURCE_CLIENT


def source_label(order) -> str:
    return "От клиента" if is_client_order(order) else "От мастера"


def client_contact_line(order) -> str:
    """Строка с Telegram клиента для карточек администраторов."""
    parts = []
    if order.client_username:
        parts.append(f"@{order.client_username}")
    if order.client_tg_id:
        parts.append(f"ID {order.client_tg_id}")
    return ", ".join(parts)


def new_order_kb(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="В работу", callback_data=f"ord_stat_{order_id}_in_progress"),
                InlineKeyboardButton(text="Завершить", callback_data=f"ord_close_{order_id}"),
            ],
            [
                InlineKeyboardButton(text="Отказ", callback_data=f"ord_stat_{order_id}_canceled"),
            ],
        ]
    )


def build_admin_card(order, master=None) -> str:
    if is_client_order(order):
        lines = [
            f"Новый заказ #{order.id} — От клиента",
            "",
            f"Имя: {order.client_name or 'не указано'}",
            f"Телефон: {order.client_phone}",
            f"Адрес: {order.address}",
            f"Задача: {order.description}",
            f"Удобное время: {order.desired_date}",
        ]
        tg = client_contact_line(order)
        if tg:
            lines.append(f"Telegram: {tg}")
        lines.append("Партнёрская комиссия: не начисляется")
        return "\n".join(lines)

    master_info = f"{master.full_name} ({master.phone})" if master else f"TG ID {order.master_id}"
    return (
        f"Новый заказ #{order.id} — От мастера\n"
        f"Мастер: {master_info}\n\n"
        f"Клиент: {order.client_phone}\n"
        f"Адрес: {order.address}\n"
        f"Задача: {order.description}\n"
        f"Сроки: {order.desired_date}"
    )


async def send_order_to_admins(bot, order, master=None) -> int:
    """Рассылает карточку новой заявки всем администраторам. Возвращает число доставленных."""
    card = build_admin_card(order, master)
    kb = new_order_kb(order.id)
    delivered = 0
    for admin_id in config.ADMIN_IDS:
        try:
            if order.photo_id and len(card) <= CAPTION_LIMIT:
                await bot.send_photo(chat_id=admin_id, photo=order.photo_id, caption=card, reply_markup=kb)
            else:
                if order.photo_id:  # длинный текст не помещается в подпись к фото
                    await bot.send_photo(chat_id=admin_id, photo=order.photo_id)
                await bot.send_message(chat_id=admin_id, text=card, reply_markup=kb)
            delivered += 1
        except Exception as e:  # админ мог не запускать бота
            logging.warning("Не удалось отправить заявку #%s админу %s: %s", order.id, admin_id, e)
    return delivered


def owner_chat_id(order) -> int | None:
    """Кому писать о заявке: мастеру (его заявка) или клиенту (прямая заявка)."""
    if is_client_order(order):
        return order.client_tg_id
    return order.master_id


async def notify_owner(bot, order, text: str):
    chat_id = owner_chat_id(order)
    if not chat_id:
        return
    try:
        await bot.send_message(chat_id, text)
    except Exception as e:
        logging.warning("Не удалось уведомить %s по заявке #%s: %s", chat_id, order.id, e)


def client_status_text(order_id: int, new_status: str, status_ru: str) -> str:
    if new_status == "in_progress":
        return f"Ваша заявка #{order_id} принята в работу. Мастер свяжется с вами по указанному телефону."
    if new_status == "canceled":
        return f"К сожалению, заявка #{order_id} отклонена. Если вопрос остался актуальным — оформите новую через /start."
    return f"Статус вашей заявки #{order_id} изменён на: {status_ru}"
