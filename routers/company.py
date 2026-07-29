"""公司资料管理"""
from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from models import Company
from auth import get_session
from templates_config import templates

router = APIRouter(prefix="/company", tags=["company"])


@router.get("", response_class=HTMLResponse)
async def company_edit_page(request: Request, db: AsyncSession = Depends(get_db)):
    session = get_session(request)
    if not session:
        return RedirectResponse(url="/login")

    result = await db.execute(select(Company).limit(1))
    company = result.scalar_one_or_none()

    return templates.TemplateResponse("company/edit.html", {
        "request": request,
        "session": session,
        "company": company,
    })


@router.post("", response_class=HTMLResponse)
async def company_save(
    request: Request,
    name: str = Form(""),
    credit_code: str = Form(""),
    legal_person: str = Form(""),
    address: str = Form(""),
    contact_phone: str = Form(""),
    contact_person: str = Form(""),
    contact_email: str = Form(""),
    bank_name: str = Form(""),
    account_no: str = Form(""),
    tax_no: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    session = get_session(request)
    if not session:
        return RedirectResponse(url="/login")

    result = await db.execute(select(Company).limit(1))
    company = result.scalar_one_or_none()

    bank_info = {
        "bank_name": bank_name,
        "account_no": account_no,
        "tax_no": tax_no,
    }

    if company:
        company.name = name
        company.credit_code = credit_code
        company.legal_person = legal_person
        company.address = address
        company.contact_phone = contact_phone
        company.contact_person = contact_person
        company.contact_email = contact_email
        company.bank_info = bank_info
    else:
        company = Company(
            name=name, credit_code=credit_code, legal_person=legal_person,
            address=address, contact_phone=contact_phone, contact_person=contact_person,
            contact_email=contact_email, bank_info=bank_info,
        )
        db.add(company)

    await db.commit()
    return RedirectResponse(url="/company", status_code=303)


@router.post("/qualifications/add", response_class=HTMLResponse)
async def add_qualification(
    request: Request,
    qual_name: str = Form(...),
    qual_level: str = Form(""),
    cert_no: str = Form(""),
    issuing_authority: str = Form(""),
    issue_date: str = Form(""),
    expiry_date: str = Form(""),
    is_permanent: bool = Form(False),
    db: AsyncSession = Depends(get_db),
):
    session = get_session(request)
    if not session:
        return RedirectResponse(url="/login")

    result = await db.execute(select(Company).limit(1))
    company = result.scalar_one_or_none()
    if not company:
        return RedirectResponse(url="/company", status_code=303)

    quals = list(company.qualifications or [])
    quals.append({
        "name": qual_name, "level": qual_level, "cert_no": cert_no,
        "issuing_authority": issuing_authority, "issue_date": issue_date,
        "expiry_date": expiry_date, "is_permanent": is_permanent,
    })
    company.qualifications = quals
    await db.commit()
    return RedirectResponse(url="/company", status_code=303)


@router.post("/qualifications/{idx}/delete")
async def delete_qualification(request: Request, idx: int, db: AsyncSession = Depends(get_db)):
    session = get_session(request)
    if not session:
        return RedirectResponse(url="/login")

    result = await db.execute(select(Company).limit(1))
    company = result.scalar_one_or_none()
    if company and company.qualifications and idx < len(company.qualifications):
        quals = list(company.qualifications)
        quals.pop(idx)
        company.qualifications = quals
        await db.commit()
    return RedirectResponse(url="/company", status_code=303)


@router.post("/performances/add", response_class=HTMLResponse)
async def add_performance(
    request: Request,
    project_name: str = Form(...),
    project_type: str = Form(""),
    contract_amount: float = Form(0),
    client_name: str = Form(""),
    contract_date: str = Form(""),
    description: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    session = get_session(request)
    if not session:
        return RedirectResponse(url="/login")

    result = await db.execute(select(Company).limit(1))
    company = result.scalar_one_or_none()
    if not company:
        return RedirectResponse(url="/company", status_code=303)

    perfs = list(company.performances or [])
    perfs.append({
        "project_name": project_name, "project_type": project_type,
        "contract_amount": contract_amount, "client_name": client_name,
        "contract_date": contract_date, "description": description,
    })
    company.performances = perfs
    await db.commit()
    return RedirectResponse(url="/company", status_code=303)


@router.post("/performances/{idx}/delete")
async def delete_performance(request: Request, idx: int, db: AsyncSession = Depends(get_db)):
    session = get_session(request)
    if not session:
        return RedirectResponse(url="/login")

    result = await db.execute(select(Company).limit(1))
    company = result.scalar_one_or_none()
    if company and company.performances and idx < len(company.performances):
        perfs = list(company.performances)
        perfs.pop(idx)
        company.performances = perfs
        await db.commit()
    return RedirectResponse(url="/company", status_code=303)


@router.post("/personnel/add", response_class=HTMLResponse)
async def add_person(
    request: Request,
    person_name: str = Form(...),
    position: str = Form(""),
    certifications: str = Form(""),
    person_phone: str = Form(""),
    person_email: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    session = get_session(request)
    if not session:
        return RedirectResponse(url="/login")

    result = await db.execute(select(Company).limit(1))
    company = result.scalar_one_or_none()
    if not company:
        return RedirectResponse(url="/company", status_code=303)

    people = list(company.personnel or [])
    people.append({
        "name": person_name, "position": position,
        "certifications": certifications,
        "phone": person_phone, "email": person_email,
    })
    company.personnel = people
    await db.commit()
    return RedirectResponse(url="/company", status_code=303)


@router.post("/personnel/{idx}/delete")
async def delete_person(request: Request, idx: int, db: AsyncSession = Depends(get_db)):
    session = get_session(request)
    if not session:
        return RedirectResponse(url="/login")

    result = await db.execute(select(Company).limit(1))
    company = result.scalar_one_or_none()
    if company and company.personnel and idx < len(company.personnel):
        people = list(company.personnel)
        people.pop(idx)
        company.personnel = people
        await db.commit()
    return RedirectResponse(url="/company", status_code=303)
