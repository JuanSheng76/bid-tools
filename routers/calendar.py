"""日历视图 — 投标截止日期标记"""
import calendar
from datetime import datetime, timedelta
from fastapi import APIRouter, Request, Query, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from models import BidNotice
from auth import get_session
from templates_config import templates

router = APIRouter(prefix="/calendar", tags=["calendar"])


@router.get("", response_class=HTMLResponse)
async def calendar_view(
    request: Request,
    year: int = Query(None),
    month: int = Query(None),
    db: AsyncSession = Depends(get_db),
):
    session = get_session(request)
    if not session:
        return RedirectResponse(url="/login")

    now = datetime.utcnow()
    year = year or now.year
    month = month or now.month

    # 规范化月份
    if month < 1:
        year -= 1
        month = 12
    elif month > 12:
        year += 1
        month = 1

    # 查询该月有截止日期的标讯
    month_start = datetime(year, month, 1)
    if month == 12:
        month_end = datetime(year + 1, 1, 1)
    else:
        month_end = datetime(year, month + 1, 1)

    notices_with_deadlines = (await db.execute(
        select(BidNotice).where(
            BidNotice.bid_deadline >= month_start,
            BidNotice.bid_deadline < month_end,
        ).order_by(BidNotice.bid_deadline.asc())
    )).scalars().all()

    # 构建 {day: [notices]} 映射
    deadline_map = {}
    for n in notices_with_deadlines:
        day = n.bid_deadline.day
        if day not in deadline_map:
            deadline_map[day] = []
        deadline_map[day].append(n)

    # 生成日历格子
    cal = calendar.Calendar(firstweekday=0)  # 周一为第一天
    weeks = cal.monthdayscalendar(year, month)

    # 构建日历数据
    calendar_data = []
    today = now.date()

    for week in weeks:
        week_data = []
        for day_num in week:
            if day_num == 0:
                week_data.append({"day": 0, "notices": [], "is_today": False, "urgent": 0})
            else:
                date_obj = datetime(year, month, day_num).date()
                day_notices = deadline_map.get(day_num, [])
                # 统计紧急标讯（剩余<7天或已过期）
                urgent_count = sum(
                    1 for n in day_notices
                    if n.bid_deadline and (n.bid_deadline - now).days < 7
                )
                week_data.append({
                    "day": day_num,
                    "date": date_obj,
                    "notices": day_notices,
                    "is_today": date_obj == today,
                    "urgent": urgent_count,
                    "total": len(day_notices),
                })
        calendar_data.append(week_data)

    # 统计本月标讯总数
    month_total = len(notices_with_deadlines)
    month_urgent = sum(
        1 for n in notices_with_deadlines
        if n.bid_deadline and (n.bid_deadline - now).days < 7
    )

    # 上一月/下一月
    prev_month = month - 1
    prev_year = year
    if prev_month < 1:
        prev_month = 12
        prev_year -= 1

    next_month = month + 1
    next_year = year
    if next_month > 12:
        next_month = 1
        next_year += 1

    # 所有有截止日期的标讯（近3个月，用于右侧列表）
    three_months_end = month_end + timedelta(days=62)  # 往后推约2个月
    upcoming_notices = (await db.execute(
        select(BidNotice).where(
            BidNotice.bid_deadline >= month_start,
            BidNotice.bid_deadline < three_months_end,
        ).order_by(BidNotice.bid_deadline.asc())
    )).scalars().all()

    return templates.TemplateResponse("calendar.html", {
        "request": request,
        "session": session,
        "year": year,
        "month": month,
        "month_name": f"{year}年{month}月",
        "calendar_data": calendar_data,
        "month_total": month_total,
        "month_urgent": month_urgent,
        "prev_year": prev_year,
        "prev_month": prev_month,
        "next_year": next_year,
        "next_month": next_month,
        "upcoming_notices": upcoming_notices,
    })
