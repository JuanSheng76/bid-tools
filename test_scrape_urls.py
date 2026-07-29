"""测试哪些标讯网站可以用静态 HTTP 请求爬取"""
import asyncio
import httpx
from bs4 import BeautifulSoup

# 候选标讯网站列表
CANDIDATE_SITES = [
    {
        "name": "全国公共资源交易平台-工程建设",
        "url": "https://deal.ggzy.gov.cn/ds/deal/dealList.jsp",
        "website_type": "government_procurement",
        "region": "全国",
        "scrape_config": {
            "list_url": "https://deal.ggzy.gov.cn/ds/deal/dealList.jsp?DEAL_TIME=01&offset={page}",
            "item_selector": "table.list-table tbody tr",
            "fields": {
                "external_id": {"selector": "a", "attr": "href", "regex": r"dealFind/(\d+)"},
                "title": {"selector": "a", "attr": "text"},
                "detail_url": {"selector": "a", "attr": "href"},
                "date": {"selector": "td:last-child", "attr": "text"},
            },
            "detail_fields": {
                "registration_deadline": {"selector": "td:contains('报名截止')+td", "processor": "parse_date"},
                "bid_deadline": {"selector": "td:contains('投标截止')+td", "processor": "parse_date"},
                "budget_amount": {"selector": "td:contains('预算')+td", "processor": "extract_number"},
                "contact_phone": {"selector": "td:contains('电话')+td", "processor": "extract_phone"},
                "contact_person": {"selector": "td:contains('联系人')+td"},
            },
            "pagination": {"offset_param": "offset", "step": 20, "max": 10},
        },
    },
    {
        "name": "中国政府采购网-地方分站",
        "url": "http://www.ccgp.gov.cn/cggg/dfgg/",
        "website_type": "government_procurement",
        "region": "全国",
        "scrape_config": {
            "list_url": "http://www.ccgp.gov.cn/cggg/dfgg/index_{page}.htm",
            "item_selector": "ul.vT-list li",
            "fields": {
                "external_id": {"selector": "a", "attr": "href", "regex": r"(\d+)"},
                "title": {"selector": "a", "attr": "text"},
                "detail_url": {"selector": "a", "attr": "href", "base_url": "http://www.ccgp.gov.cn"},
                "date": {"selector": "span", "attr": "text", "regex": r"(\d{4}-\d{2}-\d{2})"},
            },
            "detail_fields": {
                "registration_deadline": {"selector": "td:contains('获取招标文件时间')+td", "processor": "parse_date"},
                "bid_deadline": {"selector": "td:contains('开标时间')+td", "processor": "parse_date"},
                "budget_amount": {"selector": "td:contains('预算金额')+td", "processor": "extract_number"},
                "contact_phone": {"selector": "td:contains('项目联系人')+td", "processor": "extract_phone"},
                "contact_person": {"selector": "td:contains('项目联系人')+td"},
            },
            "pagination": {"param": "page", "max": 5},
        },
    },
    {
        "name": "中国招标投标公共服务平台",
        "url": "https://www.cebpubservice.com/buyer/index.jhtml",
        "website_type": "public_resource",
        "region": "全国",
        "scrape_config": {
            "list_url": "https://www.cebpubservice.com/buyer/index.jhtml?page={page}",
            "item_selector": "ul.news-list li",
            "fields": {
                "external_id": {"selector": "a", "attr": "href", "regex": r"(\d+)"},
                "title": {"selector": "a", "attr": "text"},
                "detail_url": {"selector": "a", "attr": "href", "base_url": "https://www.cebpubservice.com"},
                "date": {"selector": "span.date", "attr": "text"},
            },
            "detail_fields": {},
            "pagination": {"param": "page", "max": 5},
        },
    },
    {
        "name": "招标网-招标公告",
        "url": "https://www.zhaobiao.cn/",
        "website_type": "other",
        "region": "全国",
        "scrape_config": {
            "list_url": "https://www.zhaobiao.cn/bid_{page}.html",
            "item_selector": "div.bid-list div.item",
            "fields": {
                "external_id": {"selector": "a", "attr": "href", "regex": r"(\d+)"},
                "title": {"selector": "a.title", "attr": "text"},
                "detail_url": {"selector": "a.title", "attr": "href", "base_url": "https://www.zhaobiao.cn"},
                "date": {"selector": "span.time", "attr": "text"},
            },
            "detail_fields": {},
            "pagination": {"param": "page", "max": 5},
        },
    },
    {
        "name": "采招网-招标公告",
        "url": "https://www.bidcenter.com.cn/",
        "website_type": "other",
        "region": "全国",
        "scrape_config": {
            "list_url": "https://www.bidcenter.com.cn/news-1-{page}.html",
            "item_selector": "div.news-list ul li",
            "fields": {
                "external_id": {"selector": "a", "attr": "href", "regex": r"(\d+)"},
                "title": {"selector": "a", "attr": "text"},
                "detail_url": {"selector": "a", "attr": "href", "base_url": "https://www.bidcenter.com.cn"},
                "date": {"selector": "span", "attr": "text", "regex": r"(\d{4}-\d{2}-\d{2})"},
            },
            "detail_fields": {},
            "pagination": {"param": "page", "max": 5},
        },
    },
]


async def test_url(name: str, url: str) -> dict:
    """测试单个 URL 是否可抓取"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    result = {"name": name, "url": url, "accessible": False, "has_table": False, "has_list": False,
              "items_found": 0, "error": None, "sample_titles": [], "content_type": None, "content_length": 0}

    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            result["content_type"] = resp.headers.get("content-type", "")
            result["content_length"] = len(resp.text)
            resp.raise_for_status()

            soup = BeautifulSoup(resp.text, "html.parser")

            # 检查是否包含列表/表格
            result["has_table"] = bool(soup.select("table"))
            result["has_list"] = bool(soup.select("ul li, ol li"))
            result["accessible"] = True

            # 检查常见的选择器模式
            selectors_to_try = [
                "ul li a", "table tbody tr td a", "div.list a", "div.news-list li a",
                "div.item a", ".news-item a", "tr td a[href]", "ul.vT-list li a",
            ]
            for sel in selectors_to_try:
                items = soup.select(sel)
                if items:
                    result["items_found"] = max(result["items_found"], len(items))
                    titles = []
                    for item in items[:5]:
                        text = item.get_text(strip=True)
                        if len(text) > 5:  # 有意义的标题
                            titles.append(text[:80])
                    if titles:
                        result["sample_titles"] = titles
                        result["best_selector"] = sel
                    break

    except httpx.ConnectError as e:
        result["error"] = f"连接失败: {e}"
    except httpx.HTTPStatusError as e:
        result["error"] = f"HTTP {e.response.status_code}"
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"

    return result


async def main():
    print("=" * 70)
    print("  标讯网站可爬性测试")
    print("  测试范围: {} 个候选网站".format(len(CANDIDATE_SITES)))
    print("=" * 70)

    results = []
    for site in CANDIDATE_SITES:
        print(f"\n🔍 正在测试: {site['name']} ({site['url']})...")
        result = await test_url(site["name"], site["url"])
        results.append(result)

        if result["accessible"]:
            print(f"   ✅ 可访问 | 类型: {result['content_type'][:60]} | 大小: {result['content_length']} 字节")
            print(f"   📊 表格: {'有' if result['has_table'] else '无'} | 列表: {'有' if result['has_list'] else '无'} | 链接项: {result['items_found']}")
            if result.get("best_selector"):
                print(f"   🎯 最佳选择器: {result['best_selector']}")
            if result["sample_titles"]:
                print(f"   📝 样本标题:")
                for t in result["sample_titles"]:
                    print(f"      - {t}")
        else:
            print(f"   ❌ 不可访问: {result['error']}")

    print("\n" + "=" * 70)
    print("  汇总")
    print("=" * 70)

    accessible = [r for r in results if r["accessible"]]
    usable = [r for r in accessible if r["items_found"] > 0]

    print(f"可访问: {len(accessible)}/{len(results)}")
    print(f"可爬取(有条件项): {len(usable)}/{len(results)}")

    if usable:
        print("\n✅ 推荐添加的来源:")
        for r in usable:
            site = next(s for s in CANDIDATE_SITES if s["name"] == r["name"])
            print(f"\n   📌 {r['name']}")
            print(f"   URL: {r['url']}")
            print(f"   类型: {site['website_type']} | 地区: {site['region']}")
            if r.get("best_selector"):
                print(f"   列表选择器: {r['best_selector']}")
            print(f"   找到 {r['items_found']} 个可提取项")
    else:
        print("\n⚠️ 没有找到可直接爬取的网站。可能原因:")
        print("   1. 网站使用了 JS 动态渲染（需要 Selenium/Playwright）")
        print("   2. 网站需要登录")
        print("   3. 网络连接问题（可能需要 VPN 或代理）")
        print("\n   建议：使用浏览器开发者工具 (F12) 检查目标网站的 Network 标签")
        print("   查看首次 HTML 响应中是否包含列表数据（Ctrl+F 搜索已知标题）")

    print("\n📋 添加来源方式:")
    print("   浏览器打开 http://localhost:8000/sources → 点击新建")
    print("   填入上述测试通过的网站信息即可")
    print("   scrape_config 模板已预置在上述候选列表中")


if __name__ == "__main__":
    asyncio.run(main())
