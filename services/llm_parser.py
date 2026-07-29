"""大模型招标文件解析服务 —— 双 Agent 架构

Agent A (评分): 仅看评标办法章节 → 提取 scoring_criteria
Agent B (资格): 看全文 → 提取 qualification_requirements + important_notes

两个 Agent 通过 asyncio.gather 并行调用，结果合并后校验。
LLM 为主解析引擎，任一 Agent 失败时该部分回退到规则解析。
"""

import asyncio
import json
import re
import traceback
from datetime import datetime
from typing import Optional

from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, LLM_MAX_CHARS

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

QUAL_PROMPT = """你是招标文件"投标人须知"和"招标公告"章节的解析专家。从全文提取资格要求和重要注意事项。

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

# ====== 章节切分 ======

# 评分标准章节的锚定正则（按优先级排列）
_SCORING_ANCHOR_PATTERNS = [
    re.compile(r'[一二三四五六七八九十]+、\s*评[标审]'),         # 三、评标办法
    re.compile(r'第[一二三四五六七八九十\d]+章[^。\n]{0,10}评[标审]'),  # 第三章 评标办法
    re.compile(r'\d+[\.\、]\s*评[标审]'),                        # 3. 评标办法
    re.compile(r'评[标审]办法'),                                   # 最宽泛兜底
]

# 评分章节结束锚定（遇到这些标题说明评分章节已过）
_SCORING_END_PATTERNS = re.compile(
    r'(第[一二三四五六七八九十\d]+章|'
    r'[一二三四五六七八九十]+、)\s*'
    r'(合同|投标文件格式|附件|工程量|图纸|技术标准|供货要求)'
)


def _split_chapters(full_text: str) -> tuple[str, str]:
    """切分文档：返回 (scoring_text, qual_text)

    scoring_text: 评分标准相关章节（供 Agent A 聚焦）
    qual_text:   全文（供 Agent B 提取资格+注意事项，看全文更安全）

    如果切分失败（找不到评分章节），两者都返回全文。
    """
    lines = full_text.split('\n')

    # Step 1: 找评分章节起始行
    anchor_idx = None
    for i, line in enumerate(lines):
        for pat in _SCORING_ANCHOR_PATTERNS:
            if pat.search(line):
                anchor_idx = i
                break
        if anchor_idx is not None:
            break

    if anchor_idx is None:
        print("[llm-split] 未找到评分标准章节锚点，两 Agent 均使用全文", flush=True)
        return full_text, full_text

    # Step 2: 找评分章节结束行
    scoring_end = len(lines)
    for i in range(anchor_idx + 1, min(len(lines), anchor_idx + 300)):
        if _SCORING_END_PATTERNS.search(lines[i]):
            scoring_end = i
            break

    # Step 3: 提取评分区（带前后各 3 行的缓冲区）
    start = max(0, anchor_idx - 3)
    end = min(len(lines), scoring_end + 3)
    scoring_text = '\n'.join(lines[start:end])

    print(f"[llm-split] 评分章节定位: 行 {anchor_idx}→{scoring_end} "
          f"(共{len(lines)}行), 截取{start}→{end}, {len(scoring_text)}字符", flush=True)

    # Agent B 始终看全文（注意事项分布在各处，不全看会漏）
    # 但如果全文太长，截取到 LLM_MAX_CHARS
    qual_text = full_text

    return scoring_text, qual_text


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


async def _call_llm(client, system_prompt: str, user_message: str, label: str) -> Optional[dict]:
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
            max_tokens=4096,
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


# ====== 两个 Agent ======

async def _parse_scoring(client, scoring_text: str, company=None) -> Optional[dict]:
    """Agent A: 解析评分标准"""
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
    """Agent B: 解析资格要求 + 注意事项"""
    if not qual_text:
        return None

    text = qual_text[:LLM_MAX_CHARS]
    parts = ["## 招标文件正文\n\n", text]

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
    """双 Agent 并行解析招标文件

    - Agent A: 聚焦评标办法章节 → scoring_criteria
    - Agent B: 全文 → qualification_requirements + important_notes
    - 两个 Agent 通过 asyncio.gather 并行调用
    - 任一 Agent 失败不阻塞另一个

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

    # 切分章节
    scoring_text, qual_text = _split_chapters(full_text)

    # 并行调用两个 Agent
    print(f"[llm] 启动双 Agent 并行解析, model={LLM_MODEL}", flush=True)
    scoring_task = _parse_scoring(client, scoring_text, company)
    qual_task = _parse_qualification(client, qual_text, company)

    scoring_result, qual_result = await asyncio.gather(scoring_task, qual_task)

    # 检查结果
    if scoring_result is None and qual_result is None:
        print("[llm] 两个 Agent 均失败，回退规则解析", flush=True)
        return None

    # 合并
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
        print("[llm] Agent A (评分) 失败，评分部分将为空", flush=True)
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

    # 校验修复
    result = _validate_llm_result(merged)

    # 规则引擎匹配推荐
    scoring = result.get("scoring_criteria", {})
    result["recommendations"] = _build_recommendations_from_llm(scoring, company)

    # 证书匹配
    _match_certificates(result, company)

    # 附加合并后的 token 信息
    if total_usage["total_tokens"] > 0:
        result["llm_usage"] = total_usage

    print(f"[llm] 双 Agent 解析完成, 总 tokens={total_usage['total_tokens']}", flush=True)
    return result
