import asyncio
import json
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
import config
from database.requests import (
    add_report,
    close_order,
    get_order,
    list_sd_due,
    mark_reminded,
    update_order_status,
)
from handlers.order_notify import is_client_order, notify_owner

router = Router()
router.message.filter(F.from_user.id.in_(config.ADMIN_IDS))
router.callback_query.filter(F.from_user.id.in_(config.ADMIN_IDS))


class RS(StatesGroup):
    answering = State()
    loyal = State()


# (ключ, вопрос, тип: num | text)
FLOWS = {
    "close": [
        ("total", "Общая сумма по заявке (число):", "num"),
        ("expense", "Сумма расхода на материалы (число, 0 если не было):", "num"),
        ("works", "Какие работы проведены на адресе:", "text"),
    ],
    "sd": [
        ("prepay", "Сколько взяли предоплаты (число, 0 если не брали):", "num"),
        ("works", "Какие работы необходимо сделать:", "text"),
        ("date", "Дата, когда планируется закрытие СД:", "text"),
        ("agreed", "Согласованная сумма (число):", "num"),
    ],
    "refuse": [
        ("money", "Сколько взяли денег (0, 500, 1000...):", "num"),
        ("todo", "Что требовалось сделать:", "text"),
        ("range", "Какая вилка цен предложена:", "text"),
        ("cost", "Сколько бы вышло себестоимости:", "text"),
        ("told", "Сколько озвучили клиенту за ремонт:", "text"),
        ("reason", "Причина отказа клиента:", "text"),
    ],
}

TITLES = {"close": "Закрытие заявки", "sd": "Перевод в СД", "refuse": "Отказ"}

LABELS = {
    "total": "Общая сумма",
    "expense": "Расход",
    "net": "Чистые деньги",
    "works": "Работы",
    "prepay": "Предоплата",
    "date": "Дата закрытия СД",
    "agreed": "Согласованная сумма",
    "money": "Взяли денег",
    "todo": "Что требовалось",
    "range": "Вилка цен",
    "cost": "Себестоимость",
    "told": "Озвучено клиенту",
    "reason": "Причина отказа",
    "loyal": "Лояльный клиент",
}


def parse_num(text: str) -> float | None:
    try:
        return float(text.strip().replace(" ", "").replace(",", "."))
    except ValueError:
        return None


@router.callback_query(F.data.regexp(r"^rep_(close|sd|refuse)_\d+$"))
async def start_report(callback: CallbackQuery, state: FSMContext):
    _, kind, order_id = callback.data.split("_")
    await state.clear()
    await state.set_state(RS.answering)
    await state.update_data(kind=kind, order_id=int(order_id), idx=0, answers={})
    await callback.message.answer(
        f"{TITLES[kind]} по заявке #{order_id}. Отмена: /cancel\n\n{FLOWS[kind][0][1]}"
    )
    await callback.answer()


@router.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Отменено.")


@router.message(RS.answering, F.text)
async def answer_step(message: Message, state: FSMContext):
    data = await state.get_data()
    kind, idx, answers = data["kind"], data["idx"], data["answers"]
    key, _, kind_type = FLOWS[kind][idx]

    if kind_type == "num":
        value = parse_num(message.text)
        if value is None:
            await message.answer("Введите число (например: 15000).")
            return
        answers[key] = value
    else:
        answers[key] = message.text.strip()

    idx += 1
    await state.update_data(idx=idx, answers=answers)
    if idx < len(FLOWS[kind]):
        await message.answer(FLOWS[kind][idx][1])
        return

    await state.set_state(RS.loyal)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="Да, лояльный", callback_data="rep_loy_1"),
            InlineKeyboardButton(text="Нет", callback_data="rep_loy_0"),
        ]]
    )
    await message.answer("Клиент лояльный?", reply_markup=kb)


def format_report(order_id: int, kind: str, answers: dict) -> str:
    lines = [f"{TITLES[kind]} - заявка #{order_id}"]
    for key, value in answers.items():
        if isinstance(value, float):
            value = f"{value:g} руб."
        lines.append(f"{LABELS.get(key, key)}: {value}")
    return "\n".join(lines)


@router.callback_query(RS.loyal, F.data.in_({"rep_loy_1", "rep_loy_0"}))
async def finish_report(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    kind, order_id, answers = data["kind"], data["order_id"], data["answers"]
    answers["loyal"] = "да" if callback.data == "rep_loy_1" else "нет"
    await state.clear()

    order = await get_order(order_id)
    is_client = is_client_order(order)  # прямая заявка клиента: без партнёра и комиссии

    master_text = ""  # текст автору заявки (мастеру или клиенту)
    if kind == "close":
        net = round(answers["total"] - answers["expense"], 2)
        answers["net"] = net
        if is_client:
            await close_order(order_id, net, 0.0)
            summary_extra = "\nПрямая заявка клиента: партнёрская комиссия не начисляется."
            master_text = f"Заявка #{order_id} выполнена. Спасибо, что обратились!"
        else:
            percent = config.get_partner_percent(net)
            commission = round(net * percent / 100.0, 2)
            await close_order(order_id, net, commission)
            summary_extra = (
                f"\nПартнёру ({percent:g}%): {commission} руб.\nВам ({100 - percent:g}%): {round(net - commission, 2)} руб."
            )
            master_text = (
                f"Заказ #{order_id} успешно закрыт!\n\n"
                f"Стоимость работы без материалов: {net} руб.\n"
                f"Ваша выплата ({percent:g}%): {commission} руб."
            )
    elif kind == "sd":
        await update_order_status(order_id, "sd")
        summary_extra = ""
        if not is_client:
            master_text = (
                f"Заявка #{order_id} переведена в СД. Планируемая дата закрытия: {answers['date']}. "
                "СД закрываются в срок до 7 дней."
            )
    else:
        await update_order_status(order_id, "canceled")
        summary_extra = ""
        if not is_client:
            master_text = f"По заявке #{order_id} зафиксирован отказ клиента."

    await add_report(order_id, kind, answers)
    summary = format_report(order_id, kind, answers) + summary_extra

    await callback.message.edit_text("Клиент лояльный: " + answers["loyal"])
    for admin_id in config.ADMIN_IDS:
        try:
            await callback.bot.send_message(admin_id, summary)
        except Exception as e:  # админ мог не запускать бота
            logging.warning("Не удалось отправить отчёт админу %s: %s", admin_id, e)

    if order and master_text:
        await notify_owner(callback.bot, order, master_text)
    await callback.answer()


async def sd_reminder_loop(bot):
    """Раз в 3 часа напоминает о СД, которым пошёл 5-й день из 7."""
    while True:
        try:
            for report in await list_sd_due(days=5):
                order = await get_order(report.order_id)
                data = json.loads(report.data)
                text = (
                    f"Напоминание: СД по заявке #{report.order_id} нужно закрыть в срок до 7 дней. "
                    f"Планируемая дата: {data.get('date', 'не указана')}."
                )
                # по прямым заявкам клиентов мастера нет — напоминаем только админам
                targets = list(config.ADMIN_IDS) + ([order.master_id] if order and not is_client_order(order) else [])
                for chat_id in targets:
                    try:
                        await bot.send_message(chat_id, text)
                    except Exception as e:
                        logging.warning("Напоминание не отправлено %s: %s", chat_id, e)
                await mark_reminded(report.id)
        except Exception:
            logging.exception("Ошибка в цикле напоминаний СД")
        await asyncio.sleep(3 * 60 * 60)
