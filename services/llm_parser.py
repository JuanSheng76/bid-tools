"""大模型招标文件解析服务

使用 LLM（默认 DeepSeek）解析招标文件文本，提取：
- 资格要求（密封/盖章/递交/证书/承诺函/保证金）
- 评分标准（评分项/分值/类别/评分方法 + 自评得分）
- 重要注意事项（映射到 task_type）
- 智能推荐（匹配公司资质/业绩/人员）

LLM 为主解析引擎，规则解析作为 fallback。
"""

import json
import traceback
from datetime import datetime
from typing import Optional

from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, LLM_MAX_CHARS

# ====== System Prompt ======

SYSTEM_PROMPT = """你是一个专业的招标文件解析助手。你的任务是从中国招标文件文本中提取结构化的关键信息。

## 重点关注章节

招标文件通常包含以下章节，请重点关注：

- **招标公告**（第一章）：项目概况、投标人资格要求、招标文件获取方式、递交截止时间/地点、开标时间/地点
- **投标人须知**（第二章）：投标人资格要求（详细）、投标文件编制要求、密封/盖章/递交要求、保证金要求、投标有效期
- **评标办法/评标标准**（第三章）：评分标准、评分项和分值、评审因素

**直接忽略**以下章节，不要从中提取任何内容：
- **投标文件格式/附件**（通常最后一章）：仅提供空白表格模板，无实际信息
- **合同条款及格式**：合同模板，非评审内容
- **需求书/技术规格**：项目需求详细描述，通常不包含评分和资格信息

**重要：关于目录（TOC）** —— 文档开头可能有一个"目录"或"招标文件目录"，列出各章节名称和页码（如"第三章  评标办法（综合评估法）\\t27"）。**目录不是正文内容**，不要将目录条目当作章节内容来提取。真正的章节内容在目录之后，会有完整的段落文字。如果评分标准在目录中只显示了章节标题，请务必在正文中找到对应的完整章节并提取实际内容。

招标文件中的"评分标准"也可能被称为"评标办法"、"评审办法"、"综合评分"等，可能以表格或自然段落形式出现。如果评标办法章节中包含"评标办法前附表"表格，请仔细阅读表格中的每一行，这是评分标准的核心内容。

## 输出格式

你必须返回一个严格的 JSON 对象，结构如下：

```json
{
  "qualification_requirements": {
    "sealing": {"copies": "正本份数和副本份数要求（完整原文）", "packaging": "密封、封装、装订等要求（完整原文）", "requirements_text": "相关原文段落摘录"},
    "submission": {"deadline": "递交截止时间", "location": "递交地点（完整地址）", "method": "递交方式", "requirements_text": "相关原文段落摘录"},
    "stamping": {"requirements": ["盖章签字相关要求，逐条列出"], "requirements_text": "相关原文段落摘录"},
    "required_certificates": [
      {
        "name": "证书或资质全称",
        "type": "basic(基本资质)/professional(专业资质)/financial(财务资质)/other(其他)",
        "level": "等级要求（如甲级、乙级、一级、二级、A级、B级等，原文摘录，无则空字符串）",
        "issuing_authority": "颁发机构（如住房和城乡建设部、省住建厅等，原文摘录，无则空字符串）",
        "time_range": "时效要求（如近三年、2023年1月至今、有效期内等，原文摘录，无则空字符串）",
        "quantity": "数量要求（如至少2项、不少于3个等，原文摘录，无则空字符串）",
        "detail": "完整具体要求（原文逐字摘录，必须包含所有限定条件：等级/发证机构/数量/时效/金额/专业范围。严禁简写为'XX资质'）"
      }
    ],
    "required_commitments": [
      {
        "name": "承诺函/声明函全称",
        "detail": "具体格式和内容要求（原文摘录，不要简写）",
        "format_required": "是否需要使用招标文件提供的特定格式模板（是/否/未说明）"
      }
    ],
    "financial_requirements": {"bid_bond": "投标保证金金额（万元，数字）或null", "bid_bond_form": "保证金形式", "performance_bond": "履约保证金金额（万元，数字）或null", "other": "其他财务费用要求"},
    "raw_text": "资格要求相关原文摘要（保留关键段落，不简写）"
  },
  "scoring_criteria": {
    "total_points": "总分（数字）",
    "items": [
      {
        "category": "price(报价)/technical(技术)/performance(业绩)/personnel(人员)/qualification(资质)/other(其他)",
        "label": "评分项名称（完整名称）",
        "max_points": "该项满分（数字）",
        "scoring_method": "评分方法详细描述（完整原文，说明如何得分、扣分规则）",
        "requirements": ["该项对投标人的具体要求，逐条列出，不简写"],
        "self_assessed_score": "基于公司现有资料预估的得分（数字，0~max_points）。报价项无法预知填0；技术方案项根据经验给预估；业绩/人员/资质项逐项对比后打分。",
        "self_assessed_reason": "自评依据（说明公司有哪些匹配项、缺什么、为什么给这个分数，一句话概括）"
      }
    ],
    "self_assessed_total": "所有 self_assessed_score 的总和（数字）",
    "raw_text": "评分标准/评标办法相关原文段落"
  },
  "important_notes": [
    {
      "text": "注意事项完整原文（保留上下文，不要截断或简写）",
      "task_type": "stamp(盖章签字)/format(格式装订密封)/pricing(保证金费用报价)/certs(证书业绩)/qualifications(承诺函声明授权)/get_docs(踏勘答疑澄清)",
      "priority": "urgent(不满足直接废标)/high(重要评分项)/medium(一般要求)/low(建议)"
    }
  ]
}
```

## 提取规则

### 1. 资格要求 —— 极度具体，严禁简写 ⚠️

**核心原则：每一个字段都必须保留招标文件原文的完整表述，绝不能概括、简写或省略任何限定条件。简写的资格要求毫无价值，会直接导致废标。**

**⚠️ 名称完整性（name 字段硬性要求）：**
- **证书名称和承诺函名称必须使用招标文件中的完整原始名称，一字不差。**
- 严禁简写：招标文件写"信用中国网站查询截图"就是"信用中国网站查询截图"，不能写成"信用中国"；写"中国裁判文书网行贿犯罪记录查询截图"就是完整全称，不能缩写。
- 严禁泛化：招标文件写"投标承诺书"就是"投标承诺书"，不能写成"承诺书"；写"法定代表人身份证明书"就是全称，不能写成"法人证明"。
- 承诺函同理：招标文件写"无行贿犯罪记录声明函"不能简写为"无行贿声明"；写"中小企业声明函"不能简写为"中小企业声明"。
- 时刻反问自己：这个名称是否和招标文件原文完全一致？如果少了一个字，就是错误。

#### 所需证书 —— 必须逐字段提取（从原文逐字摘录，宁长勿短）

每个证书必须拆解为以下维度，不得合并或省略：

- **name**：证书全称
- **level**：等级要求。如"一级及以上""甲级""乙级及以上""A级""特级"等。原文没有提到等级则留空
- **issuing_authority**：颁发机构全称。如"住房和城乡建设部""省住房和城乡建设厅""国家市场监督管理总局"等。原文没有提到则留空
- **time_range**：时效限定。如"近三年（2023年1月1日至今）""投标截止日前5年内""证书须在有效期内"等。原文没有提到则留空
- **quantity**：数量要求。如"至少2项""不少于3个""2项及以上"等。原文没有提到则留空
- **detail**：**这是最重要的字段**，必须逐字摘录原文中关于该证书的全部要求，包含所有限定条件。长度不限，宁长勿短

**错误示例（严禁出现）**：
- ❌ "建筑工程施工总承包资质" —— 只有名称，缺少等级、颁发机构、数量
- ❌ "ISO9001质量管理体系认证" —— 缺少认证范围

**正确示例（必须达到的标准）**：
- ✅ name:"建筑工程施工总承包", level:"一级及以上", issuing_authority:"住房和城乡建设部", detail:"具有住房和城乡建设部颁发的建筑工程施工总承包一级及以上资质，且资质证书须在有效期内"
- ✅ name:"ISO9001质量管理体系认证", detail:"具有有效的ISO9001质量管理体系认证证书，认证范围须包含光伏电站检测或相关技术服务"

#### 承诺函 —— 必须包含格式要求

- **format_required**：原文提到"格式详见附件""按招标文件提供的格式""使用第六章格式"等 → 填"是"；提到"格式自拟" → 填"否"；未提及 → 填"未说明"
- **detail**：完整摘录格式和内容要求（盖章要求、是否需要法人签字、是否需要单独密封等）

#### 密封/盖章/递交要求

- sealing.copies：完整照抄原文表述，如"正本1份，副本4份，电子版1份（U盘）"
- sealing.packaging：完整照抄密封/封装/装订相关要求的原文
- stamping.requirements：逐条列出，包括骑缝章、逐页签字、法人章还是签字、是否接受授权委托人代签等所有细节
- submission：保留完整地址（含楼层/房间号）、截止时间（含时区如"北京时间"）、递交方式、是否接受邮寄

#### 保证金

- bid_bond/performance_bond 转为数字（万元），中文大写数字要转换：
  - "伍万元"→5.0，"伍拾万元"→50.0，"壹佰万元"→100.0
  - "50000元"→5.0，"1000000元"→100.0
- 保留原文中的到账截止时间要求、转出账户要求（如"须从基本账户转出"）、保函格式要求

### 2. 评分标准 + 自评得分 —— 逐项分析公司能拿多少分

- 招标文件中"评分标准"可能以表格形式出现，也可能以"评标办法""评审办法""综合评分""评分细则"等标题下的自然段落形式出现
- 仔细阅读全文，找出所有明确的评分项及其分值，不要遗漏任何评分维度
- 正确归类：报价相关→price，技术方案/服务方案/实施方案→technical，项目业绩/类似项目→performance，人员配置/项目负责人→personnel，企业资质/信誉→qualification
- **scoring_method 必须完整**：保留原文中关于如何评分的描述（如"满足得X分，不满足得0分""每提供一个得X分，最高Y分""根据优劣在X-Y分之间打分"）
- **requirements 必须逐条完整列出**：例如"投标人近三年（2023年1月至今）须具有至少2个单项合同金额不低于100万元的光伏电站检测业绩，须提供合同复印件及验收报告"

#### 自评得分 —— 关键决策依据（认真评估每一项）

你需要根据**公司现有资料**（资质、业绩、人员），对每个评分项预估本公司能得多少分。这是投标决策者的核心参考，请逐项认真评估：

1. **逐项对比**：仔细阅读每个评分项的 scoring_method 和 requirements，然后对比公司现有资料中是否有匹配项
2. **客观评分规则**：
   - 公司完全满足所有要求 → 给满分或接近满分（max_points × 90%~100%）
   - 公司部分满足（如要求3个业绩只有2个、要求一级资质持有二级）→ 按评分规则打折
   - 公司完全不满足或无法判断 → 给0分
3. **报价项(price)**：无法预知报价，一律填0
4. **技术方案项(technical)**：无法预知方案质量，根据公司是否有相关项目经验给预估（有丰富同类经验给60~80%分，有部分经验给30~60%分，无经验给0~20%分）
5. **业绩项(performance)**：逐项对比公司业绩列表中是否有匹配的（金额够不够、时间在不在范围内、类型对不对口），严格按评分规则计算
6. **人员项(personnel)**：对比公司人员列表中是否有持有相应证书/职称的人员
7. **资质项(qualification)**：对比公司资质列表中是否持有相应等级/类型的证书
8. **self_assessed_reason** 必须写清楚判断依据，例如"公司有2个同类业绩（要求3个），金额均达标，按每提供1个得5分计算，预计得10/15分"

### 3. 重要注意事项 —— 完整展示，按段落合并

- 从全文中找出投标人需要特别关注的每一个事项，**不要遗漏**
- **⚠️ 合并原则（核心）：同一段落、同一小节的相关要求，合并为一条注意事项，保留完整段落上下文。不要将同一段落的多个要求拆散成多条碎片。宁可一条长，不要一堆碎。**
- 例如：某一段同时提到"正本1份副本4份、A4纸双面打印、胶装、封面加盖公章"，这应该合并为一条 note（task_type: format），而不是拆成 4 条
- 例如：某一段同时提到"投标保证金5万元、须从基本账户转出、到账截止时间为开标前一日17:00"，合并为一条（task_type: pricing）
- 每个注意事项保留完整的原文段落，包含足够的上下文让人理解
- 按 task_type 正确分类：
  - stamp: 盖章、签字、签章、逐页签字、骑缝章、法定代表人或委托代理人签字
  - format: 份数、正本副本数量、密封、装订方式、封装标记、投标文件组成
  - pricing: 保证金金额/形式/到账截止、保函要求、标书费、报价方式/币种/限价
  - certs: 证书复印件、业绩证明材料、验收报告、社保证明、原件备查、复印件加盖公章
  - qualifications: 承诺函格式、声明函模板、法人证明、授权委托书、信用中国截图、无行贿犯罪证明
  - get_docs: 质疑期限、答疑会时间、踏勘安排、澄清截止、招标文件获取方式
- 按紧急程度标注 priority：urgent（不满足直接废标或拒收）、high（影响评分的关键项）、medium（需要准备的一般项）、low（建议性提醒）

### 4. 输出要求
- 所有字段必须存在，没有信息的字段用空字符串""、空数组[]或null填充
- **不要编造信息**，只提取文档中明确出现的内容
- **不要简写或概括**，保留原文的完整表述
- **资格要求的 detail 字段是最关键的信息源**，必须逐字摘录原文，宁长勿短，不得省略任何限定条件
- qualification_requirements.raw_text 和 scoring_criteria.raw_text 保留原文关键段落（各不超过3000字）
- important_notes 应尽可能完整，不设数量上限，把文档中所有值得投标人注意的事项都列出来
"""


def _build_user_message(full_text: str, company=None) -> str:
    """构建发给 LLM 的 user message：文档正文 + 公司资料摘要"""
    # 截断文档文本控制成本
    text = full_text[:LLM_MAX_CHARS]
    if len(full_text) > LLM_MAX_CHARS:
        text += f"\n\n[文档较长，已截断至 {LLM_MAX_CHARS} 字符。以上内容包含文档前 {LLM_MAX_CHARS} 字符。]"

    parts = ["## 招标文件正文\n\n", text]

    # 附加公司资料供匹配参考和自评打分
    if company:
        company_info = _build_company_summary(company)
        if company_info:
            parts.append("\n\n---\n\n## 公司现有资料（供匹配参考和自评打分）\n\n")
            parts.append(company_info)
            parts.append("\n\n请根据以上公司资料：\n"
                         "1. 在评分标准中为每个评分项评估 self_assessed_score（公司预计得分），并写明 self_assessed_reason\n"
                         "2. 将公司资质与所需证书做匹配（名称或等级匹配即可标记 matched: true）")

    return "".join(parts)


def _build_company_summary(company) -> str:
    """构建公司资料摘要（精简，控制 token 消耗）"""
    lines = []

    quals = company.qualifications or []
    if quals:
        lines.append("### 公司资质")
        for i, q in enumerate(quals[:20]):
            parts = [f"{i+1}. {q.get('name', '')}"]
            if q.get("level"):
                parts.append(f"等级：{q['level']}")
            if q.get("cert_no"):
                parts.append(f"编号：{q['cert_no']}")
            if q.get("issuing_authority"):
                parts.append(f"发证机构：{q['issuing_authority']}")
            lines.append(" | ".join(parts))
        if len(quals) > 20:
            lines.append(f"...共 {len(quals)} 项资质")

    perfs = company.performances or []
    if perfs:
        lines.append("\n### 公司业绩")
        for i, p in enumerate(perfs[:30]):
            parts = [f"{i+1}. {p.get('project_name', '')}"]
            if p.get("contract_amount"):
                parts.append(f"金额：{p['contract_amount']}万元")
            if p.get("contract_date"):
                parts.append(f"日期：{p['contract_date']}")
            if p.get("client_name"):
                parts.append(f"客户：{p['client_name']}")
            if p.get("project_type"):
                parts.append(f"类型：{p['project_type']}")
            lines.append(" | ".join(parts))
        if len(perfs) > 30:
            lines.append(f"...共 {len(perfs)} 项业绩")

    personnel = company.personnel or []
    if personnel:
        lines.append("\n### 公司人员")
        for i, p in enumerate(personnel[:20]):
            parts = [f"{i+1}. {p.get('name', '')}"]
            if p.get("position"):
                parts.append(f"职位：{p['position']}")
            if p.get("certifications"):
                parts.append(f"证书：{p['certifications']}")
            lines.append(" | ".join(parts))
        if len(personnel) > 20:
            lines.append(f"...共 {len(personnel)} 人")

    return "\n".join(lines)


def _build_recommendations_from_llm(scoring: dict, company) -> dict:
    """基于 LLM 返回的评分标准 + 公司资料，用规则引擎做精确匹配推荐

    LLM 负责理解文档（提取评分项、识别要求），推荐匹配仍由规则引擎完成，
    这样可以确保推荐结果与数据库索引精确对应，避免 LLM 编造不存在的记录。
    """
    from services.tender_parser import match_qualifications, match_performances, match_personnel

    recommendations = {
        "qualifications": [],
        "performances": [],
        "personnel": [],
        "generated_at": datetime.utcnow().isoformat(),
    }

    if company:
        try:
            recommendations["qualifications"] = match_qualifications(
                scoring, company.qualifications or []
            )
            recommendations["performances"] = match_performances(
                scoring, company.performances or []
            )
            recommendations["personnel"] = match_personnel(
                scoring, company.personnel or []
            )
        except Exception:
            pass

    return recommendations


def _validate_llm_result(raw: dict) -> dict:
    """校验并修复 LLM 返回的 JSON 结构，确保模板兼容"""
    # 顶层字段
    qual = raw.get("qualification_requirements", {}) or {}
    scoring = raw.get("scoring_criteria", {}) or {}
    notes = raw.get("important_notes", []) or []

    # 修复 qualification_requirements
    qual.setdefault("sealing", {"copies": "", "packaging": "", "requirements_text": ""})
    qual.setdefault("submission", {"deadline": "", "location": "", "method": "", "requirements_text": ""})
    qual.setdefault("stamping", {"requirements": [], "requirements_text": ""})
    qual.setdefault("required_certificates", [])

    # 修复每个 certificate（含新字段：level/issuing_authority/time_range/quantity）
    certs = []
    for c in qual.get("required_certificates", []) or []:
        if isinstance(c, dict):
            c.setdefault("type", "basic")
            c.setdefault("level", "")
            c.setdefault("issuing_authority", "")
            c.setdefault("time_range", "")
            c.setdefault("quantity", "")
            c.setdefault("detail", "")
            c.setdefault("matched", False)
            certs.append(c)
    qual["required_certificates"] = certs

    # 修复每个 commitment（含新字段：format_required）
    commitments = []
    for c in qual.get("required_commitments", []) or []:
        if isinstance(c, dict):
            c.setdefault("detail", "")
            c.setdefault("format_required", "未说明")
            commitments.append(c)
    qual["required_commitments"] = commitments

    # 修复 financial_requirements
    fin = qual.get("financial_requirements", {}) or {}
    fin.setdefault("bid_bond", None)
    fin.setdefault("bid_bond_form", "")
    fin.setdefault("performance_bond", None)
    fin.setdefault("other", "")
    qual["financial_requirements"] = fin

    # 确保 bid_bond 是数字或 None
    if fin["bid_bond"] is not None:
        try:
            fin["bid_bond"] = float(fin["bid_bond"])
        except (ValueError, TypeError):
            fin["bid_bond"] = None

    if fin["performance_bond"] is not None:
        try:
            fin["performance_bond"] = float(fin["performance_bond"])
        except (ValueError, TypeError):
            fin["performance_bond"] = None

    qual.setdefault("raw_text", "")
    raw["qualification_requirements"] = qual

    # 修复 scoring_criteria
    scoring.setdefault("total_points", 100)
    try:
        scoring["total_points"] = int(scoring["total_points"])
    except (ValueError, TypeError):
        scoring["total_points"] = 100

    # 修复每个 scoring item（含新字段：self_assessed_score/self_assessed_reason）
    items = []
    for item in scoring.get("items", []) or []:
        if isinstance(item, dict):
            item.setdefault("category", "other")
            item.setdefault("label", "")
            try:
                item["max_points"] = int(item.get("max_points", 0))
            except (ValueError, TypeError):
                item["max_points"] = 0
            item.setdefault("scoring_method", "")
            item.setdefault("requirements", [])
            # 自评得分：确保是数字且在合理范围
            try:
                sas = int(item.get("self_assessed_score", 0))
            except (ValueError, TypeError):
                sas = 0
            item["self_assessed_score"] = max(0, min(sas, item["max_points"]))
            item.setdefault("self_assessed_reason", "")
            items.append(item)
    scoring["items"] = items

    # 修复自评总分
    try:
        scoring["self_assessed_total"] = int(scoring.get("self_assessed_total", 0))
    except (ValueError, TypeError):
        scoring["self_assessed_total"] = sum(i.get("self_assessed_score", 0) for i in items)

    scoring.setdefault("raw_text", "")
    raw["scoring_criteria"] = scoring

    # 修复 important_notes
    fixed_notes = []
    for note in notes:
        if isinstance(note, dict):
            note.setdefault("text", "")
            note.setdefault("task_type", "certs")
            note.setdefault("priority", "medium")
            fixed_notes.append(note)
    raw["important_notes"] = fixed_notes[:30]

    return raw


async def parse_with_llm(full_text: str, company=None) -> Optional[dict]:
    """使用 LLM 解析招标文件文本

    Args:
        full_text: 文档全文（纯文本）
        company: Company ORM 对象（可选，用于匹配推荐和自评打分）

    Returns:
        tender_analysis 中的解析部分 dict（不含 file_name/file_stored_at/parsed_at），
        失败时返回 None（触发 fallback）
    """
    if not LLM_API_KEY:
        print("[llm] LLM_API_KEY 未配置，跳过 LLM 解析", flush=True)
        return None

    import openai

    client = openai.AsyncOpenAI(
        api_key=LLM_API_KEY,
        base_url=LLM_BASE_URL,
        timeout=120.0,
    )

    try:
        user_message = _build_user_message(full_text, company)
        print(f"[llm] 发送请求到 {LLM_BASE_URL}, model={LLM_MODEL}, "
              f"文档长度={len(full_text)}字符, 截断={min(len(full_text), LLM_MAX_CHARS)}字符", flush=True)

        response = await client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,  # 低温度提高稳定性
            max_tokens=4096,
        )

        usage = response.usage
        print(f"[llm] 请求完成: prompt_tokens={usage.prompt_tokens if usage else '?'}, "
              f"completion_tokens={usage.completion_tokens if usage else '?'}, "
              f"total_tokens={usage.total_tokens if usage else '?'}", flush=True)

        content = response.choices[0].message.content
        if not content:
            print("[llm] 返回内容为空", flush=True)
            return None

        # 清理可能的 markdown 代码块标记
        content = content.strip()
        if content.startswith("```"):
            # 移除 ```json 或 ``` 开头
            first_newline = content.find("\n")
            if first_newline != -1:
                content = content[first_newline + 1:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()

        raw = json.loads(content)
        print(f"[llm] JSON 解析成功, 顶层字段: {list(raw.keys())}", flush=True)

        # 校验修复
        result = _validate_llm_result(raw)

        # 用规则引擎做精确匹配推荐（LLM 不直接输出 recommendations）
        scoring = result.get("scoring_criteria", {})
        result["recommendations"] = _build_recommendations_from_llm(scoring, company)

        # 证书匹配状态（支持新字段 level/issuing_authority）
        _match_certificates(result, company)

        # 附加 token 信息
        if usage:
            result["llm_usage"] = {
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
                "total_tokens": usage.total_tokens,
            }

        return result

    except json.JSONDecodeError as e:
        print(f"[llm] JSON 解析失败: {e}", flush=True)
        print(f"[llm] 原始内容前500字符: {content[:500] if 'content' in dir() else 'N/A'}", flush=True)
        return None
    except openai.APIError as e:
        print(f"[llm] API 错误: {type(e).__name__}: {e}", flush=True)
        return None
    except openai.APITimeoutError:
        print("[llm] 请求超时", flush=True)
        return None
    except Exception as e:
        print(f"[llm] 未知错误: {type(e).__name__}: {e}", flush=True)
        traceback.print_exc()
        return None


def _match_certificates(result: dict, company) -> None:
    """检查 LLM 返回的证书与公司资料是否匹配（支持新字段 level/issuing_authority）"""
    if not company:
        return
    try:
        for cert in result.get("qualification_requirements", {}).get("required_certificates", []):
            cert_name = cert.get("name", "")
            if not cert_name:
                continue
            cert_level = cert.get("level", "")
            cert_authority = cert.get("issuing_authority", "")
            for q in (company.qualifications or []):
                q_name = q.get("name", "")
                q_level = q.get("level", "")
                q_authority = q.get("issuing_authority", "")
                # 名称匹配（包含关系）+ 等级匹配（如存在）
                name_match = cert_name in q_name or q_name in cert_name
                level_match = (not cert_level or cert_level in q_level or q_level in cert_level)
                if name_match and level_match:
                    cert["matched"] = True
                    break
    except Exception:
        pass
