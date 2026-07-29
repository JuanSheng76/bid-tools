"""通用标讯爬虫（配置驱动）"""
import json
import hashlib
import re
from datetime import datetime
from typing import Optional
import httpx
from bs4 import BeautifulSoup
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from models import BidSource, BidNotice


async def scrape_source(source: BidSource, db: AsyncSession) -> int:
    """
    爬取单个标讯来源
    返回：新增的标讯数量，失败时返回 -1
    """
    config = source.scrape_config or {}
    if not config or not config.get("list_url"):
        return -1

    new_count = 0
    max_pages = config.get("pagination", {}).get("max", 5)

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }

        for page in range(1, max_pages + 1):
            try:
                list_url = config["list_url"].format(page=page)
                resp = await client.get(list_url, headers=headers)
                resp.raise_for_status()
            except Exception as e:
                print(f"[Scraper] 获取列表页失败: {list_url}, 错误: {e}")
                break

            soup = BeautifulSoup(resp.text, "html.parser")
            item_selector = config.get("item_selector", "li")
            items = soup.select(item_selector)

            if not items:
                break

            for item in items:
                fields = config.get("fields", {})
                external_id = _extract_field(item, fields.get("external_id", {}))
                title = _extract_field(item, fields.get("title", {}))
                detail_url = _extract_field(item, fields.get("detail_url", {}))
                date_str = _extract_field(item, fields.get("date", {}))

                if not external_id or not title:
                    continue

                # 去重
                existing = await db.execute(
                    select(BidNotice).where(BidNotice.external_id == external_id)
                )
                if existing.scalar_one_or_none():
                    continue

                # 爬取详情
                detail_data = {}
                if detail_url:
                    detail_data = await _scrape_detail(client, detail_url, config.get("detail_fields", {}), headers)

                # 创建标讯
                notice = BidNotice(
                    source_id=source.id,
                    source_url=detail_url or list_url,
                    external_id=external_id,
                    title=title,
                    publishing_date=_parse_date(date_str) if date_str else None,
                    registration_deadline=_parse_date(detail_data.get("registration_deadline")),
                    bid_deadline=_parse_date(detail_data.get("bid_deadline")),
                    budget_amount=_parse_number(detail_data.get("budget_amount")),
                    bid_document_fee=_parse_number(detail_data.get("bid_document_fee")),
                    platform_registration_required="平台注册" in (detail_data.get("platform_notes", "") or ""),
                    contact_person=detail_data.get("contact_person", ""),
                    contact_phone=detail_data.get("contact_phone", ""),
                    qualification_requirements=detail_data.get("qualification_requirements", ""),
                    raw_content=detail_data.get("raw_html", ""),
                    status="new",
                    is_manual=False,
                )
                db.add(notice)
                new_count += 1

            # 检查是否有下一页
            next_selector = config.get("pagination", {}).get("next_selector")
            if next_selector and not soup.select_one(next_selector):
                break

    await db.commit()
    return new_count


async def _scrape_detail(client: httpx.AsyncClient, url: str, detail_config: dict, headers: dict) -> dict:
    """爬取详情页"""
    try:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
    except Exception:
        return {}

    soup = BeautifulSoup(resp.text, "html.parser")
    data = {"raw_html": resp.text[:10000]}

    for field_name, field_config in detail_config.items():
        value = _extract_field(soup, field_config)
        if value:
            data[field_name] = value

    # 尝试提取联系电话（正则匹配）
    if not data.get("contact_phone"):
        phones = re.findall(r'1[3-9]\d{9}|0\d{2,3}-?\d{7,8}', resp.text)
        if phones:
            data["contact_phone"] = phones[0]

    # 尝试提取联系人
    if not data.get("contact_person"):
        match = re.search(r'联系[人方][：:]\s*([^\s<]{2,10})', resp.text)
        if match:
            data["contact_person"] = match.group(1)

    return data


def _extract_field(soup, config: dict) -> Optional[str]:
    """根据配置提取字段"""
    if not config or not config.get("selector"):
        return None

    selector = config["selector"]
    attr = config.get("attr", "text")
    regex = config.get("regex")

    try:
        el = soup.select_one(selector)
        if not el:
            return None

        if attr == "text":
            value = el.get_text(strip=True)
        elif attr == "href":
            href = el.get("href", "")
            base = config.get("base_url", "")
            if base and href and not href.startswith("http"):
                href = base.rstrip("/") + "/" + href.lstrip("/")
            return href
        else:
            value = el.get(attr, "")

        if regex:
            match = re.search(regex, value)
            return match.group(1) if match else None

        return value
    except Exception:
        return None


def _parse_date(s: str) -> Optional[datetime]:
    """解析日期"""
    if not s or not s.strip():
        return None
    s = s.strip()
    # 常用中文日期格式
    for fmt in ["%Y-%m-%d", "%Y-%m-%d %H:%M", "%Y/%m/%d", "%Y/%m/%d %H:%M",
                "%Y年%m月%d日", "%Y年%m月%d日 %H:%M", "%Y.%m.%d"]:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    # 尝试正则提取
    match = re.search(r'(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})[日]?', s)
    if match:
        try:
            return datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            pass
    return None


def _parse_number(s: str) -> Optional[float]:
    """提取数字"""
    if not s:
        return None
    s = s.strip().replace(",", "").replace("，", "").replace(" ", "")
    # 万元转换
    match = re.search(r'([\d.]+)\s*(?:万元|万)', s)
    if match:
        return float(match.group(1))
    match = re.search(r'[\d.]+', s)
    if match:
        return float(match.group(0))
    return None
