"""标讯管理"""
from datetime import datetime, timedelta
from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from io import BytesIO
from sqlalchemy import select, func, or_
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from models import BidNotice, BidSource
from auth import get_session
from services.assessor import assess_notice
from templates_config import templates

router = APIRouter(prefix="/notices", tags=["notices"])


def parse_date(s: str) -> datetime | None:
    """尝试解析日期字符串"""
    if not s or not s.strip():
        return None
    for fmt in ["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d"]:
        try:
            return datetime.strptime(s.strip(), fmt)
        except ValueError:
            continue
    return None


@router.get("", response_class=HTMLResponse)
async def notice_list(
    request: Request,
    status: str = "",
    decision: str = "",
    view: str = "",
    sort: str = "created",
    keyword: str = "",
    page: int = 1,
    db: AsyncSession = Depends(get_db),
):
    session = get_session(request)
    if not session:
        return RedirectResponse(url="/login")

    query = select(BidNotice).options(selectinload(BidNotice.source))
    count_query = select(func.count(BidNotice.id))

    if status:
        query = query.where(BidNotice.status == status)
        count_query = count_query.where(BidNotice.status == status)

    if keyword:
        kw_filter = or_(
            BidNotice.title.contains(keyword),
            BidNotice.project_scope.contains(keyword),
            BidNotice.qualification_requirements.contains(keyword),
        )
        query = query.where(kw_filter)
        count_query = count_query.where(kw_filter)

    if decision:
        query = query.where(BidNotice.bid_decision == decision)
        count_query = count_query.where(BidNotice.bid_decision == decision)

    now = datetime.utcnow()
    if view == "attention":
        condition = BidNotice.status.in_(["new", "assessing"])
        query = query.where(condition)
        count_query = count_query.where(condition)
    elif view == "expiring":
        condition = (
            BidNotice.bid_deadline.is_not(None)
            & (BidNotice.bid_deadline >= now)
            & (BidNotice.bid_deadline <= now + timedelta(days=7))
            & ~BidNotice.status.in_(["completed", "ignored"])
        )
        query = query.where(condition)
        count_query = count_query.where(condition)
    elif view == "overdue":
        condition = (
            BidNotice.bid_deadline.is_not(None)
            & (BidNotice.bid_deadline < now)
            & ~BidNotice.status.in_(["completed", "ignored"])
        )
        query = query.where(condition)
        count_query = count_query.where(condition)

    order_map = {
        "deadline": BidNotice.bid_deadline.asc(),
        "budget_desc": BidNotice.budget_amount.desc(),
        "budget_asc": BidNotice.budget_amount.asc(),
        "created": BidNotice.created_at.desc(),
    }

    total = (await db.execute(count_query)).scalar() or 0
    page_size = 20
    offset = (page - 1) * page_size
    total_pages = max(1, (total + page_size - 1) // page_size)

    notices = (await db.execute(
        query.order_by(order_map.get(sort, order_map["created"])).offset(offset).limit(page_size)
    )).scalars().all()

    return templates.TemplateResponse("notices/list.html", {
        "request": request,
        "session": session,
        "notices": notices,
        "status": status,
        "decision": decision,
        "view": view,
        "sort": sort,
        "keyword": keyword,
        "page": page,
        "total": total,
        "total_pages": total_pages,
    })


@router.get("/new", response_class=HTMLResponse)
async def notice_create_page(request: Request, db: AsyncSession = Depends(get_db)):
    session = get_session(request)
    if not session:
        return RedirectResponse(url="/login")

    sources = (await db.execute(select(BidSource).where(BidSource.is_active == True))).scalars().all()

    # 日期预设值：默认当前年份及月份，日由用户自行填写（统一用 01）
    now = datetime.utcnow()
    ym = now.strftime("%Y-%m")                                           # 当前年月
    pub_default = f"{ym}-01"                                             # 发布日期 (type="date")
    opening_default = f"{ym}-01T09:30"                                   # 开标时间 9:30
    registration_default = f"{ym}-01T17:00"                              # 报名截止 17:00
    bid_deadline_default = opening_default                               # 投标截止 = 开标时间

    return templates.TemplateResponse("notices/form.html", {
        "request": request,
        "session": session,
        "notice": None,
        "sources": sources,
        "defaults": {
            "publishing_date": pub_default,
            "registration_deadline": registration_default,
            "bid_deadline": bid_deadline_default,
            "bid_opening_date": opening_default,
        },
    })


@router.get("/{notice_id}", response_class=HTMLResponse)
async def notice_detail(request: Request, notice_id: str, db: AsyncSession = Depends(get_db)):
    session = get_session(request)
    if not session:
        return RedirectResponse(url="/login")

    notice = (await db.execute(
        select(BidNotice).where(BidNotice.id == notice_id).options(selectinload(BidNotice.tasks))
    )).scalar_one_or_none()
    if not notice:
        return HTMLResponse("标讯不存在", status_code=404)

    sources = (await db.execute(select(BidSource).where(BidSource.is_active == True))).scalars().all()

    return templates.TemplateResponse("notices/detail.html", {
        "request": request,
        "session": session,
        "notice": notice,
        "sources": sources,
    })


@router.post("", response_class=HTMLResponse)
async def notice_create(
    request: Request,
    title: str = Form(...),
    source_url: str = Form(""),
    publishing_date: str = Form(""),
    registration_deadline: str = Form(""),
    bid_deadline: str = Form(""),
    bid_opening_date: str = Form(""),
    bid_opening_location: str = Form(""),
    budget_amount: float = Form(None),
    bid_document_fee: float = Form(None),
    bid_bond_amount: float = Form(None),
    project_location: str = Form(""),
    project_scope: str = Form(""),
    qualification_requirements: str = Form(""),
    platform_registration_required: bool = Form(False),
    platform_name: str = Form(""),
    contact_person: str = Form(""),
    contact_phone: str = Form(""),
    contact_email: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    session = get_session(request)
    if not session:
        return RedirectResponse(url="/login")

    notice = BidNotice(
        title=title,
        source_url=source_url,
        publishing_date=parse_date(publishing_date),
        registration_deadline=parse_date(registration_deadline),
        bid_deadline=parse_date(bid_deadline),
        bid_opening_date=parse_date(bid_opening_date),
        bid_opening_location=bid_opening_location,
        budget_amount=budget_amount,
        bid_document_fee=bid_document_fee,
        bid_bond_amount=bid_bond_amount,
        project_location=project_location,
        project_scope=project_scope,
        qualification_requirements=qualification_requirements,
        platform_registration_required=platform_registration_required,
        platform_name=platform_name,
        contact_person=contact_person,
        contact_phone=contact_phone,
        contact_email=contact_email,
        is_manual=True,
        status="new",
    )
    db.add(notice)
    await db.commit()
    return RedirectResponse(url=f"/notices/{notice.id}", status_code=303)


@router.post("/{notice_id}/edit")
async def notice_update(
    request: Request,
    notice_id: str,
    title: str = Form(...),
    source_url: str = Form(""),
    publishing_date: str = Form(""),
    registration_deadline: str = Form(""),
    bid_deadline: str = Form(""),
    bid_opening_date: str = Form(""),
    bid_opening_location: str = Form(""),
    budget_amount: float = Form(None),
    bid_document_fee: float = Form(None),
    bid_bond_amount: float = Form(None),
    project_location: str = Form(""),
    project_scope: str = Form(""),
    qualification_requirements: str = Form(""),
    platform_registration_required: bool = Form(False),
    platform_name: str = Form(""),
    contact_person: str = Form(""),
    contact_phone: str = Form(""),
    contact_email: str = Form(""),
    status: str = Form("new"),
    db: AsyncSession = Depends(get_db),
):
    session = get_session(request)
    if not session:
        return RedirectResponse(url="/login")

    notice = (await db.execute(select(BidNotice).where(BidNotice.id == notice_id))).scalar_one_or_none()
    if not notice:
        return HTMLResponse("标讯不存在", status_code=404)

    notice.title = title
    notice.source_url = source_url
    notice.publishing_date = parse_date(publishing_date)
    notice.registration_deadline = parse_date(registration_deadline)
    notice.bid_deadline = parse_date(bid_deadline)
    notice.bid_opening_date = parse_date(bid_opening_date)
    notice.bid_opening_location = bid_opening_location
    notice.budget_amount = budget_amount
    notice.bid_document_fee = bid_document_fee
    notice.bid_bond_amount = bid_bond_amount
    notice.project_location = project_location
    notice.project_scope = project_scope
    notice.qualification_requirements = qualification_requirements
    notice.platform_registration_required = platform_registration_required
    notice.platform_name = platform_name
    notice.contact_person = contact_person
    notice.contact_phone = contact_phone
    notice.contact_email = contact_email
    notice.status = status

    await db.commit()
    return RedirectResponse(url=f"/notices/{notice_id}", status_code=303)


@router.post("/{notice_id}/delete")
async def notice_delete(request: Request, notice_id: str, db: AsyncSession = Depends(get_db)):
    session = get_session(request)
    if not session:
        return RedirectResponse(url="/login")

    notice = (await db.execute(select(BidNotice).where(BidNotice.id == notice_id))).scalar_one_or_none()
    if notice:
        await db.delete(notice)
        await db.commit()
    return RedirectResponse(url="/notices", status_code=303)


@router.post("/{notice_id}/assess")
async def notice_assess(request: Request, notice_id: str, db: AsyncSession = Depends(get_db)):
    """执行评估"""
    session = get_session(request)
    if not session:
        return RedirectResponse(url="/login")

    notice = (await db.execute(select(BidNotice).where(BidNotice.id == notice_id))).scalar_one_or_none()
    if not notice:
        return HTMLResponse("标讯不存在", status_code=404)

    from models import Company
    company = (await db.execute(select(Company).limit(1))).scalar_one_or_none()

    assessment = assess_notice(notice, company)
    notice.assessment = assessment
    notice.status = "worth" if assessment["recommendation"] == "recommend" else (
        "not_worth" if assessment["recommendation"] == "not_recommend" else "assessing"
    )
    await db.commit()

    return RedirectResponse(url=f"/notices/{notice_id}", status_code=303)


@router.post("/{notice_id}/decide/{decision}")
async def notice_decide(
    request: Request,
    notice_id: str,
    decision: str,
    db: AsyncSession = Depends(get_db),
):
    """手动决策：bid=决定投标, no_bid=决定不投"""
    session = get_session(request)
    if not session:
        return RedirectResponse(url="/login")

    notice = (await db.execute(select(BidNotice).where(BidNotice.id == notice_id))).scalar_one_or_none()
    if not notice:
        return HTMLResponse("标讯不存在", status_code=404)

    if decision == "bid":
        notice.bid_decision = "bid"
        # 如果当前是 new/assessing/not_worth，手动决定投标后升级为 worth
        if notice.status in ["new", "assessing", "not_worth"]:
            notice.status = "worth"
    elif decision == "no_bid":
        notice.bid_decision = "no_bid"
        notice.status = "ignored"

    await db.commit()
    return RedirectResponse(url=f"/notices/{notice_id}", status_code=303)


@router.post("/{notice_id}/abandon")
async def notice_abandon(
    request: Request,
    notice_id: str,
    abandon_reason: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    """放弃投标：已决定投标的标讯主动放弃，需写明原因"""
    session = get_session(request)
    if not session:
        return RedirectResponse(url="/login")

    notice = (await db.execute(select(BidNotice).where(BidNotice.id == notice_id))).scalar_one_or_none()
    if not notice:
        return HTMLResponse("标讯不存在", status_code=404)

    notice.abandon_reason = abandon_reason.strip()
    notice.bid_decision = "no_bid"
    notice.status = "ignored"
    await db.commit()

    return RedirectResponse(url=f"/notices/{notice_id}", status_code=303)


@router.get("/export/excel")
async def notices_export_excel(
    request: Request,
    status: str = "",
    db: AsyncSession = Depends(get_db),
):
    """导出标讯为 Excel"""
    session = get_session(request)
    if not session:
        return RedirectResponse(url="/login")

    query = select(BidNotice)
    if status:
        query = query.where(BidNotice.status == status)
    notices_list = (await db.execute(
        query.order_by(BidNotice.created_at.desc())
    )).scalars().all()

    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "标讯列表"

    headers = ["标题", "来源网址", "发布日期", "报名截止", "投标截止", "开标时间",
               "预算(万元)", "标书费(元)", "保证金(万元)", "项目所在地",
               "联系人", "联系电话", "联系邮箱", "状态", "是否需要平台注册"]
    ws.append(headers)

    status_map = {"new": "新标讯", "assessing": "评估中", "worth": "值得投",
                  "not_worth": "不推荐", "registered": "已报名", "bidding": "投标中",
                  "completed": "已完成", "ignored": "已忽略"}

    for n in notices_list:
        ws.append([
            n.title,
            n.source_url or "",
            n.publishing_date.strftime("%Y-%m-%d") if n.publishing_date else "",
            n.registration_deadline.strftime("%Y-%m-%d %H:%M") if n.registration_deadline else "",
            n.bid_deadline.strftime("%Y-%m-%d %H:%M") if n.bid_deadline else "",
            n.bid_opening_date.strftime("%Y-%m-%d %H:%M") if n.bid_opening_date else "",
            n.budget_amount or "",
            n.bid_document_fee or "",
            n.bid_bond_amount or "",
            n.project_location or "",
            n.contact_person or "",
            n.contact_phone or "",
            n.contact_email or "",
            status_map.get(n.status, n.status),
            "是" if n.platform_registration_required else "否",
        ])

    output = BytesIO()
    wb.save(output)
    output.seek(0)

    from urllib.parse import quote
    filename = f"标讯导出_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.xlsx"
    encoded_filename = quote(filename)
    return Response(
        content=output.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"},
    )
