"""倒排计划生成器 — 当日→截止日正排分布"""
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from models import Task
from config import TASK_TEMPLATE


async def generate_schedule(
    notice,
    db: AsyncSession,
    target_deadline: datetime = None,
    days_before_map: dict = None,
) -> list[Task]:
    """
    从今日起，按任务工时权重比例正排分布至截止日期

    参数:
        notice: 标讯对象
        db: 数据库会话
        target_deadline: 目标截止日期（默认使用 notice.bid_deadline）
        days_before_map: 保留参数，新逻辑下不再使用

    返回: 创建的任务列表
    """
    deadline = target_deadline or notice.bid_deadline
    if not deadline:
        return []

    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    # 计算可用工作日总数
    total_wd = _count_working_days(today, deadline)
    total_est_hours = sum(tpl["est_hours"] for tpl in TASK_TEMPLATE)

    # 按 est_hours 比例分配：先取底，余数按小数部分大小补充分配
    raw = [total_wd * tpl["est_hours"] / total_est_hours for tpl in TASK_TEMPLATE]
    allocated = [max(0, int(d)) for d in raw]
    remainder = total_wd - sum(allocated)
    if remainder > 0:
        fracs = sorted(
            [(i, raw[i] - allocated[i]) for i in range(len(raw))],
            key=lambda x: x[1], reverse=True
        )
        for k in range(min(remainder, len(fracs))):
            allocated[fracs[k][0]] += 1

    # 从 today 起正排，连续排列
    tasks = []
    cursor = today

    for i, tpl in enumerate(TASK_TEMPLATE):
        duration = allocated[i]
        checklist = _get_checklist(tpl["task_type"])

        if cursor > deadline:
            cursor = deadline

        if duration == 0:
            # 无可用工作日：任务压缩到当天，不推进 cursor
            planned_start = cursor
            planned_end = cursor
        else:
            planned_start = cursor
            planned_end = _add_working_days(planned_start, duration - 1)
            if planned_end > deadline:
                planned_end = deadline
            # 下一个任务从本任务结束后一天开始
            cursor = _add_working_days(planned_end, 1)

        # 最后一个有天数的任务对齐到 deadline
        if i == len(TASK_TEMPLATE) - 1 and duration > 0:
            planned_end = deadline

        task = Task(
            notice_id=notice.id,
            title=tpl["title"],
            task_type=tpl["task_type"],
            assignee_id=None,
            status="todo",
            priority=tpl["priority"],
            planned_start=planned_start,
            planned_end=planned_end,
            sort_order=i,
            checklist=checklist,
        )
        db.add(task)
        tasks.append(task)

    await db.commit()
    return tasks


def preview_schedule(deadline: datetime, days_before_map: dict = None) -> list[dict]:
    """预览正排计划（不写入数据库），返回任务日期预览列表"""
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    total_wd = _count_working_days(today, deadline)
    total_est_hours = sum(tpl["est_hours"] for tpl in TASK_TEMPLATE)

    # 按比例分配：先取底，余数按小数部分大小补充分配
    raw = [total_wd * tpl["est_hours"] / total_est_hours for tpl in TASK_TEMPLATE]
    allocated = [max(0, int(d)) for d in raw]
    remainder = total_wd - sum(allocated)
    if remainder > 0:
        fracs = sorted(
            [(i, raw[i] - allocated[i]) for i in range(len(raw))],
            key=lambda x: x[1], reverse=True
        )
        for k in range(min(remainder, len(fracs))):
            allocated[fracs[k][0]] += 1

    # 正排
    result = []
    cursor = today

    for i, tpl in enumerate(TASK_TEMPLATE):
        duration = allocated[i]

        if cursor > deadline:
            cursor = deadline

        if duration == 0:
            planned_start = cursor
            planned_end = cursor
        else:
            planned_start = cursor
            planned_end = _add_working_days(planned_start, duration - 1)
            if planned_end > deadline:
                planned_end = deadline
            cursor = _add_working_days(planned_end, 1)

        if i == len(TASK_TEMPLATE) - 1 and duration > 0:
            planned_end = deadline

        result.append({
            "task_type": tpl["task_type"],
            "title": tpl["title"],
            "priority": tpl["priority"],
            "planned_start": planned_start,
            "planned_end": planned_end,
            "duration_days": duration,
        })

    return result


def _get_checklist(task_type: str) -> list:
    """获取预设的 checklist"""
    checklists = {
        "get_docs": [
            {"text": "查阅招标公告全文", "done": False},
            {"text": "下载招标文件", "done": False},
            {"text": "确认投标人资格要求", "done": False},
        ],
        "qualifications": [
            {"text": "整理资质证书复印件", "done": False},
            {"text": "撰写承诺函/声明函", "done": False},
            {"text": "法人授权委托书", "done": False},
        ],
        "certs": [
            {"text": "整理评分项证书", "done": False},
            {"text": "整理同类项目业绩证明", "done": False},
            {"text": "准备人员证书/社保", "done": False},
        ],
        "pricing": [
            {"text": "核算成本", "done": False},
            {"text": "确定投标报价", "done": False},
            {"text": "填写报价表", "done": False},
        ],
        "writing": [
            {"text": "编写技术方案", "done": False},
            {"text": "编写服务承诺", "done": False},
            {"text": "整理公司简介", "done": False},
        ],
        "format": [
            {"text": "检查页码/目录", "done": False},
            {"text": "统一字体格式", "done": False},
            {"text": "按要求装订", "done": False},
        ],
        "stamp": [
            {"text": "逐页盖章", "done": False},
            {"text": "法定代表人签字", "done": False},
            {"text": "密封投标文件", "done": False},
        ],
    }
    return checklists.get(task_type, [])


def _sub_working_days(dt: datetime, days: int) -> datetime:
    """减去工作日（排除周六日）—— 保留供其他模块使用"""
    result = dt
    while days > 0:
        result = result - timedelta(days=1)
        if result.weekday() < 5:
            days -= 1
    return result


def _add_working_days(dt: datetime, days: int) -> datetime:
    """向前加工作日（排除周六日）"""
    result = dt
    while days > 0:
        result = result + timedelta(days=1)
        if result.weekday() < 5:
            days -= 1
    return result


def _count_working_days(start: datetime, end: datetime) -> int:
    """计算两个日期之间的工作日天数（含起始日）"""
    if start >= end:
        return 1
    count = 0
    current = start
    while current <= end:
        if current.weekday() < 5:
            count += 1
        current += timedelta(days=1)
    return count
