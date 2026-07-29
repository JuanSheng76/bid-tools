"""生成可重复执行的历史投标结果演示数据。

仅替换 external_id 以 DEMO-RESULT- 开头的标讯及其结果，
不会修改用户已有的标讯、任务或结果。
"""

import json
import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path


DB_PATH = Path(__file__).with_name("bid_tools.db")
DEMO_PREFIX = "DEMO-RESULT-"
OUR_COMPANY = "测试科技有限公司"

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

COMPETITORS = [
    "华测新能源技术有限公司",
    "中检能源科技有限公司",
    "国能检测认证中心",
    "华东电力试验研究院",
    "中科光伏检测有限公司",
]

DEMO_LOCATIONS = ["北京市", "上海市", "广州市", "深圳市", "线上"]

LOSS_REASONS = [
    "综合评分排名第二，商务分略低",
    "报价高于中标单位，价格分失分",
    "项目团队同类业绩得分不足",
    "技术方案响应深度不足",
    "本地服务能力评分偏低",
]


def db_datetime(value: datetime | None) -> str | None:
    return value.isoformat(sep=" ", timespec="seconds") if value else None


def replace_demo_results() -> dict[str, int]:
    connection = sqlite3.connect(DB_PATH)
    connection.execute("PRAGMA foreign_keys = ON")

    try:
        with connection:
            demo_notice_ids = [
                row[0]
                for row in connection.execute(
                    "SELECT id FROM bid_notices WHERE external_id LIKE ?",
                    (DEMO_PREFIX + "%",),
                )
            ]
            if demo_notice_ids:
                placeholders = ",".join("?" for _ in demo_notice_ids)
                connection.execute(
                    f"DELETE FROM bid_results WHERE notice_id IN ({placeholders})",
                    demo_notice_ids,
                )
                connection.execute(
                    f"DELETE FROM bid_notices WHERE id IN ({placeholders})",
                    demo_notice_ids,
                )

            for index, (opening_text, title, location, budget, outcome) in enumerate(
                HISTORICAL_BIDS, 1
            ):
                # 演示项目地点固定按北、上、广、深、线上循环，便于筛选和展示。
                location = DEMO_LOCATIONS[(index - 1) % len(DEMO_LOCATIONS)]
                opening_location = (
                    "线上开标（远程不见面开标）"
                    if location == "线上"
                    else f"{location}公共资源交易中心"
                )
                opening = datetime.strptime(opening_text, "%Y-%m-%d").replace(
                    hour=9, minute=30
                )
                notice_id = str(
                    uuid.uuid5(
                        uuid.NAMESPACE_URL,
                        f"bid-tools/{DEMO_PREFIX}{index:03d}",
                    )
                )
                result_id = str(
                    uuid.uuid5(
                        uuid.NAMESPACE_URL,
                        f"bid-tools/result/{DEMO_PREFIX}{index:03d}",
                    )
                )
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
                    note = "[演示数据] 项目顺利中标，合同信息已归档。"
                elif outcome == "lost":
                    winning_company = COMPETITORS[index % len(COMPETITORS)]
                    winning_amount = round(
                        our_quote * (0.91 + (index % 3) * 0.015), 2
                    )
                    contract_signed = None
                    contract_expiry = None
                    contract_amount = None
                    loss_reason = LOSS_REASONS[index % len(LOSS_REASONS)]
                    note = "[演示数据] 已完成投标复盘并记录改进建议。"
                elif outcome == "rejected":
                    winning_company = COMPETITORS[index % len(COMPETITORS)]
                    winning_amount = round(budget * 0.84, 2)
                    contract_signed = None
                    contract_expiry = None
                    contract_amount = None
                    loss_reason = "资格审查未通过，响应文件存在非实质性偏差"
                    note = "[演示数据] 废标案例，用于资质文件复核培训。"
                else:
                    winning_company = ""
                    winning_amount = None
                    contract_signed = None
                    contract_expiry = None
                    contract_amount = None
                    loss_reason = "采购计划调整，项目终止招标"
                    note = "[演示数据] 招标人取消采购，未进入定标阶段。"

                quotes = []
                for quote_index in range(min(participant_count - 1, 4)):
                    factor = 0.82 + (
                        (index + quote_index * 2) % 9
                    ) * 0.018
                    quotes.append(
                        {
                            "company": COMPETITORS[
                                (index + quote_index) % len(COMPETITORS)
                            ],
                            "quote": round(budget * factor, 2),
                        }
                    )

                connection.execute(
                    """
                    INSERT INTO bid_notices (
                        id, source_id, source_url, external_id, title,
                        publishing_date, registration_deadline, bid_deadline,
                        bid_opening_date, bid_opening_location, budget_amount,
                        bid_document_fee, bid_bond_amount, project_location,
                        project_scope, qualification_requirements,
                        platform_registration_required, platform_name,
                        contact_person, contact_phone, contact_email,
                        raw_content, status, bid_decision, is_manual, assessment,
                        created_at, updated_at, abandon_reason, tender_analysis
                    ) VALUES (
                        ?, NULL, '', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        0, '', '', '', '', '', 'completed', 'bid', 1, NULL,
                        ?, ?, '', NULL
                    )
                    """,
                    (
                        notice_id,
                        f"{DEMO_PREFIX}{index:03d}",
                        title,
                        db_datetime(publishing),
                        db_datetime(registration),
                        db_datetime(deadline),
                        db_datetime(opening),
                        opening_location,
                        budget,
                        300.0,
                        round(budget * 0.02, 2),
                        location,
                        "新能源及光伏项目第三方检测、评估与技术服务。",
                        "具备相关检验检测资质、同类项目业绩及专业技术团队。",
                        db_datetime(created),
                        db_datetime(created),
                    ),
                )

                result_created = opening + timedelta(days=2)
                connection.execute(
                    """
                    INSERT INTO bid_results (
                        id, notice_id, opening_date, participant_count,
                        our_quote, competitor_quotes, result, winning_company,
                        winning_amount, result_url, contract_signed_date,
                        contract_expiry_date, contract_amount, loss_reason,
                        notes, created_at, updated_at
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?, ?, ?, ?, ?
                    )
                    """,
                    (
                        result_id,
                        notice_id,
                        db_datetime(opening),
                        participant_count,
                        our_quote,
                        json.dumps(quotes, ensure_ascii=False),
                        outcome,
                        winning_company,
                        winning_amount,
                        db_datetime(contract_signed),
                        db_datetime(contract_expiry),
                        contract_amount,
                        loss_reason,
                        note,
                        db_datetime(result_created),
                        db_datetime(result_created),
                    ),
                )

        summary = dict(
            connection.execute(
                """
                SELECT result, COUNT(*)
                FROM bid_results
                WHERE notice_id IN (
                    SELECT id FROM bid_notices WHERE external_id LIKE ?
                )
                GROUP BY result
                """,
                (DEMO_PREFIX + "%",),
            ).fetchall()
        )
        return summary
    finally:
        connection.close()


if __name__ == "__main__":
    result_summary = replace_demo_results()
    print(f"已生成 {sum(result_summary.values())} 条历史投标结果：{result_summary}")
