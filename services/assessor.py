"""投标评估引擎"""
from datetime import datetime
from typing import Optional
from config import ASSESSMENT_WEIGHTS, RECOMMEND_THRESHOLD_HIGH, RECOMMEND_THRESHOLD_LOW


def assess_notice(notice, company) -> dict:
    """
    对标讯进行评分
    notice: BidNotice 对象
    company: Company 对象（可为 None）
    返回: assessment dict
    """
    if not company:
        return {
            "total_score": 0,
            "qual_score": 0, "perf_score": 0,
            "personnel_score": 0, "financial_score": 0, "other_score": 0,
            "recommendation": "not_recommend",
            "risk_notes": "请先完善公司资料",
            "missing_requirements": [],
            "assessed_at": datetime.utcnow().isoformat(),
        }

    w = ASSESSMENT_WEIGHTS

    # 1. 资质匹配 (40%)
    qual_score = _calc_qualification_score(notice, company)

    # 2. 业绩匹配 (25%)
    perf_score = _calc_performance_score(notice, company)

    # 3. 人员匹配 (15%)
    personnel_score = _calc_personnel_score(notice, company)

    # 4. 财务能力 (10%)
    financial_score = _calc_financial_score(notice, company)

    # 5. 其他因素 (10%)
    other_score = 0
    missing = []

    # 平台注册
    if notice.platform_registration_required:
        if notice.platform_name:
            other_score += 3
        else:
            other_score += 0
            missing.append("需要平台注册，请确认已有账号")
    else:
        other_score += 3  # 不需要平台注册 = 加分

    # 标书费
    if notice.bid_document_fee is not None and notice.bid_document_fee > 5000:
        other_score += 0
        missing.append(f"标书费较高 ({notice.bid_document_fee}元)")
    else:
        other_score += 1

    # 期限合理性（有足够准备时间）
    if notice.bid_deadline:
        days_left = (notice.bid_deadline - datetime.utcnow()).days
        if days_left >= 15:
            other_score += 3
        elif days_left >= 7:
            other_score += 1
            missing.append(f"距投标截止仅 {days_left} 天，时间紧张")
        else:
            other_score += 0
            missing.append(f"距投标截止仅 {days_left} 天，时间紧迫")
    else:
        other_score += 0
        missing.append("缺少投标截止日期")

    # 区域（假设公司地址能匹配）
    if notice.project_location and company.address:
        if notice.project_location[:2] == company.address[:2]:
            other_score += 2
        else:
            other_score += 0

    # 联系信息
    if notice.contact_phone or notice.contact_person:
        other_score += 1

    total_score = qual_score + perf_score + personnel_score + financial_score + other_score
    total_score = round(min(total_score, 100), 1)

    if total_score >= RECOMMEND_THRESHOLD_HIGH:
        recommendation = "recommend"
    elif total_score >= RECOMMEND_THRESHOLD_LOW:
        recommendation = "consider"
    else:
        recommendation = "not_recommend"

    return {
        "total_score": total_score,
        "qual_score": round(qual_score, 1),
        "perf_score": round(perf_score, 1),
        "personnel_score": round(personnel_score, 1),
        "financial_score": round(financial_score, 1),
        "other_score": round(other_score, 1),
        "recommendation": recommendation,
        "risk_notes": "；".join(missing) if missing else "无明显风险",
        "missing_requirements": missing,
        "assessed_at": datetime.utcnow().isoformat(),
    }


def _calc_qualification_score(notice, company) -> float:
    """计算资质匹配得分 (满分40)"""
    req_text = notice.qualification_requirements or ""
    if not req_text.strip():
        return 25  # 没有明确要求，给中等分

    quals = company.qualifications or []
    if not quals:
        return 5

    # 简单关键词匹配
    keywords = ["资质", "证书", "许可证", "认证", "ISO", "检验", "检测", "代理"]
    required_count = 0
    matched_count = 0

    for kw in keywords:
        if kw in req_text:
            required_count += 1

    if required_count == 0:
        return 25

    for kw in keywords:
        if kw in req_text:
            # 检查公司是否有此关键词相关的资质
            for q in quals:
                qual_text = f"{q.get('name', '')} {q.get('level', '')} {q.get('issuing_authority', '')}"
                if kw in qual_text or kw in q.get('name', ''):
                    matched_count += 1
                    break

    if required_count == 0:
        return 25
    return min(matched_count / required_count, 1.0) * 40


def _calc_performance_score(notice, company) -> float:
    """计算业绩匹配得分 (满分25)"""
    perfs = company.performances or []
    if not perfs:
        return 5

    # 按合同金额评分
    amounts = [p.get("contract_amount", 0) for p in perfs if p.get("contract_amount")]
    if notice.budget_amount and amounts:
        similar_count = sum(1 for a in amounts if a >= notice.budget_amount * 0.3)
        return min(similar_count / 2, 1.0) * 25

    # 有业绩基础分
    return min(len(perfs) * 5, 20)


def _calc_personnel_score(notice, company) -> float:
    """计算人员匹配得分 (满分15)"""
    people = company.personnel or []
    if not people:
        return 3

    # 人员数量 + 证书覆盖度
    cert_count = 0
    for p in people:
        certs = p.get("certifications", "")
        if certs:
            cert_count += len(certs.split(","))

    score = min(len(people) * 3, 10) + min(cert_count * 2, 5)
    return min(score, 15)


def _calc_financial_score(notice, company) -> float:
    """计算财务能力得分 (满分10)"""
    bank = company.bank_info or {}
    if not bank or not bank.get("account_no"):
        return 3

    # 有完整银行信息 = 基础分
    score = 5

    # 有税号 = 加分
    if bank.get("tax_no"):
        score += 2

    # 注册资本（从银行信息推断，或直接用文本字段）
    # 简化：有账户即可
    return min(score, 10)
