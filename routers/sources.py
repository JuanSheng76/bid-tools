"""标讯来源管理"""
from datetime import datetime
from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from models import BidSource
from auth import get_session
from services.scraper import scrape_source
from templates_config import templates

router = APIRouter(prefix="/sources", tags=["sources"])


@router.get("", response_class=HTMLResponse)
async def source_list(request: Request, db: AsyncSession = Depends(get_db)):
    session = get_session(request)
    if not session:
        return RedirectResponse(url="/login")

    sources = (await db.execute(select(BidSource).order_by(BidSource.created_at.desc()))).scalars().all()
    return templates.TemplateResponse("sources/list.html", {
        "request": request,
        "session": session,
        "sources": sources,
    })


@router.post("", response_class=HTMLResponse)
async def source_create(
    request: Request,
    name: str = Form(...),
    url: str = Form(...),
    website_type: str = Form("other"),
    region: str = Form(""),
    is_active: bool = Form(True),
    scrape_interval_minutes: int = Form(60),
    requires_login: bool = Form(False),
    login_username: str = Form(""),
    login_password: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    session = get_session(request)
    if not session:
        return RedirectResponse(url="/login")

    source = BidSource(
        name=name, url=url, website_type=website_type, region=region,
        is_active=is_active, scrape_interval_minutes=scrape_interval_minutes,
        requires_login=requires_login, login_username=login_username,
        login_password=login_password,
    )
    db.add(source)
    await db.commit()
    return RedirectResponse(url="/sources", status_code=303)


@router.get("/{source_id}/edit", response_class=HTMLResponse)
async def source_edit_page(request: Request, source_id: str, db: AsyncSession = Depends(get_db)):
    session = get_session(request)
    if not session:
        return RedirectResponse(url="/login")

    source = (await db.execute(select(BidSource).where(BidSource.id == source_id))).scalar_one_or_none()
    if not source:
        return HTMLResponse("来源不存在", status_code=404)

    sources = (await db.execute(select(BidSource).order_by(BidSource.created_at.desc()))).scalars().all()
    return templates.TemplateResponse("sources/list.html", {
        "request": request,
        "session": session,
        "sources": sources,
        "edit_source": source,
    })


@router.post("/{source_id}/edit")
async def source_update(
    request: Request,
    source_id: str,
    name: str = Form(...),
    url: str = Form(...),
    website_type: str = Form("other"),
    region: str = Form(""),
    is_active: bool = Form(True),
    scrape_interval_minutes: int = Form(60),
    requires_login: bool = Form(False),
    login_username: str = Form(""),
    login_password: str = Form(""),
    scrape_config: str = Form("{}"),
    db: AsyncSession = Depends(get_db),
):
    session = get_session(request)
    if not session:
        return RedirectResponse(url="/login")

    source = (await db.execute(select(BidSource).where(BidSource.id == source_id))).scalar_one_or_none()
    if source:
        source.name = name
        source.url = url
        source.website_type = website_type
        source.region = region
        source.is_active = is_active
        source.scrape_interval_minutes = scrape_interval_minutes
        source.requires_login = requires_login
        source.login_username = login_username
        source.login_password = login_password
        import json
        try:
            source.scrape_config = json.loads(scrape_config)
        except json.JSONDecodeError:
            pass
        await db.commit()
    return RedirectResponse(url="/sources", status_code=303)


@router.post("/{source_id}/delete")
async def source_delete(request: Request, source_id: str, db: AsyncSession = Depends(get_db)):
    session = get_session(request)
    if not session:
        return RedirectResponse(url="/login")

    source = (await db.execute(select(BidSource).where(BidSource.id == source_id))).scalar_one_or_none()
    if source:
        await db.delete(source)
        await db.commit()
    return RedirectResponse(url="/sources", status_code=303)


@router.post("/{source_id}/scrape")
async def source_scrape(request: Request, source_id: str, db: AsyncSession = Depends(get_db)):
    """手动触发爬取"""
    session = get_session(request)
    if not session:
        return RedirectResponse(url="/login")

    source = (await db.execute(select(BidSource).where(BidSource.id == source_id))).scalar_one_or_none()
    if source:
        new_count = await scrape_source(source, db)
        source.last_scraped_at = datetime.utcnow()
        source.last_status = "success" if new_count >= 0 else "failed"
        await db.commit()
    return RedirectResponse(url="/sources", status_code=303)
