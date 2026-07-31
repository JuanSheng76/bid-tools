"""演示数据生成器 — 为云端演示/新数据库自动填充数据

所有数据使用 DEMO- 前缀标记，幂等（已存在则跳过）。
由 main.py 的 lifespan 在检测到无用户时自动调用。
"""

import json
import uuid
from datetime import datetime, timedelta
from database import async_session
from sqlalchemy import select
from models import User, Company, BidSource, BidNotice, Registration, Task, BidResult
import bcrypt


DEMO_PREFIX = "DEMO-"
OUR_COMPANY = "测试科技有限公司"

COMPETITORS = [
    "华测新能源技术有限公司",
    "中检能源科技有限公司",
    "国能检测认证中心",
    "华东电力试验研究院",
    "中科光伏检测有限公司",
]

LOSS_REASONS = [
    "综合评分排名第二，商务分略低",
    "报价高于中标单位，价格分失分",
    "项目团队同类业绩得分不足",
    "技术方案响应深度不足",
    "本地服务能力评分偏低",
]


# ============================================================
# 辅助函数
# ============================================================

def _hash(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _now() -> datetime:
    return datetime.utcnow()


def _days_ago(n: int) -> datetime:
    return _now() - timedelta(days=n)


def _days_later(n: int) -> datetime:
    return _now() + timedelta(days=n)


# ============================================================
# 演示公司资料
# ============================================================

DEMO_COMPANY = {
    "name": OUR_COMPANY,
    "credit_code": "91110108MA01DEMO01",
    "legal_person": "张三",
    "address": "北京市海淀区中关村科技园区demo大道100号",
    "contact_phone": "010-88886666",
    "contact_person": "李经理",
    "contact_email": "demo@test-tech.com",
    "qualifications": [
        {
            "name": "CMA检验检测机构资质认定",
            "level": "国家级",
            "cert_no": "CMA2024110001",
            "issuing_authority": "国家认证认可监督管理委员会",
            "issue_date": "2024-03-15",
            "expiry_date": "2030-03-14",
            "is_permanent": False,
        },
        {
            "name": "CNAS实验室认可证书",
            "level": "国家级",
            "cert_no": "CNAS L12345",
            "issuing_authority": "中国合格评定国家认可委员会",
            "issue_date": "2023-08-20",
            "expiry_date": "2028-08-19",
            "is_permanent": False,
        },
        {
            "name": "ISO 9001质量管理体系认证",
            "level": "国际",
            "cert_no": "ISO9001-2024-DEMO",
            "issuing_authority": "SGS通标标准技术服务有限公司",
            "issue_date": "2024-01-10",
            "expiry_date": "2027-01-09",
            "is_permanent": False,
        },
        {
            "name": "电力工程调试资质证书",
            "level": "甲级",
            "cert_no": "DLTS-2023-0888",
            "issuing_authority": "国家能源局",
            "issue_date": "2023-06-01",
            "expiry_date": "2028-05-31",
            "is_permanent": False,
        },
        {
            "name": "安全生产许可证",
            "level": "省级",
            "cert_no": "AQ-2025-DEMO-001",
            "issuing_authority": "北京市应急管理局",
            "issue_date": "2025-02-01",
            "expiry_date": "2028-01-31",
            "is_permanent": False,
        },
    ],
    "performances": [
        {
            "project_name": "华东区域光伏电站性能检测服务",
            "project_type": "光伏检测",
            "contract_amount": 186.0,
            "client_name": "国网江苏省电力有限公司",
            "contract_date": "2024-08-01",
            "description": "对江苏省内12座集中式光伏电站进行年度性能检测，包括组件衰减率、逆变器效率、系统PR值等指标。",
        },
        {
            "project_name": "分布式光伏组件抽检与评估项目",
            "project_type": "组件检测",
            "contract_amount": 128.0,
            "client_name": "浙江省能源集团有限公司",
            "contract_date": "2024-09-15",
            "description": "抽检8个分布式光伏项目的组件质量，出具IEC标准检测报告。",
        },
        {
            "project_name": "某能源集团电站运维质量检测",
            "project_type": "运维检测",
            "contract_amount": 320.0,
            "client_name": "华能新能源股份有限公司",
            "contract_date": "2024-11-01",
            "description": "对华能下属6个风电场和4个光伏电站进行运维质量第三方评估。",
        },
        {
            "project_name": "工业园区屋顶光伏安全评估",
            "project_type": "安全评估",
            "contract_amount": 96.0,
            "client_name": "广东省工业园区管理委员会",
            "contract_date": "2025-02-10",
            "description": "对广州、深圳、东莞三地12个工业园区屋顶光伏系统进行安全风险评估。",
        },
        {
            "project_name": "县域光伏扶贫电站技术核查",
            "project_type": "技术核查",
            "contract_amount": 158.0,
            "client_name": "河南省能源局",
            "contract_date": "2025-05-01",
            "description": "核查全省23个县的光伏扶贫电站发电量、设备状态和运维情况。",
        },
        {
            "project_name": "光伏组件衰减率专项检测",
            "project_type": "组件检测",
            "contract_amount": 142.0,
            "client_name": "青海省新能源开发有限公司",
            "contract_date": "2025-08-01",
            "description": "对青海海南州光伏基地的组件进行为期6个月的衰减率跟踪检测。",
        },
        {
            "project_name": "大型地面电站年度巡检项目",
            "project_type": "巡检",
            "contract_amount": 225.0,
            "client_name": "中广核新能源控股有限公司",
            "contract_date": "2025-12-01",
            "description": "对甘肃酒泉地区5个大型地面电站进行年度巡检，含红外热斑检测。",
        },
        {
            "project_name": "园区综合能源系统技术评估",
            "project_type": "技术评估",
            "contract_amount": 198.0,
            "client_name": "四川省能源投资集团",
            "contract_date": "2026-02-20",
            "description": "对成都天府新区综合能源示范项目进行第三方技术评估。",
        },
    ],
    "personnel": [
        {
            "name": "王工",
            "position": "技术负责人",
            "certifications": "注册电气工程师、光伏系统高级检测师",
            "phone": "13800001001",
            "email": "wang@test-tech.com",
        },
        {
            "name": "刘工",
            "position": "检测工程师",
            "certifications": "光伏组件检测师、红外热像检测师",
            "phone": "13800001002",
            "email": "liu@test-tech.com",
        },
        {
            "name": "陈工",
            "position": "检测工程师",
            "certifications": "逆变器检测师、电能质量评估师",
            "phone": "13800001003",
            "email": "chen@test-tech.com",
        },
        {
            "name": "赵经理",
            "position": "商务经理",
            "certifications": "招标师、PMP项目管理",
            "phone": "13800001004",
            "email": "zhao@test-tech.com",
        },
        {
            "name": "周工",
            "position": "安全员",
            "certifications": "注册安全工程师",
            "phone": "13800001005",
            "email": "zhou@test-tech.com",
        },
        {
            "name": "孙会计",
            "position": "财务",
            "certifications": "注册会计师",
            "phone": "13800001006",
            "email": "sun@test-tech.com",
        },
    ],
    "bank_info": {
        "bank_name": "中国工商银行北京中关村支行",
        "account_no": "0200001234567890123",
        "tax_no": "91110108MA01DEMO01",
    },
}

# ============================================================
# 演示标讯来源（全部禁用，避免云端爬取报错）
# ============================================================

DEMO_SOURCES = [
    {
        "name": "中国政府采购网-地方公告",
        "url": "http://www.ccgp.gov.cn/cggg/dfgg/",
        "website_type": "government_procurement",
        "region": "全国",
        "scrape_interval_minutes": 120,
        "is_active": False,
        "scrape_config": {
            "list_url": "http://www.ccgp.gov.cn/cggg/dfgg/index_{page}.htm",
            "item_selector": "ul.vT-list li",
            "fields": {
                "external_id": {"selector": "a", "attr": "href", "regex": r"(\d{10,})"},
                "title": {"selector": "a", "attr": "text"},
                "detail_url": {"selector": "a", "attr": "href", "base_url": "http://www.ccgp.gov.cn"},
                "date": {"selector": "span", "attr": "text", "regex": r"(\d{4}-\d{2}-\d{2})"},
            },
            "pagination": {"param": "page", "max": 3},
        },
    },
    {
        "name": "全国公共资源交易平台",
        "url": "https://deal.ggzy.gov.cn/ds/deal/dealList.jsp",
        "website_type": "public_resource",
        "region": "全国",
        "scrape_interval_minutes": 120,
        "is_active": False,
        "scrape_config": {
            "list_url": "https://deal.ggzy.gov.cn/ds/deal/dealList.jsp?DEAL_TIME=01&offset={page}",
            "item_selector": "table.list-table tbody tr",
            "fields": {
                "external_id": {"selector": "a", "attr": "href", "regex": r"dealFind/(\d+)"},
                "title": {"selector": "td:nth-child(2) a", "attr": "text"},
                "detail_url": {"selector": "td:nth-child(2) a", "attr": "href", "base_url": "https://deal.ggzy.gov.cn"},
                "date": {"selector": "td:last-child", "attr": "text"},
            },
            "pagination": {"offset_param": "offset", "step": 20, "max": 5},
        },
    },
]

# ============================================================
# 活跃标讯（覆盖 new/assessing/worth/bidding/completed 各状态）
# ============================================================

# 方便构造时间：用 (offset_days, hour, minute) 生成 datetime
def _dt(offset_days: int, hour: int = 9, minute: int = 0) -> datetime:
    """生成相对今天的日期时间。正数=未来，负数=过去"""
    base = _now().replace(hour=hour, minute=minute, second=0, microsecond=0)
    return base + timedelta(days=offset_days)


ACTIVE_NOTICES = [
    # ---- new (3条) ----
    {
        "external_id": "DEMO-ACTIVE-001",
        "title": "青海省集中式光伏电站安全评估检测服务项目",
        "publishing_date": _dt(-5),
        "registration_deadline": _dt(18, 17, 0),
        "bid_deadline": _dt(25, 9, 30),
        "bid_opening_date": _dt(25, 9, 30),
        "bid_opening_location": "青海省公共资源交易中心",
        "budget_amount": 280.0,
        "bid_document_fee": 500.0,
        "bid_bond_amount": 5.6,
        "project_location": "青海省西宁市",
        "project_scope": "对青海省海南州、海西州共8座集中式光伏电站进行安全评估检测，包括结构安全、电气安全、防雷接地等。",
        "qualification_requirements": "1.具备CMA或CNAS资质；2.近三年有光伏电站检测业绩；3.项目负责人具备高级职称。",
        "contact_person": "张先生",
        "contact_phone": "0971-6123456",
        "status": "new",
        "bid_decision": None,
        "assessment": None,
        "is_manual": True,
    },
    {
        "external_id": "DEMO-ACTIVE-002",
        "title": "新能源汽车充电桩检测设备招标采购项目",
        "publishing_date": _dt(-3),
        "registration_deadline": _dt(20, 17, 0),
        "bid_deadline": _dt(28, 10, 0),
        "bid_opening_date": _dt(28, 10, 0),
        "bid_opening_location": "广东省公共资源交易中心",
        "budget_amount": 450.0,
        "bid_document_fee": 800.0,
        "bid_bond_amount": 9.0,
        "project_location": "广东省广州市",
        "project_scope": "采购一批新能源汽车充电桩现场检测设备，含交直流充电桩测试仪、绝缘电阻测试仪等。",
        "qualification_requirements": "1.供应商须为设备制造商或授权代理商；2.设备需取得计量认证；3.提供三年免费维保。",
        "contact_person": "陈女士",
        "contact_phone": "020-88889999",
        "status": "new",
        "bid_decision": None,
        "assessment": None,
        "is_manual": True,
    },
    {
        "external_id": "DEMO-ACTIVE-003",
        "title": "某高校屋顶分布式光伏发电项目监理服务",
        "publishing_date": _dt(-1),
        "registration_deadline": _dt(25, 17, 0),
        "bid_deadline": _dt(38, 9, 30),
        "bid_opening_date": _dt(38, 9, 30),
        "bid_opening_location": "湖北省公共资源交易中心",
        "budget_amount": 65.0,
        "bid_document_fee": 300.0,
        "bid_bond_amount": 1.3,
        "project_location": "湖北省武汉市",
        "project_scope": "对武汉某高校6栋建筑屋顶共2.8MW分布式光伏项目提供监理服务。",
        "qualification_requirements": "1.具备电力工程监理乙级以上资质；2.近三年有光伏项目监理业绩。",
        "contact_person": "周老师",
        "contact_phone": "027-87654321",
        "status": "new",
        "bid_decision": None,
        "assessment": None,
        "is_manual": True,
    },

    # ---- assessing (2条) ----
    {
        "external_id": "DEMO-ACTIVE-004",
        "title": "工业园区智慧能源管理平台系统检测项目",
        "publishing_date": _dt(-10),
        "registration_deadline": _dt(12, 17, 0),
        "bid_deadline": _dt(19, 9, 30),
        "bid_opening_date": _dt(19, 9, 30),
        "bid_opening_location": "江苏省公共资源交易中心",
        "budget_amount": 195.0,
        "bid_document_fee": 500.0,
        "bid_bond_amount": 3.9,
        "project_location": "江苏省苏州市",
        "project_scope": "对苏州工业园区智慧能源管理平台进行功能测试、性能测试和安全测试。",
        "qualification_requirements": "1.具备软件测试资质；2.CMA或CNAS资质；3.近三年有能源管理平台测试经验。",
        "contact_person": "吴先生",
        "contact_phone": "0512-66668888",
        "status": "assessing",
        "bid_decision": None,
        "assessment": {
            "total_score": 56,
            "qual_score": 24,
            "perf_score": 12,
            "personnel_score": 8,
            "financial_score": 6,
            "other_score": 6,
            "recommendation": "consider",
            "risk_notes": "公司软件测试业绩较少，平台类型项目经验不足。",
            "missing_requirements": ["能源管理平台测试经验较少"],
            "assessed_at": _dt(-9).isoformat(),
        },
        "is_manual": True,
    },
    {
        "external_id": "DEMO-ACTIVE-005",
        "title": "某县村级光伏扶贫电站运维检测服务",
        "publishing_date": _dt(-8),
        "registration_deadline": _dt(14, 17, 0),
        "bid_deadline": _dt(21, 9, 30),
        "bid_opening_date": _dt(21, 9, 30),
        "bid_opening_location": "河南省公共资源交易中心",
        "budget_amount": 82.0,
        "bid_document_fee": 200.0,
        "bid_bond_amount": 1.6,
        "project_location": "河南省信阳市",
        "project_scope": "对信阳市下辖5个县的村级光伏扶贫电站进行运维质量检测服务。",
        "qualification_requirements": "1.具备光伏检测相关资质；2.有扶贫项目服务经验优先。",
        "contact_person": "刘科长",
        "contact_phone": "0376-1234567",
        "status": "assessing",
        "bid_decision": None,
        "assessment": {
            "total_score": 48,
            "qual_score": 22,
            "perf_score": 10,
            "personnel_score": 6,
            "financial_score": 5,
            "other_score": 5,
            "recommendation": "consider",
            "risk_notes": "项目金额偏低，地点分散在5个县，交通成本高。",
            "missing_requirements": ["无扶贫项目服务经验"],
            "assessed_at": _dt(-7).isoformat(),
        },
        "is_manual": True,
    },

    # ---- worth (2条) — 已决定投标 ----
    {
        "external_id": "DEMO-ACTIVE-006",
        "title": "华东风电光伏互补电站并网性能检测项目",
        "publishing_date": _dt(-15),
        "registration_deadline": _dt(5, 17, 0),
        "bid_deadline": _dt(12, 9, 30),
        "bid_opening_date": _dt(12, 9, 30),
        "bid_opening_location": "浙江省公共资源交易中心",
        "budget_amount": 356.0,
        "bid_document_fee": 500.0,
        "bid_bond_amount": 7.1,
        "project_location": "浙江省杭州市",
        "project_scope": "对浙江沿海两个风电光伏互补电站进行并网性能检测，涵盖电能质量、功率控制、低电压穿越等。",
        "qualification_requirements": "1.CMA或CNAS资质；2.有风电和光伏检测经验；3.具备并网检测资质。",
        "contact_person": "钱主任",
        "contact_phone": "0571-88887777",
        "status": "worth",
        "bid_decision": "bid",
        "assessment": {
            "total_score": 82,
            "qual_score": 36,
            "perf_score": 20,
            "personnel_score": 12,
            "financial_score": 8,
            "other_score": 6,
            "recommendation": "recommend",
            "risk_notes": "项目技术要求高，需协调多方资源。",
            "missing_requirements": [],
            "assessed_at": _dt(-14).isoformat(),
        },
        "is_manual": True,
    },
    {
        "external_id": "DEMO-ACTIVE-007",
        "title": "国家电网光伏组件批量质量抽检项目",
        "publishing_date": _dt(-12),
        "registration_deadline": _dt(7, 17, 0),
        "bid_deadline": _dt(14, 9, 30),
        "bid_opening_date": _dt(14, 9, 30),
        "bid_opening_location": "北京市公共资源交易中心",
        "budget_amount": 520.0,
        "bid_document_fee": 1000.0,
        "bid_bond_amount": 10.4,
        "project_location": "北京市",
        "project_scope": "对国家电网2026年度光伏组件供应商进行批量质量抽检，预计抽检30批次组件。",
        "qualification_requirements": "1.国家级CMA资质；2.近三年有组件批量检测经验；3.通过国网供应商资格审查。",
        "contact_person": "赵处长",
        "contact_phone": "010-66668888",
        "status": "worth",
        "bid_decision": "bid",
        "assessment": {
            "total_score": 78,
            "qual_score": 32,
            "perf_score": 19,
            "personnel_score": 13,
            "financial_score": 7,
            "other_score": 7,
            "recommendation": "recommend",
            "risk_notes": "国网项目竞争激烈，需关注价格分。",
            "missing_requirements": ["未通过国网供应商资格审查（需补充）"],
            "assessed_at": _dt(-11).isoformat(),
        },
        "is_manual": True,
    },

    # ---- bidding (2条) — 已有倒排计划 ----
    {
        "external_id": "DEMO-ACTIVE-008",
        "title": "南方电网分布式光伏电站验收检测服务",
        "publishing_date": _dt(-35),
        "registration_deadline": _dt(-25, 17, 0),
        "bid_deadline": _dt(3, 9, 30),
        "bid_opening_date": _dt(3, 9, 30),
        "bid_opening_location": "广东省广州市公共资源交易中心",
        "budget_amount": 410.0,
        "bid_document_fee": 800.0,
        "bid_bond_amount": 8.2,
        "project_location": "广东省广州市",
        "project_scope": "对南方电网区域内2026年新建分布式光伏电站进行第三方验收检测，约15个站点。",
        "qualification_requirements": "1.CMA或CNAS资质；2.有南方电网项目经验优先；3.具备电站检测全项能力。",
        "contact_person": "林经理",
        "contact_phone": "020-33338888",
        "status": "bidding",
        "bid_decision": "bid",
        "assessment": {
            "total_score": 85,
            "qual_score": 38,
            "perf_score": 21,
            "personnel_score": 12,
            "financial_score": 8,
            "other_score": 6,
            "recommendation": "recommend",
            "risk_notes": "",
            "missing_requirements": [],
            "assessed_at": _dt(-34).isoformat(),
        },
        "is_manual": True,
    },
    {
        "external_id": "DEMO-ACTIVE-009",
        "title": "某央企新能源基地技术监督服务采购项目",
        "publishing_date": _dt(-40),
        "registration_deadline": _dt(-30, 17, 0),
        "bid_deadline": _dt(8, 9, 30),
        "bid_opening_date": _dt(8, 9, 30),
        "bid_opening_location": "河北省公共资源交易中心",
        "budget_amount": 680.0,
        "bid_document_fee": 1000.0,
        "bid_bond_amount": 13.6,
        "project_location": "河北省张家口市",
        "project_scope": "为某央企在张家口的新能源基地（含光伏、风电、储能）提供为期两年的技术监督服务。",
        "qualification_requirements": "1.具备国家级CMA/CNAS资质；2.央企/国企新能源项目服务经验；3.注册资金不低于500万。",
        "contact_person": "孙主任",
        "contact_phone": "0313-8888666",
        "status": "bidding",
        "bid_decision": "bid",
        "assessment": {
            "total_score": 90,
            "qual_score": 38,
            "perf_score": 23,
            "personnel_score": 13,
            "financial_score": 9,
            "other_score": 7,
            "recommendation": "recommend",
            "risk_notes": "项目金额高、周期长，是重大机会。",
            "missing_requirements": [],
            "assessed_at": _dt(-39).isoformat(),
        },
        "is_manual": True,
    },

    # ---- completed (6条) — 近期已完成开标 ----
    {
        "external_id": "DEMO-ACTIVE-010",
        "title": "江苏省分布式光伏发电项目质量抽查",
        "publishing_date": _dt(-90),
        "registration_deadline": _dt(-75, 17, 0),
        "bid_deadline": _dt(-60, 9, 30),
        "bid_opening_date": _dt(-60, 9, 30),
        "bid_opening_location": "江苏省公共资源交易中心",
        "budget_amount": 168.0,
        "bid_document_fee": 500.0,
        "bid_bond_amount": 3.3,
        "project_location": "江苏省南京市",
        "project_scope": "对江苏省内分布式光伏发电项目进行质量抽查检测。",
        "qualification_requirements": "1.CMA资质；2.光伏检测经验。",
        "contact_person": "王先生",
        "contact_phone": "025-88887777",
        "status": "completed",
        "bid_decision": "bid",
        "assessment": {
            "total_score": 80, "qual_score": 36, "perf_score": 20,
            "personnel_score": 11, "financial_score": 7, "other_score": 6,
            "recommendation": "recommend", "risk_notes": "", "missing_requirements": [],
            "assessed_at": _dt(-88).isoformat(),
        },
        "is_manual": True,
    },
    {
        "external_id": "DEMO-ACTIVE-011",
        "title": "安徽省新能源示范项目竣工验收检测",
        "publishing_date": _dt(-80),
        "registration_deadline": _dt(-65, 17, 0),
        "bid_deadline": _dt(-50, 9, 30),
        "bid_opening_date": _dt(-50, 9, 30),
        "bid_opening_location": "安徽省公共资源交易中心",
        "budget_amount": 245.0,
        "bid_document_fee": 500.0,
        "bid_bond_amount": 4.9,
        "project_location": "安徽省合肥市",
        "project_scope": "安徽省新能源示范项目竣工验收第三方检测。",
        "qualification_requirements": "1.国家级CMA/CNAS资质；2.竣工验收检测经验。",
        "contact_person": "陈先生",
        "contact_phone": "0551-66668888",
        "status": "completed",
        "bid_decision": "bid",
        "assessment": {
            "total_score": 75, "qual_score": 34, "perf_score": 18,
            "personnel_score": 11, "financial_score": 7, "other_score": 5,
            "recommendation": "recommend", "risk_notes": "", "missing_requirements": [],
            "assessed_at": _dt(-78).isoformat(),
        },
        "is_manual": True,
    },
    {
        "external_id": "DEMO-ACTIVE-012",
        "title": "山东省储能电站并网检测服务项目",
        "publishing_date": _dt(-70),
        "registration_deadline": _dt(-55, 17, 0),
        "bid_deadline": _dt(-40, 9, 30),
        "bid_opening_date": _dt(-40, 9, 30),
        "bid_opening_location": "山东省公共资源交易中心",
        "budget_amount": 310.0,
        "bid_document_fee": 500.0,
        "bid_bond_amount": 6.2,
        "project_location": "山东省济南市",
        "project_scope": "山东省内3个新建储能电站并网前检测服务。",
        "qualification_requirements": "1.CMA/CNAS资质；2.储能检测经验。",
        "contact_person": "李女士",
        "contact_phone": "0531-88889999",
        "status": "completed",
        "bid_decision": "bid",
        "assessment": {
            "total_score": 72, "qual_score": 30, "perf_score": 19,
            "personnel_score": 10, "financial_score": 7, "other_score": 6,
            "recommendation": "recommend", "risk_notes": "储能业务经验较少。", "missing_requirements": [],
            "assessed_at": _dt(-68).isoformat(),
        },
        "is_manual": True,
    },
    {
        "external_id": "DEMO-ACTIVE-013",
        "title": "江西省光伏扶贫项目后期评估检测",
        "publishing_date": _dt(-85),
        "registration_deadline": _dt(-70, 17, 0),
        "bid_deadline": _dt(-55, 9, 30),
        "bid_opening_date": _dt(-55, 9, 30),
        "bid_opening_location": "江西省公共资源交易中心",
        "budget_amount": 132.0,
        "bid_document_fee": 500.0,
        "bid_bond_amount": 2.6,
        "project_location": "江西省南昌市",
        "project_scope": "对江西省光伏扶贫项目进行后期运行评估检测。",
        "qualification_requirements": "1.光伏检测资质；2.类似项目经验。",
        "contact_person": "黄科长",
        "contact_phone": "0791-88887777",
        "status": "completed",
        "bid_decision": "bid",
        "assessment": {
            "total_score": 68, "qual_score": 28, "perf_score": 18,
            "personnel_score": 9, "financial_score": 7, "other_score": 6,
            "recommendation": "consider", "risk_notes": "竞争激烈，报价是关键。", "missing_requirements": [],
            "assessed_at": _dt(-83).isoformat(),
        },
        "is_manual": True,
    },
    {
        "external_id": "DEMO-ACTIVE-014",
        "title": "福建省海上风电配套光伏检测项目",
        "publishing_date": _dt(-75),
        "registration_deadline": _dt(-60, 17, 0),
        "bid_deadline": _dt(-45, 9, 30),
        "bid_opening_date": _dt(-45, 9, 30),
        "bid_opening_location": "福建省公共资源交易中心",
        "budget_amount": 286.0,
        "bid_document_fee": 500.0,
        "bid_bond_amount": 5.7,
        "project_location": "福建省福州市",
        "project_scope": "福建海上风电项目配套光伏发电系统检测服务。",
        "qualification_requirements": "1.新能源检测资质；2.海上项目经验。",
        "contact_person": "吴经理",
        "contact_phone": "0591-88887777",
        "status": "completed",
        "bid_decision": "bid",
        "assessment": {
            "total_score": 63, "qual_score": 30, "perf_score": 12,
            "personnel_score": 10, "financial_score": 6, "other_score": 5,
            "recommendation": "consider", "risk_notes": "海上风电经验不足。", "missing_requirements": ["海上项目经验"],
            "assessed_at": _dt(-73).isoformat(),
        },
        "is_manual": True,
    },
    {
        "external_id": "DEMO-ACTIVE-015",
        "title": "四川省高原光伏电站设备老化评估",
        "publishing_date": _dt(-65),
        "registration_deadline": _dt(-50, 17, 0),
        "bid_deadline": _dt(-35, 9, 30),
        "bid_opening_date": _dt(-35, 9, 30),
        "bid_opening_location": "四川省公共资源交易中心",
        "budget_amount": 198.0,
        "bid_document_fee": 500.0,
        "bid_bond_amount": 3.9,
        "project_location": "四川省成都市",
        "project_scope": "四川甘孜、阿坝地区高原光伏电站设备老化状况评估。",
        "qualification_requirements": "1.CMA资质；2.高原项目经验。",
        "contact_person": "扎西",
        "contact_phone": "028-88887777",
        "status": "completed",
        "bid_decision": "bid",
        "assessment": {
            "total_score": 58, "qual_score": 28, "perf_score": 10,
            "personnel_score": 9, "financial_score": 6, "other_score": 5,
            "recommendation": "consider", "risk_notes": "高原项目成本高。", "missing_requirements": ["高原检测经验"],
            "assessed_at": _dt(-63).isoformat(),
        },
        "is_manual": True,
    },
]

# 近期完成标讯的结果映射（与 ACTIVE_NOTICES[9:15] 对应）
COMPLETED_NOTICE_RESULTS = [
    # DEMO-ACTIVE-010 — 中标
    {"result": "won", "winning_company": OUR_COMPANY, "winning_amount": 164.5, "participant_count": 5,
     "our_quote": 165.8, "contract_amount": 162.0, "loss_reason": "",
     "notes": "技术分第一，顺利中标。"},
    # DEMO-ACTIVE-011 — 未中标
    {"result": "lost", "winning_company": COMPETITORS[0], "winning_amount": 238.0, "participant_count": 7,
     "our_quote": 248.5, "contract_amount": None, "loss_reason": LOSS_REASONS[0],
     "notes": "商务分排名第二，价格偏高。"},
    # DEMO-ACTIVE-012 — 中标
    {"result": "won", "winning_company": OUR_COMPANY, "winning_amount": 301.0, "participant_count": 4,
     "our_quote": 308.0, "contract_amount": 298.5, "loss_reason": "",
     "notes": "储能业务突破，顺利中标。"},
    # DEMO-ACTIVE-013 — 未中标
    {"result": "lost", "winning_company": COMPETITORS[1], "winning_amount": 128.0, "participant_count": 6,
     "our_quote": 135.2, "contract_amount": None, "loss_reason": LOSS_REASONS[1],
     "notes": "报价高于中标单位。"},
    # DEMO-ACTIVE-014 — 废标
    {"result": "rejected", "winning_company": COMPETITORS[2], "winning_amount": 275.0, "participant_count": 5,
     "our_quote": 280.0, "contract_amount": None,
     "loss_reason": "资格审查未通过，缺少海上作业安全许可证。",
     "notes": "废标案例，需补充海上作业资质。"},
    # DEMO-ACTIVE-015 — 未中标
    {"result": "lost", "winning_company": COMPETITORS[3], "winning_amount": 190.0, "participant_count": 8,
     "our_quote": 201.5, "contract_amount": None, "loss_reason": LOSS_REASONS[3],
     "notes": "高原项目方案深度不够。"},
]

# ============================================================
# 历史结果数据（18条，用于仪表盘图表，与 seed_results.py 一致）
# ============================================================

HISTORICAL_BIDS = [
    ("2024-08-16", "华东区域光伏电站性能检测服务", "江苏省", 186.0, "won"),
    ("2024-09-27", "分布式光伏组件抽检与评估项目", "浙江省", 128.0, "lost"),
    ("2024-11-08", "某能源集团电站运维质量检测", "山东省", 320.0, "won"),
    ("2024-12-20", "新能源项目竣工验收检测服务", "安徽省", 245.0, "rejected"),
    ("2025-02-14", "工业园区屋顶光伏安全评估", "广东省", 96.0, "won"),
    ("2025-03-28", "储能系统并网性能测试项目", "湖北省", 210.0, "lost"),
    ("2025-05-09", "县域光伏扶贫电站技术核查", "河南省", 158.0, "won"),
    ("2025-06-20", "新能源场站电能质量检测服务", "河北省", 275.0, "lost"),
    ("2025-08-01", "光伏组件衰减率专项检测项目", "青海省", 142.0, "won"),
    ("2025-09-12", "公共建筑光伏验收服务采购", "上海市", 118.0, "cancelled"),
    ("2025-10-24", "风光储一体化项目检测服务", "内蒙古自治区", 368.0, "lost"),
    ("2025-12-05", "大型地面电站年度巡检项目", "甘肃省", 225.0, "won"),
    ("2026-01-16", "光伏逆变器效率现场测试服务", "宁夏回族自治区", 88.0, "lost"),
    ("2026-02-27", "园区综合能源系统技术评估", "四川省", 198.0, "won"),
    ("2026-04-10", "新能源设备第三方质量监督", "福建省", 286.0, "rejected"),
    ("2026-05-08", "光伏电站竣工验收检测项目", "江西省", 176.0, "lost"),
    ("2026-06-05", "绿色能源示范基地评估服务", "山西省", 332.0, "won"),
    ("2026-06-26", "工商业分布式光伏尽职调查", "北京市", 152.0, "lost"),
]

DEMO_LOCATIONS = ["北京市", "上海市", "广州市", "深圳市", "线上"]

# ============================================================
# 倒排计划任务模板
# ============================================================

TASK_TEMPLATE = [
    {"task_type": "get_docs", "title": "获取招标文件",
     "checklist": [{"text": "下载招标文件", "done": False}, {"text": "阅读并标注关键条款", "done": False},
                   {"text": "整理疑问提交澄清", "done": False}]},
    {"task_type": "qualifications", "title": "资质项及承诺函",
     "checklist": [{"text": "整理资质证明材料", "done": False}, {"text": "起草承诺函", "done": False},
                   {"text": "内部审核确认", "done": False}]},
    {"task_type": "certs", "title": "评分项证书/业绩整理",
     "checklist": [{"text": "收集相关业绩证明", "done": False}, {"text": "整理人员证书材料", "done": False},
                   {"text": "制作评分响应表", "done": False}]},
    {"task_type": "pricing", "title": "报价",
     "checklist": [{"text": "核算成本", "done": False}, {"text": "制定报价策略", "done": False},
                   {"text": "制作报价文件", "done": False}]},
    {"task_type": "writing", "title": "编写服务方案",
     "checklist": [{"text": "编写技术方案", "done": False}, {"text": "编写实施方案", "done": False},
                   {"text": "方案校审修改", "done": False}]},
    {"task_type": "format", "title": "调整格式",
     "checklist": [{"text": "统一文档格式", "done": False}, {"text": "编制目录和页码", "done": False},
                   {"text": "最终格式检查", "done": False}]},
    {"task_type": "stamp", "title": "盖章",
     "checklist": [{"text": "打印投标文件", "done": False}, {"text": "加盖公章和签字", "done": False},
                   {"text": "按要求密封", "done": False}]},
]


# ============================================================
# 主入口
# ============================================================

async def seed_demo():
    """填充所有演示数据（幂等）"""
    async with async_session() as db:
        await _seed_users(db)
        await _seed_company(db)
        await _seed_sources(db)
        notice_map = await _seed_active_notices(db)
        await _seed_completed_results(db, notice_map)
        await _seed_historical_results(db)
        await _seed_tasks(db, notice_map)
        await _seed_registrations(db, notice_map)
        await db.commit()

    print("[seed_demo] 演示数据填充完成")
    _print_summary()


async def _seed_users(db):
    """创建演示用户 demo/demo123"""
    existing = (await db.execute(select(User).where(User.username == "demo"))).scalar_one_or_none()
    if existing:
        print("[seed_demo] 演示用户已存在，跳过")
        return

    # 删除可能存在的旧 admin 用户
    old_admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one_or_none()
    if old_admin:
        await db.delete(old_admin)
        print("[seed_demo] 已删除旧测试用户 admin")

    user = User(
        username="demo",
        password_hash=_hash("demo123"),
        full_name="演示管理员",
        role="admin",
        is_active=True,
    )
    db.add(user)
    print("[seed_demo] 已创建演示用户: demo / demo123")


async def _seed_company(db):
    """创建演示公司资料"""
    existing = (await db.execute(select(Company).limit(1))).scalar_one_or_none()
    if existing:
        print("[seed_demo] 公司资料已存在，跳过")
        return

    company = Company(**DEMO_COMPANY)
    db.add(company)
    print("[seed_demo] 已创建演示公司资料")


async def _seed_sources(db):
    """创建标讯来源（全部禁用）"""
    for src_data in DEMO_SOURCES:
        existing = (await db.execute(
            select(BidSource).where(BidSource.name == src_data["name"])
        )).scalar_one_or_none()
        if existing:
            continue
        source = BidSource(**src_data)
        db.add(source)
        print(f"[seed_demo] 已创建标讯来源(禁用): {src_data['name']}")


async def _seed_active_notices(db) -> dict:
    """创建活跃标讯，返回 {external_id: notice_id} 映射"""
    notice_map = {}

    for data in ACTIVE_NOTICES:
        ext_id = data["external_id"]
        existing = (await db.execute(
            select(BidNotice).where(BidNotice.external_id == ext_id)
        )).scalar_one_or_none()
        if existing:
            notice_map[ext_id] = existing.id
            continue

        notice = BidNotice(
            source_id=None,
            source_url="",
            external_id=ext_id,
            title=data["title"],
            publishing_date=data["publishing_date"],
            registration_deadline=data["registration_deadline"],
            bid_deadline=data["bid_deadline"],
            bid_opening_date=data["bid_opening_date"],
            bid_opening_location=data.get("bid_opening_location", ""),
            budget_amount=data.get("budget_amount"),
            bid_document_fee=data.get("bid_document_fee"),
            bid_bond_amount=data.get("bid_bond_amount"),
            project_location=data.get("project_location", ""),
            project_scope=data.get("project_scope", ""),
            qualification_requirements=data.get("qualification_requirements", ""),
            contact_person=data.get("contact_person", ""),
            contact_phone=data.get("contact_phone", ""),
            status=data["status"],
            bid_decision=data.get("bid_decision"),
            assessment=data.get("assessment"),
            is_manual=data.get("is_manual", True),
            created_at=data["publishing_date"],
            updated_at=data["publishing_date"],
        )
        db.add(notice)
        await db.flush()  # 获取生成的 id
        notice_map[ext_id] = notice.id

    await db.flush()
    active_count = len([eid for eid in notice_map if eid not in
        (await db.execute(select(BidNotice.external_id).where(
            BidNotice.external_id.in_(list(notice_map.keys()))
        ))).scalars().all()
    ])
    print(f"[seed_demo] 已创建 {len(notice_map)} 条活跃标讯")
    return notice_map


async def _seed_completed_results(db, notice_map: dict):
    """为 completed 状态的标讯创建开标结果"""
    completed_eids = [n["external_id"] for n in ACTIVE_NOTICES if n["status"] == "completed"]

    for i, ext_id in enumerate(completed_eids):
        if ext_id not in notice_map:
            continue
        notice_id = notice_map[ext_id]

        existing = (await db.execute(
            select(BidResult).where(BidResult.notice_id == notice_id)
        )).scalar_one_or_none()
        if existing:
            continue

        result_data = COMPLETED_NOTICE_RESULTS[i]
        notice_data = ACTIVE_NOTICES[9 + i]  # offset for completed notices

        competitor_quotes = []
        for j in range(min(result_data["participant_count"] - 1, 4)):
            competitor_quotes.append({
                "company": COMPETITORS[j],
                "quote": round(result_data["our_quote"] * (0.85 + j * 0.04), 2),
            })

        contract_signed = None
        contract_expiry = None
        if result_data["result"] == "won" and result_data.get("contract_amount"):
            contract_signed = notice_data["bid_opening_date"] + timedelta(days=15)
            contract_expiry = contract_signed + timedelta(days=365)

        result = BidResult(
            notice_id=notice_id,
            opening_date=notice_data["bid_opening_date"],
            participant_count=result_data["participant_count"],
            our_quote=result_data["our_quote"],
            competitor_quotes=competitor_quotes,
            result=result_data["result"],
            winning_company=result_data["winning_company"],
            winning_amount=result_data["winning_amount"],
            contract_signed_date=contract_signed,
            contract_expiry_date=contract_expiry,
            contract_amount=result_data.get("contract_amount"),
            loss_reason=result_data["loss_reason"],
            notes=result_data["notes"],
        )
        db.add(result)

    print(f"[seed_demo] 已创建 {len(completed_eids)} 条开标结果")


async def _seed_historical_results(db):
    """创建18条历史投标结果（用于仪表盘图表）"""
    existing = (await db.execute(
        select(BidNotice.external_id).where(BidNotice.external_id.like("DEMO-RESULT-%"))
    )).scalars().all()
    existing_eids = set(existing)

    new_count = 0
    for index, (opening_text, title, location, budget, outcome) in enumerate(HISTORICAL_BIDS, 1):
        ext_id = f"DEMO-RESULT-{index:03d}"
        if ext_id in existing_eids:
            continue

        location = DEMO_LOCATIONS[(index - 1) % len(DEMO_LOCATIONS)]
        opening_location = (
            "线上开标（远程不见面开标）"
            if location == "线上"
            else f"{location}公共资源交易中心"
        )
        opening = datetime.strptime(opening_text, "%Y-%m-%d").replace(hour=9, minute=30)
        publishing = opening - timedelta(days=38 + index % 12)
        registration = opening - timedelta(days=20)
        deadline = opening - timedelta(days=3)
        created = publishing - timedelta(days=1)
        our_quote = round(budget * (0.86 + (index % 5) * 0.012), 2)
        participant_count = 3 + index % 5

        if outcome == "won":
            winning_company = OUR_COMPANY
            winning_amount = round(our_quote * 0.992, 2)
            contract_signed = opening + timedelta(days=12 + index % 8)
            contract_expiry = (
                datetime(2026, 8, 18)
                if index == 17
                else contract_signed + timedelta(days=365)
            )
            contract_amount = round(winning_amount * 0.985, 2)
            loss_reason = ""
            notes = "[演示数据] 项目顺利中标，合同信息已归档。"
        elif outcome == "lost":
            winning_company = COMPETITORS[index % len(COMPETITORS)]
            winning_amount = round(our_quote * (0.91 + (index % 3) * 0.015), 2)
            contract_signed = None
            contract_expiry = None
            contract_amount = None
            loss_reason = LOSS_REASONS[index % len(LOSS_REASONS)]
            notes = "[演示数据] 已完成投标复盘并记录改进建议。"
        elif outcome == "rejected":
            winning_company = COMPETITORS[index % len(COMPETITORS)]
            winning_amount = round(budget * 0.84, 2)
            contract_signed = None
            contract_expiry = None
            contract_amount = None
            loss_reason = "资格审查未通过，响应文件存在非实质性偏差"
            notes = "[演示数据] 废标案例，用于资质文件复核培训。"
        else:
            winning_company = ""
            winning_amount = None
            contract_signed = None
            contract_expiry = None
            contract_amount = None
            loss_reason = "采购计划调整，项目终止招标"
            notes = "[演示数据] 招标人取消采购，未进入定标阶段。"

        quotes = []
        for quote_index in range(min(participant_count - 1, 4)):
            factor = 0.82 + ((index + quote_index * 2) % 9) * 0.018
            quotes.append({
                "company": COMPETITORS[(index + quote_index) % len(COMPETITORS)],
                "quote": round(budget * factor, 2),
            })

        # 创建标讯
        notice = BidNotice(
            source_id=None,
            source_url="",
            external_id=ext_id,
            title=title,
            publishing_date=publishing,
            registration_deadline=registration,
            bid_deadline=deadline,
            bid_opening_date=opening,
            bid_opening_location=opening_location,
            budget_amount=budget,
            bid_document_fee=300.0,
            bid_bond_amount=round(budget * 0.02, 2),
            project_location=location,
            project_scope="新能源及光伏项目第三方检测、评估与技术服务。",
            qualification_requirements="具备相关检验检测资质、同类项目业绩及专业技术团队。",
            status="completed",
            bid_decision="bid",
            is_manual=True,
            assessment=None,
            created_at=created,
            updated_at=created,
        )
        db.add(notice)
        await db.flush()

        # 创建结果
        result_created = opening + timedelta(days=2)
        result = BidResult(
            notice_id=notice.id,
            opening_date=opening,
            participant_count=participant_count,
            our_quote=our_quote,
            competitor_quotes=quotes,
            result=outcome,
            winning_company=winning_company,
            winning_amount=winning_amount,
            contract_signed_date=contract_signed,
            contract_expiry_date=contract_expiry,
            contract_amount=contract_amount,
            loss_reason=loss_reason,
            notes=notes,
            created_at=result_created,
            updated_at=result_created,
        )
        db.add(result)
        new_count += 1

    print(f"[seed_demo] 已创建 {new_count} 条历史投标结果")


async def _seed_tasks(db, notice_map: dict):
    """为 bidding 状态的标讯创建倒排计划任务"""
    bidding_eids = [n["external_id"] for n in ACTIVE_NOTICES if n["status"] == "bidding"]

    for ext_id in bidding_eids:
        if ext_id not in notice_map:
            continue
        notice_id = notice_map[ext_id]

        existing = (await db.execute(
            select(Task).where(Task.notice_id == notice_id)
        )).scalars().all()
        if existing:
            continue

        notice_data = next(n for n in ACTIVE_NOTICES if n["external_id"] == ext_id)
        deadline = notice_data["bid_deadline"]

        # 获取演示用户 id
        demo_user = (await db.execute(select(User).where(User.username == "demo"))).scalar_one_or_none()
        assignee_id = demo_user.id if demo_user else None

        days_before_list = [15, 12, 10, 7, 5, 3, 1]
        for i, template in enumerate(TASK_TEMPLATE):
            days_before = days_before_list[i]
            planned_end = deadline - timedelta(days=days_before)
            # 跳过周末
            while planned_end.weekday() >= 5:
                planned_end -= timedelta(days=1)
            planned_start = planned_end - timedelta(days=2)

            # 第一个和第二个任务已完成
            if i < 1:
                status = "done"
                completed_at = planned_end
            elif i < 2:
                status = "in_progress"
                completed_at = None
            else:
                status = "todo"
                completed_at = None

            task = Task(
                notice_id=notice_id,
                title=template["title"],
                description=f"标讯[{notice_data['title']}]的倒排计划任务",
                task_type=template["task_type"],
                assignee_id=assignee_id,
                status=status,
                priority="high" if i in [1, 2, 3] else ("urgent" if i >= 5 else "medium"),
                planned_start=planned_start,
                planned_end=planned_end,
                completed_at=completed_at,
                sort_order=i,
                checklist=template["checklist"],
            )
            db.add(task)

    # 再创建几条独立自定义任务，增加看板丰富度
    demo_user = (await db.execute(select(User).where(User.username == "demo"))).scalar_one_or_none()
    if demo_user:
        existing_extra = (await db.execute(
            select(Task).where(Task.task_type == "custom", Task.assignee_id == demo_user.id)
        )).scalars().all()
        if not existing_extra:
            # 为第一条 worth 标讯创建2条自定义任务
            worth_eids = [n["external_id"] for n in ACTIVE_NOTICES if n["status"] == "worth"]
            if worth_eids and worth_eids[0] in notice_map:
                extra_tasks = [
                    {"title": "提前联系招标代理了解项目背景", "status": "done", "priority": "medium",
                     "planned_end": _dt(2), "checklist": [{"text": "电话沟通", "done": True}, {"text": "记录要点", "done": True}]},
                    {"title": "准备投标意向函", "status": "todo", "priority": "low",
                     "planned_end": _dt(5), "checklist": [{"text": "起草意向函", "done": False}, {"text": "盖章发出", "done": False}]},
                ]
                for et in extra_tasks:
                    task = Task(
                        notice_id=notice_map[worth_eids[0]],
                        title=et["title"],
                        description="",
                        task_type="custom",
                        assignee_id=demo_user.id,
                        status=et["status"],
                        priority=et["priority"],
                        planned_start=_now(),
                        planned_end=et["planned_end"],
                        sort_order=99,
                        checklist=et["checklist"],
                    )
                    db.add(task)

    print(f"[seed_demo] 已创建任务看板数据")


async def _seed_registrations(db, notice_map: dict):
    """为 worth/bidding 状态的标讯创建报名记录"""
    reg_eids = [n["external_id"] for n in ACTIVE_NOTICES if n["status"] in ("worth", "bidding")]

    for ext_id in reg_eids:
        if ext_id not in notice_map:
            continue
        notice_id = notice_map[ext_id]

        existing = (await db.execute(
            select(Registration).where(Registration.notice_id == notice_id)
        )).scalars().all()
        if existing:
            continue

        notice_data = next(n for n in ACTIVE_NOTICES if n["external_id"] == ext_id)

        # 根据状态决定报名状态
        if notice_data["status"] == "bidding":
            reg_status = "confirmed"
            payment_status = "paid"
            submitted_at = _dt(-3)
        else:
            reg_status = "submitted"
            payment_status = "paid"
            submitted_at = _dt(-1)

        reg = Registration(
            notice_id=notice_id,
            status=reg_status,
            form_data={
                "company_name": OUR_COMPANY,
                "contact_person": "赵经理",
                "contact_phone": "13800001004",
                "credit_code": "91110108MA01DEMO01",
            },
            platform_name=notice_data.get("bid_opening_location", ""),
            platform_account="demo_account",
            payment_status=payment_status,
            payment_amount=notice_data.get("bid_document_fee", 500.0),
            notes="演示报名数据",
            submitted_at=submitted_at,
        )
        db.add(reg)

    print(f"[seed_demo] 已创建报名记录")


def _print_summary():
    print("""
    +======================================+
    |     [Demo] 演示数据填充完成           |
    +======================================+
    |  登录账号: demo / demo123            |
    |  公司资料: 5资质 + 8业绩 + 6人员     |
    |  标讯来源: 2个(全部禁用)             |
    |  活跃标讯: 15条(覆盖各状态)          |
    |  历史结果: 18条(仪表盘图表用)        |
    |  倒排任务: 多条(看板三列)            |
    |  报名记录: 已创建                    |
    +======================================+
    """)
