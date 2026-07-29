# 招标文件解析与智能推荐

## 概述

在确定投标并获取招标文件后，系统解析招标文件内容，提取资格要求、评分项，推荐匹配的公司业绩/人员，并提炼注意事项到任务清单。

## 用户确认

- **上传方式**：网页上传（标讯详情页选择文件）
- **文件格式**：.docx + .pdf 双格式
- **解析方式**：纯规则匹配（章节标题关键词定位 + 正则提取）

---

## 数据模型

### BidNotice 新增字段

```python
# models.py
tender_analysis = Column(JSON, nullable=True)
```

### tender_analysis JSON 结构

```json
{
  "file_name": "XX光伏电站招标文件.docx",
  "file_stored_at": "uploads/tenders/{notice_id}/xxx.docx",
  "parsed_at": "2026-07-29T10:30:00",
  "parse_version": 1,

  "qualification_requirements": {
    "sealing": {"copies": "", "packaging": "", "requirements_text": ""},
    "submission": {"deadline": "", "location": "", "method": "", "requirements_text": ""},
    "stamping": {"requirements": [], "requirements_text": ""},
    "required_certificates": [
      {"name": "营业执照", "type": "basic", "detail": "", "matched": true}
    ],
    "required_commitments": [
      {"name": "诚信承诺函", "detail": ""}
    ],
    "financial_requirements": {
      "bid_bond": 50.0, "bid_bond_form": "", "performance_bond": null, "other": ""
    },
    "raw_text": "..."
  },

  "scoring_criteria": {
    "total_points": 100,
    "items": [
      {
        "category": "price|technical|performance|personnel|qualification|other",
        "label": "投标报价",
        "max_points": 30,
        "scoring_method": "...",
        "requirements": []
      }
    ],
    "raw_text": "..."
  },

  "recommendations": {
    "qualifications": [{"from_db_index": 0, "name": "...", "level": "...", "match_score": 1.0}],
    "performances": [{"from_db_index": 0, "project_name": "...", "match_score": 0.9, "contract_amount": 120, "contract_date": "2024-03", "client_name": "..."}],
    "personnel": [{"from_db_index": 0, "name": "...", "match_score": 0.95, "position": "...", "certifications": "..."}],
    "generated_at": "..."
  },

  "important_notes": [
    {"text": "逐页加盖公章", "task_type": "stamp", "priority": "urgent"}
  ]
}
```

---

## 新增/修改文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `requirements.txt` | 修改 | +`python-docx>=1.1` +`pdfplumber>=0.11` |
| `models.py` | 修改 | BidNotice 加 `tender_analysis` JSON 列 |
| `database.py` | 修改 | `_migrate()` 添加 tender_analysis 迁移 |
| `services/tender_parser.py` | **新增** | 核心解析服务 |
| `routers/tender.py` | **新增** | 上传/解析/推荐/同步路由 |
| `main.py` | 修改 | 注册 tender router |
| `templates/tender/analysis_card.html` | **新增** | HTMX 局部加载分析卡片 |
| `templates/tender/recommend.html` | **新增** | 推荐选择完整页 |
| `templates/notices/detail.html` | 修改 | 操作栏加"上传招标文件"按钮 + 分析卡片区域 |

---

## services/tender_parser.py 设计

### 章节检测

```python
SECTION_KEYWORDS = {
    "bidder_instructions": ["投标人须知", "投标须知", "供应商须知", "须知前附表"],
    "qualification": ["资格要求", "投标人资格", "资格条件", "资格审查", "合格投标人"],
    "scoring": ["评分办法", "评分标准", "评标办法", "评审办法", "评审标准", "综合评分", "评分细则"],
    "bid_doc_format": ["投标文件格式", "投标文件组成", "投标文件编制", "响应文件格式"],
    "project_requirements": ["项目需求", "技术规格", "服务要求", "采购需求", "招标范围"],
}

def locate_sections(doc) -> dict  # 返回 {section_key: (start_idx, end_idx)}
def _is_section_heading(para, keywords) -> bool  # 检查 Heading 样式 + 关键词匹配
```

### .docx 解析

```python
async def parse_tender_docx(file_path: str, original_filename: str, company=None) -> dict:
    """主入口：解析 .docx 招标文件，返回完整 tender_analysis dict"""
```

### .pdf 解析（pdfplumber）

```python
async def parse_tender_pdf(file_path: str, original_filename: str, company=None) -> dict:
    """主入口：解析 .pdf 招标文件
    策略：pdfplumber 提取所有文本 + 表格 → 用同样的正则/关键词规则解析
    注意：pdfplumber 无 Heading 样式概念，依赖字号+加粗判断章节标题
    """
```

### 资格要求提取

通过表格解析 + 正则关键词匹配：
- `_parse_qualification_table(table)` — 解析资格条件表格（序号|项目|要求）
- `_extract_certificates_from_text(text)` — 证书关键词：`资质|证书|许可证|认证|ISO|检验|检测`
- `_extract_commitments_from_text(text)` — 承诺函关键词：`承诺函|声明函|承诺书|声明|证明`
- `_extract_sealing/stamping/submission_requirements(text)` — 密封/盖章/递交关键词
- `_extract_financial_requirements(text)` — 保证金关键词：`保证金|保函|[0-9]+万`

### 评分标准提取

核心策略：表格解析（评分表常见格式：序号|评分项|分值|评分标准）
- `_parse_scoring_table(table)` — 解析评分汇总表
- `_infer_scoring_category(text)` — 归类到 price/technical/performance/personnel/qualification
- `_extract_performance_requirements(text)` — 提取项目数/金额/时间/类型要求
- `_extract_personnel_requirements(text)` — 提取证书/人数/年限要求

### 注意事项提取

```python
def extract_important_notes(full_text: str) -> list[dict]:
    """全局扫描，用关键词+正则提取可执行注意事项，映射到 task_type"""
```

task_type 映射关键词：

| task_type | 触发词 |
|-----------|--------|
| stamp | 盖章、签字、签章、逐页、骑缝 |
| format | 份数、正本、副本、密封、装订、封装 |
| pricing | 保证金、保函、到账、标书费 |
| certs | 证书复印件、业绩证明、验收报告、社保证明 |
| qualifications | 承诺函格式、声明函、法人证明、授权委托书 |
| get_docs | 质疑期限、答疑、踏勘、澄清 |

### 匹配推荐引擎

```python
def match_qualifications(scoring, company_qualifications) -> list[dict]
def match_performances(scoring, company_performances) -> list[dict]
    # 排序：项目类型匹配 > 金额满足 > 时间范围内 > 描述完整度
def match_personnel(scoring, company_personnel) -> list[dict]
    # 匹配：持证、职位关键词、个人业绩关联
```

### 任务清单同步

```python
async def enrich_task_checklists(notice_id, db, important_notes) -> int:
    """将 important_notes 追加到对应 task_type 的 Task.checklist 中（去重）"""
```

---

## routers/tender.py 路由设计

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/tender/upload/{notice_id}` | 上传 .docx/.pdf 文件 → 保存 → 调用 parse_tender_xxx() → 写入 notice.tender_analysis → 303 跳回 detail |
| GET | `/tender/analysis/{notice_id}` | HTMX 局部加载：返回分析卡片 HTML 片段 |
| GET | `/tender/recommend/{notice_id}` | 推荐选择页（完整页面，含勾选功能） |
| POST | `/tender/enrich-tasks/{notice_id}` | 将注意事项同步到任务 checklist → 303 跳回 detail |

上传路由核心逻辑：
```python
@router.post("/upload/{notice_id}")
async def tender_upload(request, notice_id, tender_file: UploadFile = File(...), db=Depends(get_db)):
    # 1. 验证：登录、notice 存在、bid_decision=='bid'
    # 2. 验证文件扩展名：.docx 或 .pdf
    # 3. 保存到 uploads/tenders/{notice_id}/{uuid}_{filename}
    # 4. 根据扩展名调用 parse_tender_docx() 或 parse_tender_pdf()
    # 5. company = (await db.execute(select(Company).limit(1))).scalar_one_or_none()
    # 6. notice.tender_analysis = result
    # 7. await db.commit()
    # 8. return RedirectResponse(f"/notices/{notice_id}#tender-analysis")
```

---

## 模板设计

### notices/detail.html 修改点

**操作栏新增**（在"生成倒排计划"按钮后面）：
```html
{% if notice.bid_decision == 'bid' %}
    {% if not notice.tender_analysis %}
    <!-- 上传按钮：隐藏 file input + 可见触发按钮 -->
    <form method="post" action="/tender/upload/{{ notice.id }}"
          enctype="multipart/form-data" class="inline-form" id="tender-upload-form">
        <input type="file" name="tender_file" accept=".docx,.pdf" style="display:none"
               id="tender-file-input"
               onchange="document.getElementById('tender-upload-form').submit()">
        <button type="button" class="btn btn-sm btn-outline"
                onclick="document.getElementById('tender-file-input').click()">
            📄 上传招标文件解析
        </button>
    </form>
    {% else %}
    <a href="/tender/recommend/{{ notice.id }}" class="btn btn-sm btn-primary">查看解析与推荐</a>
    <form method="post" action="/tender/enrich-tasks/{{ notice.id }}" class="inline-form">
        <button type="submit" class="btn btn-sm btn-outline">同步到任务清单</button>
    </form>
    {% endif %}
{% endif %}
```

**分析卡片区域**（在编辑 form 之后）：
```html
{% if notice.tender_analysis %}
<div id="tender-analysis"
     hx-get="/tender/analysis/{{ notice.id }}"
     hx-trigger="load" hx-swap="outerHTML">
    <div class="card" style="text-align:center;padding:40px;">
        <span class="text-secondary">加载招标文件分析中...</span>
    </div>
</div>
{% endif %}
```

### templates/tender/analysis_card.html（HTMX 部分）

四张卡片：
1. **资格要求摘要**：密封/盖章/递交要求 + 所需证书列表（已备✓/缺失✗）+ 所需承诺函列表
2. **评分标准**：表格展示（评分项|满分|要求）+ 简单 CSS 柱状图
3. **推荐匹配摘要**：业绩/人员/资质各 Top 3 + "查看完整推荐"链接
4. **重要注意事项**：列表 + "同步到任务清单"按钮

### templates/tender/recommend.html（完整页）

```
[← 返回标讯详情]
标讯概览 card → 评分要求摘要 card
推荐资质 card（表格 + 勾选）
推荐业绩 card（表格，按匹配度排序，每行勾选框）
推荐人员 card（表格 + 勾选）
[同步到任务清单] [生成业绩材料(Phase 2预留)]
```

---

## 依赖变更

```diff
# requirements.txt
+ python-docx>=1.1     # .docx 读取（与投标文件库 Phase 1/2 共用）
+ pdfplumber>=0.11      # .pdf 读取（新增）
# python-multipart 已存在，无需添加
```

---

## 实现步骤

### 第1步：基础设施
1. 更新 `requirements.txt` + 安装依赖
2. `models.py`：BidNotice 加 `tender_analysis` 列
3. `database.py._migrate()`：加迁移逻辑
4. 创建 `uploads/tenders/` 目录（.gitkeep）

### 第2步：核心解析服务
1. 创建 `services/tender_parser.py`
2. 实现章节检测（Heading + keyword matching）
3. 实现资格要求提取（表格解析 + 正则）
4. 实现评分标准提取
5. 实现注意事项提取 + task_type 映射
6. 实现匹配推荐引擎
7. 实现 parse_tender_docx() 和 parse_tender_pdf() 主入口
8. 实现 enrich_task_checklists()

### 第3步：路由
1. 创建 `routers/tender.py`（4个路由）
2. `main.py` 注册 router

### 第4步：模板
1. 创建 `templates/tender/analysis_card.html`
2. 创建 `templates/tender/recommend.html`
3. 修改 `templates/notices/detail.html`（上传按钮 + 分析区域）

### 第5步：测试验证
1. 准备真实 .docx 和 .pdf 招标文件
2. 测试：上传 → 解析 → 查看分析卡片 → 推荐列表 → 同步到任务
3. 测试：重新上传覆盖旧分析
4. 测试：无 Company 数据时匹配为空但不报错
5. 测试：无已有任务时同步无副作用

---

## 与现有功能的集成

| 集成点 | 方式 |
|--------|------|
| 现有 assessor | 可选增强：assess_notice() 可读取 tender_analysis.scoring_criteria 做更精准评分（后续迭代） |
| 任务生成 | enrich_task_checklists() 将注意事项追加到已有 Task.checklist，不修改 planner 预设模板 |
| 投标文件库 Phase 2 | tender_analysis.recommendations 直接作为 generate_performance_docx() 的输入 |
| 文件存储 | `uploads/tenders/{notice_id}/` — 与 static/ 分离，通过路由鉴权下载 |

---

## 验证清单

1. 上传 .docx 招标文件 → 解析成功 → 详情页显示分析卡片
2. 上传 .pdf 招标文件 → 解析成功 → 结果一致
3. 资格要求卡片：密封/盖章/递交 + 证书匹配状态正确
4. 评分标准卡片：表格 + 进度条展示正确
5. 推荐列表：业绩按匹配度排序，人员按持证匹配，资质按等级匹配
6. "同步到任务清单"：注意事项追加到对应任务 checklist，不重复
7. 重新上传：旧分析被覆盖
8. 无 Company 数据：解析正常，推荐为空
