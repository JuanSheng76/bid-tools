"""仪表盘"""
from datetime import datetime
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select, func, or_
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
    funnel_data = await _get_bid_funnel(db)

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
        "funnel_data": funnel_data,
    })


async def _get_bid_funnel(db: AsyncSession) -> dict:
    """统计从获取标讯到投标结果的转化漏斗。"""

    total_notices = (await db.execute(
        select(func.count(BidNotice.id))
    )).scalar() or 0

    # 已有结果的历史数据必然经过“确定投标”，兼容旧数据未记录 bid_decision 的情况。
    confirmed_bids = (await db.execute(
        select(func.count(func.distinct(BidNotice.id)))
        .outerjoin(BidResult, BidResult.notice_id == BidNotice.id)
        .where(or_(
            BidNotice.bid_decision == "bid",
            BidResult.id.isnot(None),
        ))
    )).scalar() or 0

    result_rows = (await db.execute(
        select(BidResult.result, func.count(BidResult.id))
        .group_by(BidResult.result)
    )).all()
    result_counts = {result: count for result, count in result_rows}

    completed_bids = sum(result_counts.values())
    lost_bids = result_counts.get("lost", 0)
    won_bids = result_counts.get("won", 0)
    other_results = (
        result_counts.get("rejected", 0)
        + result_counts.get("cancelled", 0)
    )

    def percentage(value: int, total: int) -> float:
        return round(value / total * 100, 1) if total else 0

    return {
        "total": total_notices,
        "confirmed": confirmed_bids,
        "completed": completed_bids,
        "lost": lost_bids,
        "won": won_bids,
        "other": other_results,
        "confirmed_rate": percentage(confirmed_bids, total_notices),
        "completion_rate": percentage(completed_bids, confirmed_bids),
        "lost_share": percentage(lost_bids, completed_bids),
        "won_share": percentage(won_bids, completed_bids),
        "won_overall_rate": percentage(won_bids, total_notices),
        "confirmed_width": max(
            58, percentage(confirmed_bids, total_notices)
        ),
        "completed_width": max(
            44, percentage(completed_bids, total_notices)
        ),
        "won_width": max(
            30, percentage(won_bids, total_notices)
        ),
    }


async def _get_monthly_stats(db: AsyncSession) -> dict:
    """获取近12个自然月的结果构成及中标项目名称（用于 Chart.js）。"""

    now = datetime.utcnow()
    labels = []
    won_data = []
    lost_data = []
    rejected_data = []
    cancelled_data = []
    total_data = []
    won_projects = []

    def month_start_with_offset(offset: int) -> datetime:
        """以当前月为 0，精确移动自然月，避免按 30 天倒推造成月份重复。"""
        month_index = now.year * 12 + (now.month - 1) + offset
        year, zero_based_month = divmod(month_index, 12)
        return datetime(year, zero_based_month + 1, 1)

    for offset in range(-11, 1):
        month_start = month_start_with_offset(offset)
        month_end = now if offset == 0 else month_start_with_offset(offset + 1)

        labels.append(month_start.strftime("%y年%m月"))

        monthly_rows = (await db.execute(
            select(BidResult.result, func.count(BidResult.id))
            .where(
                BidResult.created_at >= month_start,
                BidResult.created_at < month_end,
            )
            .group_by(BidResult.result)
        )).all()
        counts = {result: count for result, count in monthly_rows}
        monthly_won_projects = (await db.execute(
            select(BidNotice.title)
            .join(BidResult, BidResult.notice_id == BidNotice.id)
            .where(
                BidResult.result == "won",
                BidResult.created_at >= month_start,
                BidResult.created_at < month_end,
            )
            .order_by(BidResult.opening_date.asc())
        )).scalars().all()

        won_count = counts.get("won", 0)
        lost_count = counts.get("lost", 0)
        rejected_count = counts.get("rejected", 0)
        cancelled_count = counts.get("cancelled", 0)
        total_count = won_count + lost_count + rejected_count + cancelled_count

        won_data.append(won_count)
        lost_data.append(lost_count)
        rejected_data.append(rejected_count)
        cancelled_data.append(cancelled_count)
        total_data.append(total_count)
        won_projects.append(monthly_won_projects)

    period_total = sum(total_data)
    period_wins = sum(won_data)
    period_lost = sum(lost_data)
    busiest_index = total_data.index(max(total_data)) if period_total else None
    observed_max = max(total_data, default=0)
    # 常规投标频次约每周 2–3 次，月度纵轴以 12 项作为基础容量。
    count_axis_max = max(12, ((observed_max + 1) // 2) * 2)
    count_axis_step = max(2, (count_axis_max + 5) // 6)

    return {
        "labels": labels,
        "won": won_data,
        "lost": lost_data,
        "rejected": rejected_data,
        "cancelled": cancelled_data,
        "total": total_data,
        "won_projects": won_projects,
        "period_total": period_total,
        "period_wins": period_wins,
        "period_lost": period_lost,
        "busiest_month": labels[busiest_index] if busiest_index is not None else "-",
        "busiest_count": total_data[busiest_index] if busiest_index is not None else 0,
        "count_axis_max": count_axis_max,
        "count_axis_step": count_axis_step,
    }


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    session = get_session(request)
    if session:
        return RedirectResponse(url="/")
    return templates.TemplateResponse("auth/login.html", {"request": request})
