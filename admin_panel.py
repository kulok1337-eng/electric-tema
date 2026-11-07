from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)
import config
from database.requests import delete_user, get_stats, get_user, list_masters, list_orders
from handlers.order_notify import client_contact_line, is_client_order, source_label

router = Router()
router.message.filter(F.from_user.id.in_(config.ADMIN_IDS))
router.callback_query.filter(F.from_user.id.in_(config.ADMIN_IDS))

STATUS_RU = {
    "new": "Новая",
    "in": "В работе",
    "sd": "СД",
    "in_progress": "В работе",
    "completed": "Завершена",
    "canceled": "Отклонена",
}


def admin_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Новые заявки"), KeyboardButton(text="В работе")],
            [KeyboardButton(text="СД"), KeyboardButton(text="Все заявки")],
            [KeyboardButton(text="Статистика")],
            [KeyboardButton(text="Мастера"), KeyboardButton(text="На модерации")],
        ],
        resize_keyboard=True,
    )


def order_text(o) -> str:
    header = f"Заявка #{o.id} [{STATUS_RU.get(o.status, o.status)}] — {source_label(o)}\n"
    if is_client_order(o):
        tg = client_contact_line(o)
        text = (
            header
            + f"Клиент: {o.client_name or 'не указано'}, {o.client_phone}\n"
            + (f"Telegram: {tg}\n" if tg else "")
            + f"Адрес: {o.address}\n"
            f"Задача: {o.description}\n"
            f"Сроки: {o.desired_date}"
        )
    else:
        text = (
            header
            + f"Мастер (TG ID): {o.master_id}\n"
            f"Клиент: {o.client_phone}\n"
            f"Адрес: {o.address}\n"
            f"Задача: {o.description}\n"
            f"Сроки: {o.desired_date}"
        )
    if o.status == "completed":
        if is_client_order(o):
            text += f"\nЧек: {o.deal_amount} руб.\nКомиссия: не начисляется (заявка клиента)"
        else:
            text += f"\nЧек: {o.deal_amount} руб.\nКомиссия: {o.commission_amount} руб."
    return text


def order_kb(o) -> InlineKeyboardMarkup | None:
    if o.status in ("completed", "canceled"):
        return None
    rows = []
    if o.status == "new":
        rows.append([InlineKeyboardButton(text="В работу", callback_data=f"ord_stat_{o.id}_in_progress")])
    rows.append([InlineKeyboardButton(text="Закрыть заявку", callback_data=f"rep_close_{o.id}")])
    if o.status != "sd":
        rows.append([InlineKeyboardButton(text="Перевести в СД", callback_data=f"rep_sd_{o.id}")])
    rows.append([InlineKeyboardButton(text="Отказ клиента", callback_data=f"rep_refuse_{o.id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("admin"))
async def cmd_admin(message: Message):
    await message.answer("Панель администратора. Выберите раздел:", reply_markup=admin_menu())


async def send_orders(message: Message, status: str | None, title: str):
    orders = await list_orders(status)
    if not orders:
        await message.answer(f"{title}: пока пусто.")
        return
    await message.answer(f"{title} (последние {len(orders)}):")
    for o in reversed(orders):
        await message.answer(order_text(o), reply_markup=order_kb(o))


@router.message(F.text == "Новые заявки")
async def new_orders(message: Message):
    await send_orders(message, "new", "Новые заявки")


@router.message(F.text == "В работе")
async def in_progress_orders(message: Message):
    await send_orders(message, "in_progress", "Заявки в работе")


@router.message(F.text == "СД")
async def sd_orders(message: Message):
    await send_orders(message, "sd", "Заявки в СД")


@router.message(F.text == "Все заявки")
async def all_orders(message: Message):
    await send_orders(message, None, "Все заявки")


@router.message(F.text == "Статистика")
async def stats(message: Message):
    s = await get_stats()
    by = s["by_status"]
    await message.answer(
        "Статистика\n\n"
        f"Заявок всего: {s['orders_total']} (от клиентов: {s['client_orders']})\n"
        f"Новые: {by.get('new', 0)}\n"
        f"В работе: {by.get('in_progress', 0)}\n"
        f"СД: {by.get('sd', 0)}\n"
        f"Завершено: {by.get('completed', 0)}\n"
        f"Отклонено: {by.get('canceled', 0)}\n\n"
        f"Сумма сделок: {s['deal_sum']} руб.\n"
        f"Комиссия: {s['commission_sum']} руб.\n\n"
        f"Мастеров: {s['masters_total']} (на модерации: {s['masters_pending']})"
    )


@router.message(F.text == "Мастера")
async def masters(message: Message):
    items = await list_masters(approved=True)
    if not items:
        await message.answer("Подтверждённых мастеров пока нет.")
        return
    for m in items:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="Удалить", callback_data=f"adm_del_{m.telegram_id}")]]
        )
        await message.answer(
            f"{m.full_name}\nТелефон: {m.phone}\nСпециализация: {m.specialty}\nTG ID: {m.telegram_id}",
            reply_markup=kb,
        )


@router.message(F.text == "На модерации")
async def pending(message: Message):
    items = await list_masters(approved=False)
    if not items:
        await message.answer("Нет анкет на модерации.")
        return
    for m in items:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="Одобрить", callback_data=f"adm_appr_{m.telegram_id}"),
                    InlineKeyboardButton(text="Отклонить", callback_data=f"adm_decl_{m.telegram_id}"),
                ]
            ]
        )
        await message.answer(
            f"{m.full_name}\nТелефон: {m.phone}\nСпециализация: {m.specialty}\nTG ID: {m.telegram_id}",
            reply_markup=kb,
        )


@router.callback_query(F.data.startswith("adm_del_"))
async def delete_master(callback: CallbackQuery):
    user_id = int(callback.data.split("_")[2])
    user = await get_user(user_id)
    if user and user.role == "master":
        await delete_user(user_id)
        await callback.message.edit_text(f"{callback.message.text}\n\n[Мастер удалён]")
    await callback.answer()
