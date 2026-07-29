"""应用配置"""
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 数据库
DATABASE_URL = f"sqlite+aiosqlite:///{BASE_DIR}/bid_tools.db"

# 会话密钥（生产环境请修改为随机字符串）
SECRET_KEY = os.environ.get("SECRET_KEY", "bid-tools-secret-key-change-in-production")

# 爬虫默认配置
DEFAULT_SCRAPE_INTERVAL_MINUTES = 60
SCRAPE_REQUEST_DELAY_SECONDS = (3, 10)  # 请求间隔范围

# 任务模板（倒排计划）- days_before_deadline
TASK_TEMPLATE = [
    {"task_type": "get_docs",      "title": "获取招标文件",      "days_before": 15, "est_hours": 4,  "priority": "medium"},
    {"task_type": "qualifications","title": "资质项及承诺函",    "days_before": 12, "est_hours": 4,  "priority": "high"},
    {"task_type": "certs",         "title": "评分项证书/业绩整理","days_before": 10, "est_hours": 3,  "priority": "high"},
    {"task_type": "pricing",       "title": "报价",              "days_before": 7,  "est_hours": 2,  "priority": "high"},
    {"task_type": "writing",       "title": "编写服务方案",      "days_before": 5,  "est_hours": 8,  "priority": "medium"},
    {"task_type": "format",        "title": "调整格式",          "days_before": 3,  "est_hours": 2,  "priority": "medium"},
    {"task_type": "stamp",         "title": "盖章",              "days_before": 1,  "est_hours": 1,  "priority": "urgent"},
]

# 评估权重
ASSESSMENT_WEIGHTS = {
    "qualifications": 40,
    "performance": 25,
    "personnel": 15,
    "financial": 10,
    "other": 10,
}

# 推荐阈值
RECOMMEND_THRESHOLD_HIGH = 70
RECOMMEND_THRESHOLD_LOW = 40

# LLM 配置（可选，不配置则使用规则解析）
# 默认使用 DeepSeek，可通过环境变量覆盖
LLM_API_KEY = os.environ.get("LLM_API_KEY", "sk-2816ec8cf2ef457183d055e2323e5420")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com")
LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek-chat")
# 文档截断长度（字符），控制 LLM 调用成本
LLM_MAX_CHARS = int(os.environ.get("LLM_MAX_CHARS", "50000"))
