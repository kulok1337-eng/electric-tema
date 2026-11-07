from sqlalchemy import delete, select, update
import json
from datetime import datetime, timedelta
from database.models import Order, OrderReport, User, async_session


async def get_user(telegram_id: int) -> User | None:
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        return result.scalar_one_or_none()


async def create_user(
    telegram_id: int,
    full_name: str,
    phone: str,
    specialty: str,
    role: str = "master",
    is_approved: bool = False,
):
    async with async_session() as session:
        user = User(
            telegram_id=telegram_id,
            full_name=full_name,
            phone=phone,
            specialty=specialty,
            role=role,
            is_approved=is_approved,
        )
        session.add(user)
        await session.commit()
        return user


async def approve_user(telegram_id: int):
    async with async_session() as session:
        await session.execute(update(User).where(User.telegram_id == telegram_id).values(is_approved=True))
        await session.commit()


async def add_order(
    master_id: int,
    client_phone: str,
    address: str,
    description: str,
    desired_date: str,
    photo_id: str | None,
    source: str = "master",
    client_tg_id: int | None = None,
    client_name: str | None = None,
    client_username: str | None = None,
) -> Order:
    async with async_session() as session:
        order = Order(
            master_id=master_id,
            client_phone=client_phone,
            address=address,
            description=description,
            desired_date=desired_date,
            photo_id=photo_id,
            status="new",
            source=source,
            client_tg_id=client_tg_id,
            client_name=client_name,
            client_username=client_username,
        )
        session.add(order)
        await session.commit()
        await session.refresh(order)
        return order


async def get_order(order_id: int) -> Order | None:
    async with async_session() as session:
        result = await session.execute(select(Order).where(Order.id == order_id))
        return result.scalar_one_or_none()


async def update_order_status(order_id: int, status: str):
    async with async_session() as session:
        await session.execute(update(Order).where(Order.id == order_id).values(status=status))
        await session.commit()


async def close_order(order_id: int, deal_amount: float, commission_amount: float):
    async with async_session() as session:
        await session.execute(
            update(Order)
            .where(Order.id == order_id)
            .values(status="completed", deal_amount=deal_amount, commission_amount=commission_amount)
        )
        await session.commit()


async def list_orders(status: str | None = None, limit: int = 15) -> list[Order]:
    async with async_session() as session:
        query = select(Order).order_by(Order.id.desc()).limit(limit)
        if status:
            query = query.where(Order.status.in_(["in_progress", "in"]) if status == "in_progress" else Order.status == status)
        result = await session.execute(query)
        return list(result.scalars().all())


async def list_masters(approved: bool | None = None) -> list[User]:
    async with async_session() as session:
        query = select(User).where(User.role == "master").order_by(User.id.desc())
        if approved is not None:
            query = query.where(User.is_approved == approved)
        result = await session.execute(query)
        return list(result.scalars().all())


async def delete_user(telegram_id: int):
    async with async_session() as session:
        await session.execute(delete(User).where(User.telegram_id == telegram_id))
        await session.commit()


async def get_stats() -> dict:
    async with async_session() as session:
        orders = (await session.execute(select(Order))).scalars().all()
        masters = (await session.execute(select(User).where(User.role == "master"))).scalars().all()
    by_status: dict[str, int] = {}
    for o in orders:
        key = "in_progress" if o.status == "in" else o.status
        by_status[key] = by_status.get(key, 0) + 1
    return {
        "orders_total": len(orders),
        "by_status": by_status,
        "deal_sum": sum(o.deal_amount for o in orders if o.status == "completed"),
        "commission_sum": sum(o.commission_amount for o in orders if o.status == "completed"),
        "masters_total": len(masters),
        "masters_pending": sum(1 for m in masters if not m.is_approved),
        "client_orders": sum(1 for o in orders if o.source == "client"),
    }


async def add_report(order_id: int, kind: str, answers: dict):
    async with async_session() as session:
        session.add(OrderReport(order_id=order_id, kind=kind, data=json.dumps(answers, ensure_ascii=False)))
        await session.commit()


async def get_reports(order_id: int) -> list[OrderReport]:
    async with async_session() as session:
        result = await session.execute(
            select(OrderReport).where(OrderReport.order_id == order_id).order_by(OrderReport.id)
        )
        return list(result.scalars().all())


async def list_sd_due(days: int = 5) -> list[OrderReport]:
    """СД-отчёты старше N дней, по которым ещё не было напоминания, а заявка всё ещё в СД."""
    border = datetime.utcnow() - timedelta(days=days)
    async with async_session() as session:
        result = await session.execute(
            select(OrderReport)
            .join(Order, Order.id == OrderReport.order_id)
            .where(OrderReport.kind == "sd", OrderReport.reminded == False, OrderReport.created_at <= border, Order.status == "sd")  # noqa: E712
        )
        return list(result.scalars().all())


async def mark_reminded(report_id: int):
    async with async_session() as session:
        await session.execute(update(OrderReport).where(OrderReport.id == report_id).values(reminded=True))
        await session.commit()
