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

# 调色板：12 种颜色，按 notice_id 的 hash 取模，同一标讯始终同色
_NOTICE_COLORS = [
    ("#1677ff", "#e6f4ff"),  # 蓝
    ("#52c41a", "#f6ffed"),  # 绿
    ("#fa8c16", "#fff7e6"),  # 橙
    ("#722ed1", "#f9f0ff"),  # 紫
    ("#13c2c2", "#e6fffb"),  # 青
    ("#eb2f96", "#fff0f6"),  # 粉
    ("#faad14", "#fffbe6"),  # 金
    ("#2f54eb", "#f0f5ff"),  # 靛蓝
    ("#a0d911", "#fcffe6"),  # 黄绿
    ("#f5222d", "#fff1f0"),  # 红
    ("#531dab", "#f3e8ff"),  # 深紫
    ("#08979c", "#e6fffb"),  # 深青
]


def notice_color(notice_id: str) -> dict:
    """根据 notice_id 返回 (主色, 背景色) 元组，同一标讯始终同色"""
    import hashlib
    h = int(hashlib.md5(notice_id.encode()).hexdigest()[:8], 16)
    idx = h % len(_NOTICE_COLORS)
    primary, bg = _NOTICE_COLORS[idx]
    return {"primary": primary, "bg": bg}


templates.env.filters["notice_color"] = notice_color
