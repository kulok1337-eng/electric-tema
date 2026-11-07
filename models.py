import logging
import os
import sqlite3
from datetime import datetime
from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.ext.asyncio import AsyncAttrs, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

DB_PATH = "bot_database.db"

engine = create_async_engine(f"sqlite+aiosqlite:///{DB_PATH}", echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False)


class Base(AsyncAttrs, DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(128))
    phone: Mapped[str] = mapped_column(String(32))
    specialty: Mapped[str] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(16), default="master")
    is_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Для заявок мастеров — Telegram ID мастера. Для прямых заявок клиентов — 0.
    master_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id"))
    # Для заявок клиентов здесь телефон самого клиента.
    client_phone: Mapped[str] = mapped_column(String(32))
    address: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    desired_date: Mapped[str] = mapped_column(String(128))
    photo_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="new")
    deal_amount: Mapped[float] = mapped_column(Float, default=0.0)
    commission_amount: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    # Источник заявки: "master" (через мастера) или "client" (напрямую от клиента)
    source: Mapped[str] = mapped_column(String(16), default="master", server_default="master")
    client_tg_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    client_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    client_username: Mapped[str | None] = mapped_column(String(64), nullable=True)


class OrderReport(Base):
    __tablename__ = "order_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(Integer, index=True)
    kind: Mapped[str] = mapped_column(String(16))  # close / sd / refuse
    data: Mapped[str] = mapped_column(Text)  # JSON с ответами
    reminded: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# Колонки, добавленные в orders после первой версии бота: (имя, DDL для ALTER TABLE).
# Существующие заявки автоматически получают source='master'.
ORDERS_NEW_COLUMNS = [
    ("source", "VARCHAR(16) NOT NULL DEFAULT 'master'"),
    ("client_tg_id", "BIGINT"),
    ("client_name", "VARCHAR(128)"),
    ("client_username", "VARCHAR(64)"),
]


def migrate_sqlite(db_path: str) -> list[str]:
    """Безопасная миграция: только ALTER TABLE ... ADD COLUMN, данные не удаляются.

    Если в orders не хватает колонок — сначала делается копия файла базы
    (<имя>.bak-ГГГГММДД-ЧЧММСС), затем колонки добавляются. Повторный запуск
    ничего не меняет. Возвращает список добавленных колонок.
    """
    if not os.path.exists(db_path) or os.path.getsize(db_path) == 0:
        return []  # базы ещё нет — таблицы создаст create_all уже в новой схеме

    conn = sqlite3.connect(db_path)
    try:
        has_orders = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='orders'"
        ).fetchone()
        if not has_orders:
            return []
        existing = {row[1] for row in conn.execute("PRAGMA table_info(orders)")}
        missing = [(name, ddl) for name, ddl in ORDERS_NEW_COLUMNS if name not in existing]
        if not missing:
            return []

        backup = f"{db_path}.bak-{datetime.now():%Y%m%d-%H%M%S}"
        try:
            # backup() корректно копирует базу даже если она открыта
            dst = sqlite3.connect(backup)
            try:
                conn.backup(dst)
            finally:
                dst.close()
            logging.info("Перед миграцией создана копия базы: %s", backup)
        except Exception:
            logging.exception("Не удалось создать копию базы перед миграцией")
            raise  # без бэкапа базу не трогаем

        for name, ddl in missing:
            conn.execute(f"ALTER TABLE orders ADD COLUMN {name} {ddl}")
        conn.commit()
        added = [name for name, _ in missing]
        logging.info("Миграция БД: в orders добавлены колонки %s", added)
        return added
    finally:
        conn.close()


async def init_db():
    migrate_sqlite(DB_PATH)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
