"""共享的 Jinja2 Templates 配置"""
from datetime import datetime
from fastapi.templating import Jinja2Templates


class TemplatesWithNow(Jinja2Templates):
    """自动注入 now 变量到所有模板上下文，兼容 Starlette 1.x API"""

    def TemplateResponse(self, name: str, context: dict = None, **kwargs):
        if context is None:
            context = {}
        context.setdefault("now", datetime.utcnow())

        # Starlette >= 1.0: TemplateResponse(request, name, context, ...)
        #   request 始终在 context 中，提取出来传给父类
        request = context.get("request")
        return super().TemplateResponse(request, name, context, **kwargs)


templates = TemplatesWithNow(directory="templates")

# ====== 自定义 Jinja2 过滤器 ======

# 低饱和调色板：按 notice_id 的 hash 取模，同一标讯始终同色。
# 用于任务卡片顶部的标讯信息，保持区分度但避免抢夺任务标题的视觉焦点。
_NOTICE_COLORS = [
    ("#52718d", "#edf2f6"),  # 灰蓝
    ("#557766", "#eef4f1"),  # 灰绿
    ("#8a7049", "#f5f2eb"),  # 沙金
    ("#6e6687", "#f1eff5"),  # 灰紫
    ("#52777a", "#eef4f4"),  # 灰青
    ("#856879", "#f5f0f3"),  # 灰粉
    ("#7c744f", "#f4f3ed"),  # 卡其
    ("#5e7390", "#eef2f7"),  # 靛灰
    ("#6f7855", "#f2f4ed"),  # 橄榄灰
    ("#8a6266", "#f6eff0"),  # 灰红
    ("#686480", "#f1f0f4"),  # 深灰紫
    ("#517579", "#edf4f4"),  # 深灰青
]


def notice_color(notice_id: str) -> dict:
    """根据 notice_id 返回 (主色, 背景色) 元组，同一标讯始终同色"""
    import hashlib
    h = int(hashlib.md5(notice_id.encode()).hexdigest()[:8], 16)
    idx = h % len(_NOTICE_COLORS)
    primary, bg = _NOTICE_COLORS[idx]
    return {"primary": primary, "bg": bg}


templates.env.filters["notice_color"] = notice_color
