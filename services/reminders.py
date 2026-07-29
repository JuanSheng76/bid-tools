"""提醒服务"""
from datetime import datetime, timedelta
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from models import BidNotice, BidResult, Task


async def get_upcoming_deadlines(db: AsyncSession, days: int = 7) -> list[dict]:
    """获取即将到期的标讯和任务"""
    now = datetime.utcnow()
    deadline = now + timedelta(days=days)
    reminders = []

    # 标讯截止日期
    notices = (await db.execute(
        select(BidNotice).where(
            BidNotice.status.in_(["new", "assessing", "worth", "registered", "bidding"]),
            BidNotice.bid_deadline.isnot(None),
            BidNotice.bid_deadline <= deadline,
            BidNotice.bid_deadline >= now,
        )
    )).scalars().all()

    for n in notices:
        days_left = (n.bid_deadline - now).days if n.bid_deadline else 0
        reminders.append({
            "type": "bid_deadline",
            "title": n.title,
            "date": n.bid_deadline,
            "days_left": days_left,
            "url": f"/notices/{n.id}",
        })

    # 任务到期
    tasks = (await db.execute(
        select(Task).where(
            Task.status != "done",
            Task.planned_end.isnot(None),
            Task.planned_end <= deadline,
            Task.planned_end >= now,
        ).options(selectinload(Task.notice))
    )).scalars().all()

    for t in tasks:
        days_left = (t.planned_end - now).days if t.planned_end else 0
        reminders.append({
            "type": "task_due",
            "title": t.title,
            "date": t.planned_end,
            "days_left": days_left,
            "url": f"/tasks/{t.id}",
            "notice_title": t.notice.title if t.notice else None,
            "notice_id": t.notice_id,
        })

    # 合同到期
    soon = now + timedelta(days=30)
    contracts = (await db.execute(
        select(BidResult).where(
            BidResult.contract_expiry_date.isnot(None),
            BidResult.contract_expiry_date <= soon,
            BidResult.contract_expiry_date >= now,
            BidResult.result == "won",
        )
    )).scalars().all()

    for c in contracts:
        days_left = (c.contract_expiry_date - now).days if c.contract_expiry_date else 0
        reminders.append({
            "type": "contract_expiry",
            "title": f"合同到期: {c.winning_company or '未知单位'}",
            "date": c.contract_expiry_date,
            "days_left": days_left,
            "url": f"/results",
        })

    # 按紧急程度排序
    reminders.sort(key=lambda r: r["days_left"])
    return reminders


async def check_contract_expiry(db: AsyncSession) -> list[BidResult]:
    """检查即将到期的合同"""
    now = datetime.utcnow()
    soon = now + timedelta(days=30)
    results = (await db.execute(
        select(BidResult).where(
            BidResult.contract_expiry_date.isnot(None),
            BidResult.contract_expiry_date <= soon,
            BidResult.result == "won",
        )
    )).scalars().all()
    return list(results)
