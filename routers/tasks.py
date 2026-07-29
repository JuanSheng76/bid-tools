"""任务管理 + 倒排计划"""
from datetime import datetime, timedelta
from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from models import Task, BidNotice, User
from auth import get_session
from services.planner import generate_schedule, preview_schedule
from templates_config import templates
import config

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("", response_class=HTMLResponse)
async def task_kanban(
    request: Request,
    notice_id: str = "",
    assignee_id: str = "",
    mine: bool = False,
    overdue: bool = False,
    db: AsyncSession = Depends(get_db),
):
    session = get_session(request)
    if not session:
        return RedirectResponse(url="/login")

    # 所有标讯（用于筛选下拉）
    notices = (await db.execute(
        select(BidNotice).order_by(BidNotice.created_at.desc()).limit(50)
    )).scalars().all()

    # 所有用户
    users = (await db.execute(select(User).where(User.is_active == True))).scalars().all()

    # 任务查询（预加载关联的 notice 和 assignee）
    query = select(Task).options(selectinload(Task.notice), selectinload(Task.assignee))
    if notice_id:
        query = query.where(Task.notice_id == notice_id)
    if assignee_id:
        query = query.where(Task.assignee_id == assignee_id)
    if mine:
        query = query.where(Task.assignee_id == session["user_id"])
    if overdue:
        query = query.where(
            Task.status != "done",
            Task.planned_end.is_not(None),
            Task.planned_end < datetime.utcnow(),
        )

    tasks = (await db.execute(
        query.order_by(Task.planned_end.asc(), Task.sort_order)
    )).scalars().all()

    # 按状态分组
    todo = [t for t in tasks if t.status == "todo"]
    in_progress = [t for t in tasks if t.status == "in_progress"]
    done = [t for t in tasks if t.status == "done"]

    return templates.TemplateResponse("tasks/kanban.html", {
        "request": request,
        "session": session,
        "todo": todo,
        "in_progress": in_progress,
        "done": done,
        "notices": notices,
        "users": users,
        "filter_notice_id": notice_id,
        "filter_assignee_id": assignee_id,
        "filter_mine": mine,
        "filter_overdue": overdue,
    })


@router.get("/{task_id}", response_class=HTMLResponse)
async def task_detail(request: Request, task_id: str, db: AsyncSession = Depends(get_db)):
    session = get_session(request)
    if not session:
        return RedirectResponse(url="/login")

    task = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
    if not task:
        return HTMLResponse("任务不存在", status_code=404)

    users = (await db.execute(select(User).where(User.is_active == True))).scalars().all()
    notice = (await db.execute(select(BidNotice).where(BidNotice.id == task.notice_id))).scalar_one_or_none()

    return templates.TemplateResponse("tasks/detail.html", {
        "request": request,
        "session": session,
        "task": task,
        "notice": notice,
        "users": users,
    })


@router.post("/{task_id}/status")
async def task_update_status(
    request: Request,
    task_id: str,
    status: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """更新任务状态（看板拖拽用）"""
    session = get_session(request)
    if not session:
        return JSONResponse({"error": "未登录"}, status_code=401)

    task = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
    if task:
        if status not in {"todo", "in_progress", "done"}:
            return JSONResponse({"error": "无效状态"}, status_code=400)
        task.status = status
        if status == "done":
            task.completed_at = datetime.utcnow()
        else:
            task.completed_at = None
        await db.commit()
        return JSONResponse({
            "success": True,
            "status": status,
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        })
    return JSONResponse({"error": "任务不存在"}, status_code=404)


@router.post("/{task_id}/assign")
async def task_assign(
    request: Request,
    task_id: str,
    assignee_id: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    session = get_session(request)
    if not session:
        return RedirectResponse(url="/login")

    task = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
    if task:
        task.assignee_id = assignee_id if assignee_id else None
        await db.commit()

    # HTMX 响应：返回更新后的 assignee 显示
    if task and task.assignee:
        return HTMLResponse(task.assignee.full_name)
    return HTMLResponse("未分配")


@router.post("/{task_id}/checklist")
async def task_checklist_update(
    request: Request,
    task_id: str,
    db: AsyncSession = Depends(get_db),
):
    """更新 checklist"""
    session = get_session(request)
    if not session:
        return JSONResponse({"error": "未登录"}, status_code=401)

    import json
    body = await request.body()
    data = json.loads(body)
    checklist = data.get("checklist", [])

    task = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
    if task:
        task.checklist = checklist
        await db.commit()
        return JSONResponse({"success": True})
    return JSONResponse({"error": "任务不存在"}, status_code=404)


@router.post("/{task_id}/edit")
async def task_edit(
    request: Request,
    task_id: str,
    title: str = Form(...),
    description: str = Form(""),
    priority: str = Form("medium"),
    planned_start: str = Form(""),
    planned_end: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    session = get_session(request)
    if not session:
        return RedirectResponse(url="/login")

    task = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
    if task:
        task.title = title
        task.description = description
        task.priority = priority
        if planned_start:
            task.planned_start = datetime.fromisoformat(planned_start)
        if planned_end:
            task.planned_end = datetime.fromisoformat(planned_end)
        await db.commit()
    return RedirectResponse(url=f"/tasks/{task_id}", status_code=303)


@router.get("/generate/{notice_id}", response_class=HTMLResponse)
async def task_generate_form(request: Request, notice_id: str, db: AsyncSession = Depends(get_db)):
    """倒排计划设置页面（GET：显示表单）"""
    session = get_session(request)
    if not session:
        return RedirectResponse(url="/login")

    notice = (await db.execute(select(BidNotice).where(BidNotice.id == notice_id))).scalar_one_or_none()
    if not notice:
        return HTMLResponse("标讯不存在", status_code=404)

    # 检查已有任务数量
    from sqlalchemy import func
    existing_tasks = (await db.execute(
        select(func.count()).where(Task.notice_id == notice_id)
    )).scalar() or 0

    # 目标截止日期
    deadline = notice.bid_deadline or datetime.utcnow()
    target_deadline = deadline.strftime('%Y-%m-%dT%H:%M')

    # 预览倒排计划（默认天数）
    task_templates = preview_schedule(deadline)

    return templates.TemplateResponse("tasks/generate.html", {
        "request": request,
        "session": session,
        "notice": notice,
        "target_deadline": target_deadline,
        "task_templates": task_templates,
        "existing_tasks": existing_tasks,
    })


@router.post("/generate/{notice_id}")
async def task_generate_execute(
    request: Request,
    notice_id: str,
    db: AsyncSession = Depends(get_db),
):
    """倒排计划生成（POST：执行生成）"""
    session = get_session(request)
    if not session:
        return RedirectResponse(url="/login")

    notice = (await db.execute(select(BidNotice).where(BidNotice.id == notice_id))).scalar_one_or_none()
    if not notice:
        return HTMLResponse("标讯不存在", status_code=404)

    # 解析表单数据
    form = await request.form()
    target_deadline_str = form.get("target_deadline", "")
    target_deadline = datetime.fromisoformat(target_deadline_str) if target_deadline_str else None
    replace = form.get("replace", "0") == "1"

    if not target_deadline:
        return HTMLResponse("请设置目标截止日期", status_code=400)

    # 替换模式：删除已有任务
    if replace:
        existing = (await db.execute(
            select(Task).where(Task.notice_id == notice_id)
        )).scalars().all()
        for t in existing:
            await db.delete(t)
        await db.flush()

    # 收集自定义天数
    days_before_map = {}
    for tpl in config.TASK_TEMPLATE:
        task_type = tpl["task_type"]
        days_str = form.get(f"days_before_{task_type}", "")
        if days_str:
            try:
                days_before_map[task_type] = int(days_str)
            except ValueError:
                pass

    tasks = await generate_schedule(notice, db, target_deadline=target_deadline, days_before_map=days_before_map)

    # 更新标讯状态
    if notice.status in ["new", "assessing", "worth"]:
        notice.status = "bidding"
        await db.commit()

    return RedirectResponse(url=f"/tasks?notice_id={notice_id}", status_code=303)
