"""大模型招标文件解析服务 —— 三 Agent 架构

Agent C (拆分): 分析全文结构 → 提取招标公告、投标人须知、评标办法章节原文
Agent A (评分): 仅看评标办法章节 → 提取 scoring_criteria（无评分标准时跳过）
Agent B (资格): 仅看招标公告+投标人须知 → 提取 qualification_requirements + important_notes

Agent C 先运行做章节拆分，Agent A+B 通过 asyncio.gather 并行调用。
LLM 为主解析引擎，任一 Agent 失败时该部分回退到规则解析。
"""

import asyncio
import json
import traceback
from datetime import datetime
from typing import Optional

from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, LLM_MAX_CHARS

# ====== Agent C: 章节拆分专用 Prompt ======

SPLIT_PROMPT = """你是招标文件结构分析专家。你只会看到文档开头的目录部分（如有）或正文开头。从目录/开头找出以下三个章节的**确切起始标题文本**（只输出标题，不输出章节内容）。

招标文件通常按此结构组织（章节标题可能是"第X章""X、""X."等格式）：
1. 招标公告/采购公告
2. 投标人须知/投标须知（含前附表）
3. 评标办法/评标办法前附表/评审办法/综合评分

严格返回以下 JSON：

```json
{
  "has_announcement": true,
  "announcement_heading": "正文中招标公告章节的起始标题原文，如'第一章 招标公告'，找不到则为null",
  "has_instructions": true,
  "instructions_heading": "正文中投标人须知章节的起始标题原文，如'第二章 投标人须知'，找不到则为null",
  "has_scoring": true,
  "scoring_heading": "正文中评标办法章节的起始标题原文，如'三、评标办法（综合评分法）'，找不到则为null"
}
```

## 规则
1. **优先从目录识别**：目录中列出了各章节的完整标题和顺序，直接提取即可，忽略页码和引导符（……）
2. heading 取目录中的标题原文，一字不差（后续用它在正文中定位切分位置）
3. 没有目录时，从正文开头逐章扫描标题
4. 标题格式可能是"第X章 XXX""X、XXX""X. XXX"，也可能是独立加粗行
5. 注意区分归属：投标人须知中的资格要求属于 instructions；评标办法中的资格评审属于 scoring
6. 找不到的章节 → has_xxx=false，xxx_heading=null
7. 缩写识别："投标须知"≈"投标人须知"，"评审办法""综合评分"≈"评标办法"
"""

# ====== Agent A: 评分标准专用 Prompt ======

SCORING_PROMPT = """你是招标文件"评标办法"章节的解析专家。只从评标办法/评分标准章节中提取信息。

**评分标准**也称"评标办法""评审办法""综合评分"，可能以表格或自然段落出现。注意"评标办法前附表"表格。

严格返回以下 JSON（只含 scoring_criteria）：

```json
{
  "scoring_criteria": {
    "total_points": "总分(数字)",
    "items": [{
      "depth": "1(大项)/2(子项)/3(孙项)——必须还原招标文件原始层级",
      "score_type": "objective(客观：满足条件即得分) / subjective(主观：评委根据优劣打分)",
      "category": "price/technical/performance/personnel/qualification/other",
      "label": "评分项名称，含原文序号如'1.1'、'（一）'",
      "max_points": "满分(数字)。depth=1的大项填子项合计值",
      "scoring_method": "评分方法详细描述（完整原文，说明如何得分、扣分规则）",
      "requirements": ["具体要求，逐条完整列出"],
      "self_assessed_score": "客观分:基于公司资料预估(0~max_points)；主观分:max_points×0.8取整",
      "self_assessed_reason": "预估依据，一句话。客观分写匹配/缺失项，主观分写'主观分，按满分80%预估'"
    }],
    "self_assessed_total": "所有self_assessed_score之和",
    "raw_text": "评分标准原文段落（≤3000字）"
  }
}
```

## 提取规则

### 层级（depth）
还原招标文件原始层级。例：
- 一、商务部分(30分) → depth=1
  - 1.企业资质(15分) → depth=2
    - (1)ISO认证(5分) → depth=3

**即使只有一层结构，也按大项拆分 depth=1，不能平铺。**

### 主客观（score_type）
- **objective** = 满足硬性条件即得分（资质等级、业绩数量、人员证书、报价公式）
- **subjective** = 评委根据优劣/合理性在范围内打分（技术方案、实施方案）

**防误判：** 业绩/资质/人员/财务类默认判 objective。仅当原文明确出现"评委根据…综合打分""优得X分良得Y分""专家酌情给分"等主观措辞时才判 subjective。

### 自评得分
- 客观分：逐项对比公司资料按规则计算（满足→满分，部分→打折，无→0，报价→0）
- 主观分：max_points × 0.8 取整

### 输出底线
- 所有字段必须存在，缺则用""、[]或 null
- 不编造，不简写，保留原文完整表述
- raw_text 不超过 3000 字
"""

# ====== Agent B: 资格要求 + 注意事项专用 Prompt ======

QUAL_PROMPT = """你是招标文件"招标公告"和"投标人须知"章节的解析专家。只从这两个章节提取信息，不参考其他章节。

**重要：** 文档开头如有"目录"，目录不是正文，不要提取目录内容。

严格返回以下 JSON（含 qualification_requirements 和 important_notes）：

```json
{
  "qualification_requirements": {
    "sealing": {"copies": "正本/副本份数（完整原文）", "packaging": "密封/封装要求（完整原文）", "requirements_text": "原文摘录"},
    "submission": {"deadline": "递交截止时间", "location": "递交地点（完整地址）", "method": "递交方式", "requirements_text": "原文摘录"},
    "stamping": {"requirements": ["盖章签字要求，逐条"], "requirements_text": "原文摘录"},
    "required_certificates": [{
      "name": "证书全称——必须原文完整名称，一字不差。'信用中国网站查询截图'不能写成'信用中国'",
      "type": "basic/professional/financial/other",
      "level": "等级要求，原文摘录，无则空",
      "issuing_authority": "颁发机构全称，无则空",
      "time_range": "时效要求，无则空",
      "quantity": "数量要求，无则空",
      "detail": "【最重要字段】原文逐字摘录全部要求，含所有限定条件，宁长勿短",
      "matched": false
    }],
    "required_commitments": [{
      "name": "承诺函全称——必须原文完整名称。'投标承诺书'不能写成'承诺书'",
      "detail": "格式和内容要求（原文摘录）",
      "format_required": "是/否/未说明"
    }],
    "financial_requirements": {"bid_bond": "投标保证金(万元，数字)或null", "bid_bond_form": "保证金形式", "performance_bond": "履约保证金(万元，数字)或null", "other": "其他财务要求"},
    "raw_text": "资格要求原文摘要（≤3000字）"
  },
  "important_notes": [{
    "text": "注意事项完整原文段落——同一段落的相关要求必须合并为一条，不要拆分",
    "task_type": "stamp/format/pricing/certs/qualifications/get_docs",
    "priority": "urgent(不满足即废标)/high(影响评分)/medium(一般)/low(建议)"
  }]
}
```

**⚠️ important_notes 硬性限制：总共最多 15 条。同一段落、同一个小节的内容必须合并为一条，宁可一条长，不要一堆碎。**

## 提取规则

### 1. 资格要求 —— 严禁简写

**名称完整性（最重要）：** 证书/承诺函的 name 必须与招标文件原文一字不差。
- "信用中国网站查询截图" ≠ "信用中国"
- "投标承诺书" ≠ "承诺书"
- "法定代表人身份证明书" ≠ "法人证明"

**证书 detail 字段：** 逐字摘录原文全部要求（等级/发证机构/数量/时效/金额/专业范围），宁长勿短。
- ❌ "建筑工程施工总承包资质"
- ✅ "具有住房和城乡建设部颁发的建筑工程施工总承包一级及以上资质，且资质证书须在有效期内"

**承诺函 format_required：** 原文提到"格式详见附件""按招标文件提供的格式"→"是"；"格式自拟"→"否"；未提及→"未说明"

**密封/盖章/递交/保证金：** 完整照抄原文。保证金中文大写转数字：
- "伍万元"→5.0, "伍拾万元"→50.0, "壹佰万元"→100.0
- "50000元"→5.0, "1000000元"→100.0

### 2. 重要注意事项 —— 最多15条，按段落合并

| task_type | 涵盖内容 |
|-----------|---------|
| stamp | 盖章、签字、骑缝章、法人/授权人签字 |
| format | 份数、正副本、密封、装订、封装标记 |
| pricing | 保证金、保函、标书费、报价方式/限价 |
| certs | 证书复印件、业绩证明、社保、原件备查 |
| qualifications | 承诺函、声明函、授权书、信用中国、无行贿证明 |
| get_docs | 质疑期、答疑会、踏勘、澄清截止 |

**合并输出流程：**
1. 按章节/段落扫描 → 同一段落的多个要求合并为一条 note
2. 判断该合并段落的 task_type（取主导类型）
3. 标注 priority（urgent=不满足直接废标）
4. 输出前自查：同 task_type 且来源相邻的两条 → 立即合并
5. 最终数量 ≤ 15 条

### 输出底线
- 所有字段必须存在，缺则用""、[]或 null
- 不编造，不简写，保留原文完整表述
- raw_text 不超过 3000 字
"""


# ====== LLM 调用工具 ======

def _clean_json(content: str) -> str:
    """清理 LLM 返回的 JSON（去 markdown 代码块标记）"""
    content = content.strip()
    if content.startswith("```"):
        first_newline = content.find("\n")
        if first_newline != -1:
            content = content[first_newline + 1:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()
    return content


async def _call_llm(client, system_prompt: str, user_message: str, label: str,
                    max_tokens: int = 4096) -> Optional[dict]:
    """单次 LLM 调用，返回解析后的 dict 或 None"""
    import openai

    try:
        print(f"[llm-{label}] 发送请求, 文档{len(user_message)}字符", flush=True)

        response = await client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=max_tokens,
        )

        usage = response.usage
        print(f"[llm-{label}] 完成: prompt={usage.prompt_tokens if usage else '?'}, "
              f"completion={usage.completion_tokens if usage else '?'}, "
              f"total={usage.total_tokens if usage else '?'}", flush=True)

        content = response.choices[0].message.content
        if not content:
            print(f"[llm-{label}] 返回内容为空", flush=True)
            return None

        content = _clean_json(content)
        result = json.loads(content)
        print(f"[llm-{label}] JSON 解析成功, 字段: {list(result.keys())}", flush=True)

        # 附加 token 信息
        if usage:
            result["_usage"] = {
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
                "total_tokens": usage.total_tokens,
            }

        return result

    except json.JSONDecodeError as e:
        print(f"[llm-{label}] JSON 解析失败: {e}", flush=True)
        return None
    except openai.APIError as e:
        print(f"[llm-{label}] API 错误: {type(e).__name__}: {e}", flush=True)
        return None
    except openai.APITimeoutError:
        print(f"[llm-{label}] 请求超时", flush=True)
        return None
    except Exception as e:
        print(f"[llm-{label}] 未知错误: {type(e).__name__}: {e}", flush=True)
        traceback.print_exc()
        return None


# ====== 三个 Agent ======

def _find_heading_line(lines: list, heading: str) -> int | None:
    """在文本行列表中查找标题所在行号（从后往前，避开目录取正文中的标题）

    归一化空白后做包含匹配，从后往前扫优先取正文中的标题。
    """
    heading_norm = ' '.join(heading.split())
    for i in range(len(lines) - 1, -1, -1):
        line_norm = ' '.join(lines[i].split())
        if heading_norm in line_norm:
            return i
    return None


async def _parse_split(client, full_text: str) -> Optional[dict]:
    """Agent C: 识别章节标题 → Python 代码按标题切分原文

    返回 {has_scoring, scoring_text, has_announcement, announcement_text,
            has_instructions, instructions_text} 或 None（失败时）
    """
    if not full_text:
        return None

    # Step 1: LLM 识别章节标题（只看文档开头的目录/正文，不扫全文）
    text = full_text[:8000]
    user_message = f"## 招标文件开头（目录/正文）\n\n{text}"

    headings_result = await _call_llm(client, SPLIT_PROMPT, user_message, "split", max_tokens=1024)
    if headings_result is None:
        return None

    # Step 2: 收集有效标题及其归属类型
    heading_entries = []
    for key, stype in [("announcement_heading", "announcement"),
                        ("instructions_heading", "instructions"),
                        ("scoring_heading", "scoring")]:
        heading = (headings_result.get(key, "") or "").strip()
        if heading and headings_result.get(f"has_{stype}", False):
            heading_entries.append((heading, stype))

    if not heading_entries:
        print("[llm-split] Agent C 未返回任何章节标题", flush=True)
        return None

    # Step 3: 在原文中定位每个标题的行号
    lines = full_text.split('\n')
    heading_positions = []  # [(line_idx, heading_text, section_type), ...]

    for heading, stype in heading_entries:
        line_idx = _find_heading_line(lines, heading)
        if line_idx is not None:
            heading_positions.append((line_idx, heading, stype))
            print(f"[llm-split] 定位 '{heading[:40]}' → 行 {line_idx}", flush=True)
        else:
            print(f"[llm-split] ⚠ 未在正文中找到标题: '{heading[:60]}'", flush=True)

    if not heading_positions:
        print("[llm-split] 所有标题定位失败", flush=True)
        return None

    # Step 4: 按文档出现顺序排序，以相邻标题为边界切分章节
    heading_positions.sort(key=lambda x: x[0])

    MAX_SECTION_CHARS = 20000
    result = {
        "has_scoring": False, "scoring_text": "",
        "has_announcement": False, "announcement_text": "",
        "has_instructions": False, "instructions_text": "",
    }

    for idx, (line_idx, heading, stype) in enumerate(heading_positions):
        # 结束于下一个定位到的标题行（或文末）
        if idx + 1 < len(heading_positions):
            end_line = heading_positions[idx + 1][0]
        else:
            end_line = len(lines)

        section_text = '\n'.join(lines[line_idx:end_line])

        # 截断过长章节（优先保留前部）
        if len(section_text) > MAX_SECTION_CHARS:
            section_text = section_text[:MAX_SECTION_CHARS]
            print(f"[llm-split] 章节 '{heading[:30]}' 过长({len(section_text)}字符)，已截断", flush=True)

        if stype == "announcement":
            result["has_announcement"] = True
            result["announcement_text"] = section_text
        elif stype == "instructions":
            result["has_instructions"] = True
            result["instructions_text"] = section_text
        elif stype == "scoring":
            result["has_scoring"] = True
            result["scoring_text"] = section_text

    print(f"[llm-split] 切分完成: 公告={result['has_announcement']}({len(result['announcement_text'])}字符), "
          f"须知={result['has_instructions']}({len(result['instructions_text'])}字符), "
          f"评分={result['has_scoring']}({len(result['scoring_text'])}字符)", flush=True)

    return result


async def _parse_scoring(client, scoring_text: str, company=None) -> Optional[dict]:
    """Agent A: 解析评分标准（仅看评标办法章节）"""
    if not scoring_text:
        return None

    parts = ["## 招标文件 - 评标办法章节\n\n", scoring_text[:LLM_MAX_CHARS]]

    if company:
        company_info = _build_company_summary(company)
        if company_info:
            parts.append("\n\n---\n\n## 公司现有资料（供自评打分参考）\n\n")
            parts.append(company_info)
            parts.append("\n\n请根据公司资料为每个评分项评估 self_assessed_score 和 self_assessed_reason。")

    user_message = "".join(parts)
    return await _call_llm(client, SCORING_PROMPT, user_message, "scoring")


async def _parse_qualification(client, qual_text: str, company=None) -> Optional[dict]:
    """Agent B: 解析资格要求 + 注意事项（仅看招标公告+投标人须知）"""
    if not qual_text:
        return None

    text = qual_text[:LLM_MAX_CHARS]
    parts = ["## 招标公告 + 投标人须知\n\n", text]

    if company:
        company_info = _build_qual_company_summary(company)
        if company_info:
            parts.append("\n\n---\n\n## 公司现有资质（供证书匹配参考）\n\n")
            parts.append(company_info)
            parts.append("\n\n请将公司资质与所需证书做匹配（名称或等级匹配即可标记 matched: true）。")

    user_message = "".join(parts)
    return await _call_llm(client, QUAL_PROMPT, user_message, "qual")


# ====== 公司资料摘要 ======

def _build_company_summary(company) -> str:
    """构建公司资料摘要（评分 Agent 用：含资质/业绩/人员）"""
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


def _build_qual_company_summary(company) -> str:
    """构建公司资质摘要（资格 Agent 用：仅资质，更精简）"""
    quals = company.qualifications or []
    if not quals:
        return ""

    lines = []
    for i, q in enumerate(quals[:20]):
        parts = [f"{i+1}. {q.get('name', '')}"]
        if q.get("level"):
            parts.append(f"等级：{q['level']}")
        if q.get("issuing_authority"):
            parts.append(f"发证机构：{q['issuing_authority']}")
        lines.append(" | ".join(parts))
    if len(quals) > 20:
        lines.append(f"...共 {len(quals)} 项资质")

    return "\n".join(lines)


# ====== 结果校验 ======

def _validate_llm_result(raw: dict) -> dict:
    """校验并修复合并后的 JSON 结构，确保模板兼容"""
    qual = raw.get("qualification_requirements", {}) or {}
    scoring = raw.get("scoring_criteria", {}) or {}
    notes = raw.get("important_notes", []) or []

    # --- qualification_requirements ---
    qual.setdefault("sealing", {"copies": "", "packaging": "", "requirements_text": ""})
    qual.setdefault("submission", {"deadline": "", "location": "", "method": "", "requirements_text": ""})
    qual.setdefault("stamping", {"requirements": [], "requirements_text": ""})
    qual.setdefault("required_certificates", [])

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

    commitments = []
    for c in qual.get("required_commitments", []) or []:
        if isinstance(c, dict):
            c.setdefault("detail", "")
            c.setdefault("format_required", "未说明")
            commitments.append(c)
    qual["required_commitments"] = commitments

    fin = qual.get("financial_requirements", {}) or {}
    fin.setdefault("bid_bond", None)
    fin.setdefault("bid_bond_form", "")
    fin.setdefault("performance_bond", None)
    fin.setdefault("other", "")
    qual["financial_requirements"] = fin

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

    # --- scoring_criteria ---
    scoring.setdefault("total_points", 100)
    try:
        scoring["total_points"] = int(scoring["total_points"])
    except (ValueError, TypeError):
        scoring["total_points"] = 100

    items = []
    for item in scoring.get("items", []) or []:
        if isinstance(item, dict):
            item.setdefault("category", "other")
            item.setdefault("label", "")
            item.setdefault("score_type", "objective")
            item.setdefault("depth", 1)
            try:
                item["depth"] = int(item["depth"])
            except (ValueError, TypeError):
                item["depth"] = 1
            try:
                item["max_points"] = int(item.get("max_points", 0))
            except (ValueError, TypeError):
                item["max_points"] = 0
            item.setdefault("scoring_method", "")
            item.setdefault("requirements", [])
            try:
                sas = int(item.get("self_assessed_score", 0))
            except (ValueError, TypeError):
                sas = 0
            item["self_assessed_score"] = max(0, min(sas, item["max_points"]))
            item.setdefault("self_assessed_reason", "")
            items.append(item)
    scoring["items"] = items

    try:
        scoring["self_assessed_total"] = int(scoring.get("self_assessed_total", 0))
    except (ValueError, TypeError):
        scoring["self_assessed_total"] = sum(i.get("self_assessed_score", 0) for i in items)

    scoring.setdefault("raw_text", "")
    raw["scoring_criteria"] = scoring

    # --- important_notes ---
    fixed_notes = []
    for note in notes:
        if isinstance(note, dict):
            note.setdefault("text", "")
            note.setdefault("task_type", "certs")
            note.setdefault("priority", "medium")
            fixed_notes.append(note)
    raw["important_notes"] = fixed_notes[:30]

    return raw


# ====== 推荐匹配（规则引擎） ======

def _build_recommendations_from_llm(scoring: dict, company) -> dict:
    """基于 LLM 返回的评分标准 + 公司资料，用规则引擎做精确匹配推荐"""
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


def _match_certificates(result: dict, company) -> None:
    """检查 LLM 返回的证书与公司资料是否匹配"""
    if not company:
        return
    try:
        for cert in result.get("qualification_requirements", {}).get("required_certificates", []):
            cert_name = cert.get("name", "")
            if not cert_name:
                continue
            cert_level = cert.get("level", "")
            for q in (company.qualifications or []):
                q_name = q.get("name", "")
                q_level = q.get("level", "")
                name_match = cert_name in q_name or q_name in cert_name
                level_match = (not cert_level or cert_level in q_level or q_level in cert_level)
                if name_match and level_match:
                    cert["matched"] = True
                    break
    except Exception:
        pass


# ====== 编排函数（对外入口） ======

async def parse_with_llm(full_text: str, company=None) -> Optional[dict]:
    """三 Agent 协作解析招标文件

    1. Agent C 先运行：分析全文结构，拆分出招标公告、投标人须知、评标办法
    2. Agent A + Agent B 并行运行（无评分标准时跳过 A）
    3. 合并结果 + 校验 + 推荐匹配

    Returns:
        tender_analysis JSON dict（不含 file_name 等元信息），
        完全失败时返回 None（触发规则 fallback）
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

    # ===== Step 1: Agent C 拆分文档 =====
    print(f"[llm] Agent C 开始拆分文档, model={LLM_MODEL}", flush=True)
    split_result = await _parse_split(client, full_text)

    if split_result is None:
        print("[llm] Agent C 拆分失败，回退：A/B 均使用全文", flush=True)
        scoring_text = full_text
        qual_text = full_text
        has_scoring = True  # 让 Agent A 自己判断
    else:
        scoring_text = split_result.get("scoring_text", "") or ""
        has_scoring = split_result.get("has_scoring", False) and bool(scoring_text)

        ann_text = split_result.get("announcement_text", "") or ""
        ins_text = split_result.get("instructions_text", "") or ""
        qual_text = (ann_text + "\n\n" + ins_text).strip()

        if not qual_text:
            print("[llm] Agent C 未找到公告/须知章节，回退全文给 Agent B", flush=True)
            qual_text = full_text[:LLM_MAX_CHARS]
        else:
            print(f"[llm] Agent C 拆分完成: 公告{len(ann_text)}字符, "
                  f"须知{len(ins_text)}字符, 评分{len(scoring_text)}字符", flush=True)

        if not has_scoring:
            print("[llm] Agent C 未检测到评分标准章节，跳过 Agent A", flush=True)

    # ===== Step 2: Agent A + Agent B 并行 =====
    scoring_coro = _parse_scoring(client, scoring_text, company) if has_scoring and scoring_text else None
    qual_coro = _parse_qualification(client, qual_text, company)

    if scoring_coro:
        print(f"[llm] 启动 Agent A(评分) + Agent B(资格) 并行解析", flush=True)
        scoring_result, qual_result = await asyncio.gather(scoring_coro, qual_coro)
    else:
        print(f"[llm] 仅运行 Agent B(资格)", flush=True)
        scoring_result = None
        qual_result = await qual_coro

    # ===== Step 3: 检查结果 =====
    if scoring_result is None and qual_result is None:
        print("[llm] Agent A 和 B 均失败，回退规则解析", flush=True)
        return None

    # ===== Step 4: 合并 =====
    merged = {}
    total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    if scoring_result:
        usage = scoring_result.pop("_usage", None)
        merged.update(scoring_result)
        if usage:
            for k in total_usage:
                total_usage[k] += usage.get(k, 0)
        print(f"[llm] Agent A (评分) 成功", flush=True)
    else:
        print("[llm] Agent A (评分) 无结果，评分部分将为空", flush=True)
        merged.setdefault("scoring_criteria", {"total_points": 100, "items": [], "raw_text": ""})

    if qual_result:
        usage = qual_result.pop("_usage", None)
        merged.update(qual_result)
        if usage:
            for k in total_usage:
                total_usage[k] += usage.get(k, 0)
        print(f"[llm] Agent B (资格+注意事项) 成功", flush=True)
    else:
        print("[llm] Agent B (资格+注意事项) 失败，资格部分将为空", flush=True)
        merged.setdefault("qualification_requirements", {})
        merged.setdefault("important_notes", [])

    # ===== Step 5: 校验 + 推荐匹配 =====
    result = _validate_llm_result(merged)

    scoring = result.get("scoring_criteria", {})
    result["recommendations"] = _build_recommendations_from_llm(scoring, company)

    _match_certificates(result, company)

    if total_usage["total_tokens"] > 0:
        result["llm_usage"] = total_usage

    print(f"[llm] 三 Agent 解析完成, 总 tokens={total_usage['total_tokens']}", flush=True)
    return result
