import os

# Токен: сначала берётся переменная окружения BOT_TOKEN (если задана на хостинге),
# иначе используется значение, прописанное здесь. Не выкладывайте этот файл в публичный репозиторий.
BOT_TOKEN = os.getenv("BOT_TOKEN") or "9290804875:AAFOXboAmzRTRI8o2lynWo1DLPqqIenttis"

# ID администраторов: Артём (диспетчер), владелец и третий администратор
ARTEM_ID = 5742960391
OWNER_ID = 1979046241
ADMIN3_ID = 8079727075

ADMIN_IDS = [ARTEM_ID, OWNER_ID, ADMIN3_ID]

# Источник заявки
SOURCE_MASTER = "master"
SOURCE_CLIENT = "client"
# У прямых заявок клиентов нет мастера: в orders.master_id (NOT NULL) пишем 0
CLIENT_MASTER_ID = 0


def get_partner_percent(work_cost: float) -> float:
    """Доля партнёра (мастера, передавшего заказ) от стоимости работы без материалов."""
    if work_cost < 4000:
        return 25.0
    if work_cost <= 7000:
        return 20.0
    return 15.0
