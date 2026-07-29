"""报名管理"""
from datetime import datetime
from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from models import Registration, BidNotice, Company
from auth import get_session
from templates_config import templates

router = APIRouter(prefix="/registrations", tags=["registrations"])


@router.get("", response_class=HTMLResponse)
async def registration_list(
    request: Request,
    notice_id: str = "",
    db: AsyncSession = Depends(get_db),
):
    session = get_session(request)
    if not session:
        return RedirectResponse(url="/login")

    query = select(Registration)
    if notice_id:
        query = query.where(Registration.notice_id == notice_id)
    registrations = (await db.execute(
        query.order_by(Registration.created_at.desc())
    )).scalars().all()

    # 标讯列表（用于新建报名选择）
    notices = (await db.execute(
        select(BidNotice).where(
            BidNotice.status.in_(["worth", "registered", "bidding"])
        ).order_by(BidNotice.created_at.desc()).limit(50)
    )).scalars().all()

    # 公司资料（用于自动填表）
    company = (await db.execute(select(Company).limit(1))).scalar_one_or_none()

    # 如果有 notice_id，查对应标讯
    notice = None
    if notice_id:
        notice = (await db.execute(
            select(BidNotice).where(BidNotice.id == notice_id)
        )).scalar_one_or_none()

    return templates.TemplateResponse("registrations/list.html", {
        "request": request,
        "session": session,
        "registrations": registrations,
        "notices": notices,
        "company": company,
        "view_notice": notice,
        "filter_notice_id": notice_id,
    })


@router.post("", response_class=HTMLResponse)
async def registration_create(
    request: Request,
    notice_id: str = Form(...),
    platform_name: str = Form(""),
    platform_account: str = Form(""),
    form_data_json: str = Form("{}"),
    notes: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    session = get_session(request)
    if not session:
        return RedirectResponse(url="/login")

    import json
    try:
        form_data = json.loads(form_data_json)
    except json.JSONDecodeError:
        form_data = {}

    reg = Registration(
        notice_id=notice_id,
        platform_name=platform_name,
        platform_account=platform_account,
        form_data=form_data,
        notes=notes,
        status="pending",
    )
    db.add(reg)

    # 更新标讯状态为已报名
    notice = (await db.execute(
        select(BidNotice).where(BidNotice.id == notice_id)
    )).scalar_one_or_none()
    if notice and notice.status in ["worth"]:
        notice.status = "registered"
    await db.commit()

    return RedirectResponse(url=f"/registrations?notice_id={notice_id}", status_code=303)


@router.post("/{reg_id}/status/{new_status}")
async def registration_update_status(
    request: Request,
    reg_id: str,
    new_status: str,
    db: AsyncSession = Depends(get_db),
):
    session = get_session(request)
    if not session:
        return RedirectResponse(url="/login")

    reg = (await db.execute(
        select(Registration).where(Registration.id == reg_id)
    )).scalar_one_or_none()
    if reg:
        reg.status = new_status
        if new_status == "submitted":
            reg.submitted_at = datetime.utcnow()
        await db.commit()

    return RedirectResponse(
        url=f"/registrations?notice_id={reg.notice_id}", status_code=303
    )


@router.post("/{reg_id}/payment/{p_status}")
async def registration_update_payment(
    request: Request,
    reg_id: str,
    p_status: str,
    amount: float = 0,
    db: AsyncSession = Depends(get_db),
):
    session = get_session(request)
    if not session:
        return RedirectResponse(url="/login")

    reg = (await db.execute(
        select(Registration).where(Registration.id == reg_id)
    )).scalar_one_or_none()
    if reg:
        reg.payment_status = p_status
        if amount > 0:
            reg.payment_amount = amount
        await db.commit()

    return RedirectResponse(
        url=f"/registrations?notice_id={reg.notice_id}", status_code=303
    )


@router.post("/{reg_id}/delete")
async def registration_delete(
    request: Request,
    reg_id: str,
    db: AsyncSession = Depends(get_db),
):
    session = get_session(request)
    if not session:
        return RedirectResponse(url="/login")

    reg = (await db.execute(
        select(Registration).where(Registration.id == reg_id)
    )).scalar_one_or_none()
    notice_id = reg.notice_id if reg else ""
    if reg:
        await db.delete(reg)
        await db.commit()

    return RedirectResponse(
        url=f"/registrations?notice_id={notice_id}", status_code=303
    )


@router.get("/auto-fill/{notice_id}", response_class=HTMLResponse)
async def registration_auto_fill(
    request: Request,
    notice_id: str,
    db: AsyncSession = Depends(get_db),
):
    """返回自动填充的报名表单 JSON（HTMX 局部刷新）"""
    session = get_session(request)
    if not session:
        return HTMLResponse("未登录", status_code=401)

    notice = (await db.execute(
        select(BidNotice).where(BidNotice.id == notice_id)
    )).scalar_one_or_none()

    company = (await db.execute(select(Company).limit(1))).scalar_one_or_none()

    if not company:
        return HTMLResponse('<span class="text-danger">请先完善公司资料</span>')

    # 根据公司资料自动生成报名表单数据
    import json
    auto_data = {
        "company_name": company.name,
        "credit_code": company.credit_code,
        "legal_person": company.legal_person,
        "address": company.address,
        "contact_person": company.contact_person,
        "contact_phone": company.contact_phone,
        "contact_email": company.contact_email,
        "bank_name": company.bank_info.get("bank_name", "") if company.bank_info else "",
        "account_no": company.bank_info.get("account_no", "") if company.bank_info else "",
        "tax_no": company.bank_info.get("tax_no", "") if company.bank_info else "",
    }

    # 构建表单 HTML
    rows = ""
    for key, value in auto_data.items():
        label_map = {
            "company_name": "公司名称", "credit_code": "统一社会信用代码",
            "legal_person": "法定代表人", "address": "注册地址",
            "contact_person": "联系人", "contact_phone": "联系电话",
            "contact_email": "联系邮箱", "bank_name": "开户行",
            "account_no": "银行账号", "tax_no": "纳税人识别号",
        }
        label = label_map.get(key, key)
        rows += f'<div class="form-group"><label>{label}</label><input type="text" name="fld_{key}" value="{value}"></div>\n'

    html = f'<div class="grid-2">{rows}</div>'
    html += f'<div class="text-secondary" style="font-size:12px;">✅ 已从公司资料自动填充，请核对后提交</div>'
    return HTMLResponse(html)
