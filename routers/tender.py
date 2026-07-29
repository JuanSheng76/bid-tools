"""招标文件上传/解析/推荐路由"""
import asyncio
import os
import time
import traceback
import uuid
from datetime import datetime

from fastapi import APIRouter, Request, Form, Depends, File, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from config import BASE_DIR
from database import get_db
from models import BidNotice, Company
from auth import get_session
from templates_config import templates
from services.tender_parser import (
    parse_tender_docx,
    parse_tender_pdf,
    enrich_task_checklists,
)

router = APIRouter(prefix="/tender", tags=["tender"])

UPLOAD_DIR = os.path.join(BASE_DIR, "uploads", "tenders")
ALLOWED_EXTENSIONS = {".docx", ".pdf"}


def _ensure_upload_dir(notice_id: str) -> str:
    """确保上传目录存在，返回 notice 专属目录路径"""
    notice_dir = os.path.join(UPLOAD_DIR, notice_id)
    os.makedirs(notice_dir, exist_ok=True)
    return notice_dir


@router.post("/upload/{notice_id}")
async def tender_upload(
    request: Request,
    notice_id: str,
    tender_file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """上传招标文件并触发解析"""
    session = get_session(request)
    if not session:
        return RedirectResponse(url="/login")

    # 验证标讯存在 + bid_decision
    notice = (await db.execute(
        select(BidNotice).where(BidNotice.id == notice_id)
    )).scalar_one_or_none()

    if not notice:
        return HTMLResponse("标讯不存在", status_code=404)

    # 验证文件扩展名
    _, ext = os.path.splitext(tender_file.filename or "")
    if ext.lower() not in ALLOWED_EXTENSIONS:
        return HTMLResponse("仅支持 .docx 和 .pdf 格式", status_code=400)

    # 保存文件
    notice_dir = _ensure_upload_dir(notice_id)
    safe_filename = f"{uuid.uuid4().hex}_{tender_file.filename}"
    file_path = os.path.join(notice_dir, safe_filename)

    content = await tender_file.read()
    with open(file_path, "wb") as f:
        f.write(content)

    # 获取公司资料（用于匹配推荐）
    company = (await db.execute(select(Company).limit(1))).scalar_one_or_none()

    # 根据扩展名调用解析（放入线程池避免阻塞事件循环）
    print(f"[tender] 开始解析: {tender_file.filename} ({os.path.getsize(file_path)} bytes)", flush=True)
    t0 = time.time()
    try:
        if ext.lower() == ".docx":
            result = await asyncio.to_thread(
                parse_tender_docx, file_path, tender_file.filename, company
            )
        else:
            result = await asyncio.to_thread(
                parse_tender_pdf, file_path, tender_file.filename, company
            )
        elapsed = time.time() - t0
        print(f"[tender] 解析完成: {tender_file.filename} 耗时 {elapsed:.1f}s", flush=True)
    except Exception as e:
        elapsed = time.time() - t0
        print(f"[tender] 解析失败: {tender_file.filename} 耗时 {elapsed:.1f}s", flush=True)
        traceback.print_exc()
        tb = traceback.format_exc()
        return HTMLResponse(
            f'<div class="card" style="border-left:4px solid var(--danger);margin:0;">'
            f'<h4>❌ 解析失败</h4>'
            f'<p><strong>错误类型：</strong>{type(e).__name__}</p>'
            f'<p><strong>错误信息：</strong>{e}</p>'
            f'<details style="margin-top:8px;"><summary style="cursor:pointer;font-size:12px;color:var(--text-muted);">完整 Traceback</summary>'
            f'<pre style="font-size:11px;max-height:300px;overflow:auto;background:#1e1e1e;color:#d4d4d4;padding:10px;border-radius:6px;margin-top:6px;">{tb}</pre>'
            f'</details></div>',
            status_code=500)

    # 写入 notice
    notice.tender_analysis = result
    await db.commit()

    # HTMX 请求：直接返回分析卡片 HTML，页面不跳转
    if request.headers.get("HX-Request"):
        try:
            # 重新加载 notice（预加载 tasks 用于模板）
            await db.refresh(notice)
            notice_with_tasks = (await db.execute(
                select(BidNotice).where(BidNotice.id == notice_id).options(
                    selectinload(BidNotice.tasks)
                )
            )).scalar_one_or_none()
            return templates.TemplateResponse("tender/analysis_card.html", {
                "request": request,
                "session": get_session(request),
                "notice": notice_with_tasks,
                "analysis": notice.tender_analysis,
            })
        except Exception as e:
            traceback.print_exc()
            tb = traceback.format_exc()
            return HTMLResponse(
                f'<div class="card" style="border-left:4px solid var(--danger);margin:0;">'
                f'<h4>❌ 模板渲染失败</h4>'
                f'<p><strong>{type(e).__name__}:</strong> {e}</p>'
                f'<pre style="font-size:11px;max-height:200px;overflow:auto;background:#1e1e1e;color:#d4d4d4;padding:10px;border-radius:6px;">{tb}</pre>'
                f'</div>',
                status_code=500)

    return RedirectResponse(url=f"/notices/{notice_id}#tender-analysis", status_code=303)


@router.get("/analysis/{notice_id}", response_class=HTMLResponse)
async def tender_analysis_card(
    request: Request,
    notice_id: str,
    db: AsyncSession = Depends(get_db),
):
    """HTMX 局部加载：返回分析卡片 HTML 片段"""
    session = get_session(request)
    if not session:
        return HTMLResponse('<div class="card">请先登录</div>')

    notice = (await db.execute(
        select(BidNotice).where(BidNotice.id == notice_id).options(
            selectinload(BidNotice.tasks)
        )
    )).scalar_one_or_none()

    if not notice or not notice.tender_analysis:
        return HTMLResponse("")

    return templates.TemplateResponse("tender/analysis_card.html", {
        "request": request,
        "session": session,
        "notice": notice,
        "analysis": notice.tender_analysis,
    })


@router.get("/recommend/{notice_id}", response_class=HTMLResponse)
async def tender_recommend(
    request: Request,
    notice_id: str,
    db: AsyncSession = Depends(get_db),
):
    """推荐选择页（完整页面）"""
    session = get_session(request)
    if not session:
        return RedirectResponse(url="/login")

    notice = (await db.execute(
        select(BidNotice).where(BidNotice.id == notice_id)
    )).scalar_one_or_none()

    if not notice:
        return HTMLResponse("标讯不存在", status_code=404)

    if not notice.tender_analysis:
        return RedirectResponse(url=f"/notices/{notice_id}", status_code=303)

    return templates.TemplateResponse("tender/recommend.html", {
        "request": request,
        "session": session,
        "notice": notice,
        "analysis": notice.tender_analysis,
    })


@router.post("/enrich-tasks/{notice_id}")
async def tender_enrich_tasks(
    request: Request,
    notice_id: str,
    db: AsyncSession = Depends(get_db),
):
    """将招标文件注意事项同步到任务 checklist"""
    session = get_session(request)
    if not session:
        return RedirectResponse(url="/login")

    notice = (await db.execute(
        select(BidNotice).where(BidNotice.id == notice_id)
    )).scalar_one_or_none()

    if not notice:
        return HTMLResponse("标讯不存在", status_code=404)

    if not notice.tender_analysis:
        return RedirectResponse(url=f"/notices/{notice_id}", status_code=303)

    important_notes = notice.tender_analysis.get("important_notes", [])
    if important_notes:
        added = await enrich_task_checklists(notice_id, db, important_notes)
        if added > 0:
            # 刷新 notice 以获取更新后的任务
            await db.refresh(notice)

    return RedirectResponse(url=f"/notices/{notice_id}#tender-analysis", status_code=303)
