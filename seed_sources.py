"""种子数据：初始化默认标讯来源 + 测试爬虫配置

用法: python seed_sources.py
这将在数据库中创建预配置的标讯来源。
"""
import asyncio
import sys
sys.path.insert(0, '.')

from database import async_session, init_db
from sqlalchemy import select
from models import BidSource


DEFAULT_SOURCES = [
    {
        "name": "中国政府采购网-地方公告",
        "url": "http://www.ccgp.gov.cn/cggg/dfgg/",
        "website_type": "government_procurement",
        "region": "全国",
        "scrape_interval_minutes": 120,
        "is_active": True,
        "scrape_config": {
            "list_url": "http://www.ccgp.gov.cn/cggg/dfgg/index_{page}.htm",
            "item_selector": "ul.vT-list li",
            "fields": {
                "external_id": {
                    "selector": "a",
                    "attr": "href",
                    "regex": r"(\d{10,})"
                },
                "title": {
                    "selector": "a",
                    "attr": "text"
                },
                "detail_url": {
                    "selector": "a",
                    "attr": "href",
                    "base_url": "http://www.ccgp.gov.cn"
                },
                "date": {
                    "selector": "span",
                    "attr": "text",
                    "regex": r"(\d{4}-\d{2}-\d{2})"
                }
            },
            "detail_fields": {
                "registration_deadline": {
                    "selector": "td:contains('获取招标文件时间')+td",
                    "processor": "parse_date"
                },
                "bid_deadline": {
                    "selector": "td:contains('开标时间')+td, td:contains('投标截止')+td",
                    "processor": "parse_date"
                },
                "budget_amount": {
                    "selector": "td:contains('预算金额')+td, td:contains('预算')+td",
                    "processor": "extract_number"
                },
                "bid_document_fee": {
                    "selector": "td:contains('招标文件售价')+td",
                    "processor": "extract_number"
                },
                "contact_person": {
                    "selector": "td:contains('项目联系人')+td"
                },
                "contact_phone": {
                    "selector": "td:contains('项目联系人')+td, td:contains('联系电话')+td",
                    "processor": "extract_phone"
                },
                "qualification_requirements": {
                    "selector": "td:contains('投标人资格要求')+td, td:contains('供应商资格')+td"
                }
            },
            "pagination": {
                "param": "page",
                "max": 3
            }
        }
    },
    {
        "name": "全国公共资源交易平台",
        "url": "https://deal.ggzy.gov.cn/ds/deal/dealList.jsp",
        "website_type": "public_resource",
        "region": "全国",
        "scrape_interval_minutes": 120,
        "is_active": False,  # 默认禁用，需用户验证网络连通性
        "scrape_config": {
            "list_url": "https://deal.ggzy.gov.cn/ds/deal/dealList.jsp?DEAL_TIME=01&offset={page}",
            "item_selector": "table.list-table tbody tr",
            "fields": {
                "external_id": {
                    "selector": "a",
                    "attr": "href",
                    "regex": r"dealFind/(\d+)"
                },
                "title": {
                    "selector": "td:nth-child(2) a",
                    "attr": "text"
                },
                "detail_url": {
                    "selector": "td:nth-child(2) a",
                    "attr": "href",
                    "base_url": "https://deal.ggzy.gov.cn"
                },
                "date": {
                    "selector": "td:last-child",
                    "attr": "text"
                }
            },
            "pagination": {
                "offset_param": "offset",
                "step": 20,
                "max": 5
            }
        }
    },
]

# 光伏检测行业相关关键词
PV_KEYWORDS = ["光伏", "太阳能", "新能源", "检测", "检验", "监测", "电站", "组件"]


async def seed():
    await init_db()

    async with async_session() as db:
        for src_data in DEFAULT_SOURCES:
            # 检查是否已存在
            existing = (await db.execute(
                select(BidSource).where(BidSource.name == src_data["name"])
            )).scalar_one_or_none()

            if existing:
                print(f"⏭ 已存在: {src_data['name']}")
                continue

            source = BidSource(**src_data)
            db.add(source)
            status = "✅" if src_data["is_active"] else "⏸ (需手动启用)"
            print(f"{status} 添加: {src_data['name']} [{src_data['website_type']}]")

        await db.commit()

    print(f"\n📋 共 {len(DEFAULT_SOURCES)} 个来源已配置")
    print(f"   浏览器打开 http://localhost:8000/sources 查看和管理")
    print(f"\n💡 提示:")
    print(f"   1. 先运行 python test_scrape_urls.py 测试网站连通性")
    print(f"   2. 在浏览器中使用 F12 开发者工具查看目标网站的 HTML 结构")
    print(f"   3. 修改 scrape_config 中的 selector 以匹配实际页面结构")
    print(f"   4. 启用来源后，点击「爬取」按钮手动测试")
    print(f"   5. 光伏检测行业建议关注关键词: {', '.join(PV_KEYWORDS)}")


if __name__ == "__main__":
    asyncio.run(seed())
