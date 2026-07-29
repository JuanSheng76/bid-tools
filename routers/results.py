"""开标/结果管理"""
from datetime import datetime
from fastapi import APIRouter, Request, Form, Depends
from io import BytesIO
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from templates_config import templates
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from models import BidResult, BidNotice
from auth import get_session

router = APIRouter(prefix="/results", tags=["results"])


def parse_date(s: str) -> datetime | None:
    if not s or not s.strip():
        return None
    for fmt in ["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d"]:
        try:
            return datetime.strptime(s.strip(), fmt)
        except ValueError:
            continue
    return None


@router.get("", response_class=HTMLResponse)
async def result_list(
    request: Request,
    result_filter: str = "",
    page: int = 1,
    db: AsyncSession = Depends(get_db),
):
    session = get_session(request)
    if not session:
        return RedirectResponse(url="/login")

    query = select(BidResult)
    count_query = select(func.count(BidResult.id))

    if result_filter:
        query = query.where(BidResult.result == result_filter)
        count_query = count_query.where(BidResult.result == result_filter)

    total = (await db.execute(count_query)).scalar() or 0
    page_size = 20
    offset = (page - 1) * page_size
    total_pages = max(1, (total + page_size - 1) // page_size)

    results = (await db.execute(
        query.order_by(BidResult.created_at.desc()).offset(offset).limit(page_size)
    )).scalars().all()

    # 统计数据
    total_wins = (await db.execute(
        select(func.count()).where(BidResult.result == "won")
    )).scalar() or 0
    total_all = (await db.execute(
        select(func.count()).where(BidResult.result.in_(["won", "lost"]))
    )).scalar() or 0
    win_rate = round(total_wins / total_all * 100, 1) if total_all > 0 else 0

    # 即将到期的合同
    from datetime import timedelta
    soon = datetime.utcnow() + timedelta(days=30)
    expiring = (await db.execute(
        select(BidResult).where(
            BidResult.contract_expiry_date.isnot(None),
            BidResult.contract_expiry_date <= soon,
            BidResult.contract_expiry_date >= datetime.utcnow(),
            BidResult.result == "won"
        )
    )).scalars().all()

    # 所有标讯（用于新建结果选择）
    notices = (await db.execute(
        select(BidNotice).order_by(BidNotice.created_at.desc()).limit(100)
    )).scalars().all()

    return templates.TemplateResponse("results/list.html", {
        "request": request,
        "session": session,
        "results": results,
        "result_filter": result_filter,
        "page": page,
        "total": total,
        "total_pages": total_pages,
        "total_wins": total_wins,
        "win_rate": win_rate,
        "expiring": expiring,
        "notices": notices,
    })


@router.post("", response_class=HTMLResponse)
async def result_create(
    request: Request,
    notice_id: str = Form(...),
    opening_date: str = Form(""),
    participant_count: int = Form(None),
    our_quote: float = Form(None),
    result: str = Form(""),
    winning_company: str = Form(""),
    winning_amount: float = Form(None),
    result_url: str = Form(""),
    contract_signed_date: str = Form(""),
    contract_expiry_date: str = Form(""),
    contract_amount: float = Form(None),
    loss_reason: str = Form(""),
    notes: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    session = get_session(request)
    if not session:
        return RedirectResponse(url="/login")

    # 检查是否已有结果
    existing = (await db.execute(
        select(BidResult).where(BidResult.notice_id == notice_id)
    )).scalar_one_or_none()

    # 解析竞对报价
    competitor_quotes = []
    comp_companies = request._form.getlist("comp_company")
    comp_quotes = request._form.getlist("comp_quote")
    for i in range(min(len(comp_companies), len(comp_quotes))):
        if comp_companies[i] and comp_quotes[i]:
            try:
                competitor_quotes.append({
                    "company": comp_companies[i],
                    "quote": float(comp_quotes[i]),
                })
            except ValueError:
                pass

    if existing:
        existing.opening_date = parse_date(opening_date)
        existing.participant_count = participant_count
        existing.our_quote = our_quote
        existing.competitor_quotes = competitor_quotes
        existing.result = result
        existing.winning_company = winning_company
        existing.winning_amount = winning_amount
        existing.result_url = result_url
        existing.contract_signed_date = parse_date(contract_signed_date)
        existing.contract_expiry_date = parse_date(contract_expiry_date)
        existing.contract_amount = contract_amount
        existing.loss_reason = loss_reason
        existing.notes = notes
    else:
        br = BidResult(
            notice_id=notice_id, opening_date=parse_date(opening_date),
            participant_count=participant_count, our_quote=our_quote,
            competitor_quotes=competitor_quotes, result=result,
            winning_company=winning_company, winning_amount=winning_amount,
            result_url=result_url,
            contract_signed_date=parse_date(contract_signed_date),
            contract_expiry_date=parse_date(contract_expiry_date),
            contract_amount=contract_amount, loss_reason=loss_reason, notes=notes,
        )
        db.add(br)

    # 更新标讯状态
    notice = (await db.execute(select(BidNotice).where(BidNotice.id == notice_id))).scalar_one_or_none()
    if notice:
        notice.status = "completed"
    await db.commit()

    return RedirectResponse(url="/results", status_code=303)


@router.post("/{result_id}/delete")
async def result_delete(request: Request, result_id: str, db: AsyncSession = Depends(get_db)):
    session = get_session(request)
    if not session:
        return RedirectResponse(url="/login")

    br = (await db.execute(select(BidResult).where(BidResult.id == result_id))).scalar_one_or_none()
    if br:
        await db.delete(br)
        await db.commit()
    return RedirectResponse(url="/results", status_code=303)


@router.get("/export/excel")
async def results_export_excel(
    request: Request,
    result_filter: str = "",
    db: AsyncSession = Depends(get_db),
):
    """导出结果为 Excel"""
    session = get_session(request)
    if not session:
        return RedirectResponse(url="/login")

    query = select(BidResult)
    if result_filter:
        query = query.where(BidResult.result == result_filter)
    results_list = (await db.execute(
        query.order_by(BidResult.created_at.desc())
    )).scalars().all()

    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "投标结果"

    headers = ["标讯", "开标日期", "参与家数", "我方报价(万元)", "结果",
               "中标单位", "中标金额(万元)", "合同签订日期", "合同到期日期",
               "合同金额(万元)", "未中标原因", "备注"]
    ws.append(headers)

    result_map = {"won": "中标", "lost": "未中标", "rejected": "废标", "cancelled": "流标"}

    for r in results_list:
        ws.append([
            r.notice.title[:60] if r.notice else "-",
            r.opening_date.strftime("%Y-%m-%d") if r.opening_date else "",
            r.participant_count or "",
            r.our_quote or "",
            result_map.get(r.result, r.result),
            r.winning_company or "",
            r.winning_amount or "",
            r.contract_signed_date.strftime("%Y-%m-%d") if r.contract_signed_date else "",
            r.contract_expiry_date.strftime("%Y-%m-%d") if r.contract_expiry_date else "",
            r.contract_amount or "",
            r.loss_reason or "",
            r.notes or "",
        ])

    output = BytesIO()
    wb.save(output)
    output.seek(0)

    from urllib.parse import quote
    filename = f"投标结果导出_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.xlsx"
    encoded_filename = quote(filename)
    return Response(
        content=output.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"},
    )
