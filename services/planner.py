"""倒排计划生成器"""
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
    根据目标截止日期，倒排生成任务列表

    参数:
        notice: 标讯对象
        db: 数据库会话
        target_deadline: 目标截止日期（默认使用 notice.bid_deadline）
        days_before_map: {task_type: days_before} 自定义每个任务的天数（可选）

    返回: 创建的任务列表
    """
    deadline = target_deadline or notice.bid_deadline
    if not deadline:
        return []

    tasks = []

    for i, tpl in enumerate(TASK_TEMPLATE):
        # 支持自定义天数
        days_before = days_before_map.get(tpl["task_type"], tpl["days_before"]) if days_before_map else tpl["days_before"]
        planned_end = _sub_working_days(deadline, days_before)
        planned_start = _sub_working_days(planned_end, max(tpl["est_hours"] // 8, 1))

        # 默认 checklist
        checklist = _get_checklist(tpl["task_type"])

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
    """预览倒排计划（不写入数据库），返回任务日期预览列表"""
    result = []
    for tpl in TASK_TEMPLATE:
        days_before = days_before_map.get(tpl["task_type"], tpl["days_before"]) if days_before_map else tpl["days_before"]
        planned_end = _sub_working_days(deadline, days_before)
        planned_start = _sub_working_days(planned_end, max(tpl["est_hours"] // 8, 1))
        result.append({
            "task_type": tpl["task_type"],
            "title": tpl["title"],
            "days_before": days_before,
            "preview_date": planned_end,
            "priority": tpl["priority"],
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
    """减去工作日（排除周六日）"""
    result = dt
    while days > 0:
        result = result - timedelta(days=1)
        if result.weekday() < 5:  # Mon-Fri
            days -= 1
    return result
