"""仪表盘"""
from datetime import datetime
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from models import BidNotice, Task, BidResult, User
from auth import get_session
from services.reminders import get_upcoming_deadlines
from templates_config import templates

router = APIRouter(prefix="", tags=["dashboard"])


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    session = get_session(request)
    if not session:
        return RedirectResponse(url="/login")

    # 统计数据
    new_notices = (await db.execute(
        select(func.count()).where(BidNotice.status.in_(["new", "assessing"]))
    )).scalar() or 0

    active_bids = (await db.execute(
        select(func.count()).where(BidNotice.status.in_(["worth", "registered", "bidding"]))
    )).scalar() or 0

    urgent_tasks = (await db.execute(
        select(func.count()).where(Task.status.in_(["todo", "in_progress"]))
    )).scalar() or 0

    total_wins = (await db.execute(
        select(func.count()).where(BidResult.result == "won")
    )).scalar() or 0

    # 最近标讯
    recent_notices = (await db.execute(
        select(BidNotice).order_by(BidNotice.created_at.desc()).limit(10)
    )).scalars().all()

    # 即将到期的任务
    upcoming_tasks = (await db.execute(
        select(Task)
        .options(selectinload(Task.notice), selectinload(Task.assignee))
        .where(Task.status != "done")
        .order_by(Task.planned_end.asc())
        .limit(10)
    )).scalars().all()

    # 用户列表（用于任务分配）
    users = (await db.execute(select(User).where(User.is_active == True))).scalars().all()

    # 提醒（近7天截止的标讯、任务、合同）
    reminders = await get_upcoming_deadlines(db, days=7)

    # 图表数据：近12个月中标/未中标趋势
    chart_data = await _get_monthly_stats(db)

    # 中标率
    total_decided = (await db.execute(
        select(func.count()).where(BidResult.result.in_(["won", "lost"]))
    )).scalar() or 0
    win_rate = round(total_wins / total_decided * 100, 1) if total_decided > 0 else 0

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "session": session,
        "new_notices": new_notices,
        "active_bids": active_bids,
        "urgent_tasks": urgent_tasks,
        "total_wins": total_wins,
        "win_rate": win_rate,
        "total_decided": total_decided,
        "recent_notices": recent_notices,
        "upcoming_tasks": upcoming_tasks,
        "users": users,
        "reminders": reminders,
        "chart_data": chart_data,
    })


async def _get_monthly_stats(db: AsyncSession) -> dict:
    """获取近12个月中标/未中标月度统计（用于 Chart.js）"""
    from datetime import timedelta
    import json

    now = datetime.utcnow()
    labels = []
    won_data = []
    lost_data = []

    for i in range(11, -1, -1):
        month_start = datetime(now.year, now.month, 1) - timedelta(days=i * 30)
        # 规范化到当月1号
        month_start = datetime(month_start.year, month_start.month, 1)
        if i == 0:
            month_end = now
        else:
            if month_start.month == 12:
                month_end = datetime(month_start.year + 1, 1, 1)
            else:
                month_end = datetime(month_start.year, month_start.month + 1, 1)

        labels.append(month_start.strftime("%Y-%m"))

        won_count = (await db.execute(
            select(func.count()).where(
                BidResult.result == "won",
                BidResult.created_at >= month_start,
                BidResult.created_at < month_end,
            )
        )).scalar() or 0

        lost_count = (await db.execute(
            select(func.count()).where(
                BidResult.result == "lost",
                BidResult.created_at >= month_start,
                BidResult.created_at < month_end,
            )
        )).scalar() or 0

        won_data.append(won_count)
        lost_data.append(lost_count)

    return {
        "labels": labels,
        "won": won_data,
        "lost": lost_data,
    }


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    session = get_session(request)
    if session:
        return RedirectResponse(url="/")
    return templates.TemplateResponse("auth/login.html", {"request": request})
