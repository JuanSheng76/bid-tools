# 投标文件库 — 两阶段方案

## 投标文件实际结构

```
投标文件.docx
├── ...（其他章节，跳过）
├── 业绩章节（如"投标人业绩""同类项目经验"）
│   ├── 汇总表格（1个）：列出所有业绩概况
│   │   ┌──────────────────────────────────────────────┐
│   │   │ 序号 │ 项目名称 │ 合同金额 │ 业主 │ 日期    │
│   │   │  1   │ XX光伏检测│ 120万   │ XX  │ 2024-03│
│   │   │  2   │ YY招标代理│ 80万    │ YY  │ 2023-11│
│   │   └──────────────────────────────────────────────┘
│   ├── 2.1 XX光伏检测项目  ← 业绩详情块（小标题）
│   │   该项目位于XX，装机容量100MW...（文字描述，没有表格）
│   │   [合同扫描件.jpg] [检测报告.jpg] ← 证明材料图片
│   ├── 2.2 YY招标代理项目  ← 下一个业绩详情块
│   │   为YY公司提供招标代理服务...（文字描述）
│   │   [中标通知书.jpg]
│   └── ...
├── 资质章节（如"投标人资质""企业资质"）
│   ├── 汇总表格（1个）：资质证书列表
│   │   ┌──────────────────────────────────────────────┐
│   │   │ 序号 │ 证书名称 │ 等级 │ 编号 │ 发证机关    │
│   │   └──────────────────────────────────────────────┘
│   └── 各资质详情块 + 证书扫描件图片
├── 人员章节（如"拟投入本项目人员""项目团队"）
│   ├── 汇总表格（1个）：人员列表
│   │   ┌──────────────────────────────────────────────┐
│   │   │ 序号 │ 姓名 │ 职位 │ 持证 │ 个人代表业绩    │
│   │   └──────────────────────────────────────────────┘
│   └── 各人员详情块（含个人业绩描述）
└── ...
```

---

## Phase 1：导入投标文件到公司资料库

### 整体数据流

```
docs/*.docx
    ↓ 逐个解析
services/doc_parser.py → 章节定位 + 表格提取 + 详情块切分 + 图片提取
    ↓ {qualifications, performances, personnel, blocks}
services/dedup.py → 读取 Company 现有数据对比去重
    ↓ {new_items, skipped_items}
scan_docs.py → 写入数据库 + 保存图片 + 更新索引
    ↓
SQLite Company 表（qualifications / performances / personnel JSON 字段）
    ↓
网页端 /company → 列表展示（含来源文件列）
网页端 /company/library → 按来源文件浏览
```

### 解析策略

#### 业绩章节处理

1. **定位业绩章节**：通过 Heading 关键词找到章节位置
   - 关键词：`业绩、项目经验、同类项目、类似项目、已完成项目、主要项目、代表项目、承担项目、承揽项目、项目业绩、相关业绩`
2. **提取汇总表格**：章节内第一个表格 → 解析为结构化数据
3. **切分详情块**：在汇总表之后，按小标题切分，每个块 = 标题 + 文字描述 + 图片
4. **关联**：汇总表每行 → 对应一个详情块（通过项目名称匹配）

#### 资质章节处理

1. **定位资质章节**：Heading 关键词 `资质、证书、企业资质、投标人资质、资格、认证`
2. **提取汇总表格** → 结构化数据（name, level, cert_no, issuing_authority, issue_date, expiry_date）
3. **切分详情块** → 证书描述 + 证书扫描件图片

#### 人员章节处理

1. **定位人员章节**：Heading 关键词 `人员、团队成员、项目负责人、拟投入、项目组、管理团队`
2. **提取汇总表格** → 结构化数据（name, position, certifications, phone, email）
3. **提取个人业绩**：汇总表中可能有"代表项目"列，或人员详情块下有个人业绩列表

### 去重策略

#### 资质去重
- 匹配规则：`name + cert_no` 完全相同 → 重复
- 保留原则：保留日期更新的那份

#### 业绩去重
- 匹配规则：`project_name` 相似度 ≥ 80%
- 保留原则：**保留 contract_date 更新的那份**
- 备用：日期相同时，保留描述更长的

#### 人员去重
- 匹配规则：`name` 完全相同 → 同一人
- 处理方式：**合并 personal_performances**（不重复添加同名人员）
- 其他字段（职位/持证/电话/邮箱）以较新的数据覆盖

### 导入到公司资料的实现

#### 资质导入

```python
# scan_docs.py 中调用 database.py 连接 SQLite
async def import_qualifications(parsed_list, db):
    result = await db.execute(select(Company).limit(1))
    company = result.scalar_one_or_none()
    existing = list(company.qualifications or [])

    new_items, skipped = dedup_qualifications(parsed_list, existing)
    # new_items 每条格式: {name, level, cert_no, issuing_authority,
    #                       issue_date, expiry_date, is_permanent,
    #                       source_file}

    company.qualifications = existing + new_items
    await db.commit()
    return len(new_items), len(skipped)
```

#### 业绩导入

```python
async def import_performances(parsed_list, db):
    result = await db.execute(select(Company).limit(1))
    company = result.scalar_one_or_none()
    existing = list(company.performances or [])

    new_items, skipped = dedup_performances(parsed_list, existing)
    # new_items 每条格式: {project_name, project_type, contract_amount,
    #                       client_name, contract_date, description,
    #                       source_file, block_id}

    company.performances = existing + new_items
    await db.commit()
    return len(new_items), len(skipped)
```

#### 人员导入

```python
async def import_personnel(parsed_list, db):
    result = await db.execute(select(Company).limit(1))
    company = result.scalar_one_or_none()
    existing = list(company.personnel or [])

    new_people, merged_count = dedup_personnel(parsed_list, existing)
    # 同名人员 → 合并 personal_performances 到已有记录
    # 新人员 → 追加到列表
    # 每条格式: {name, position, certifications, phone, email,
    #             source_file, personal_performances: [...]}

    company.personnel = existing + new_people
    await db.commit()
    return len(new_people), merged_count
```

### 网页端展示

#### 公司资料页 (`/company`)

现有表格增加列：

| 区域 | 增加内容 |
|------|---------|
| 资质表格 | "来源文件"列 + "预览图片"按钮 |
| 业绩表格 | "来源文件"列（可点击跳转文件库） |
| 人员表格 | "来源文件"列 + "个人业绩"展开区 |

#### 文件库页 (`/company/library`) — 新建

- 按 source_file 分组卡片
- 每个卡片：文件名 + 提取统计（X条资质/Y条业绩/Z名人员/N张图）
- 点击展开详情：记录列表 + 图片缩略图

### 数据存储

#### Company JSON 字段扩展

**qualifications 每条增加**：
```json
{
    "name": "电力工程检测甲级",
    "level": "甲级",
    "cert_no": "XYZ-2024-001",
    "issuing_authority": "XX省住建厅",
    "issue_date": "2024-01-15",
    "expiry_date": "2029-01-14",
    "is_permanent": false,
    "source_file": "XX光伏项目投标文件.docx"
}
```

**performances 每条增加**：
```json
{
    "project_name": "XX光伏电站检测",
    "project_type": "pv_testing",
    "contract_amount": 120.5,
    "client_name": "XX能源公司",
    "contract_date": "2024-03-15",
    "description": "该项目位于XX，装机容量100MW...",
    "source_file": "XX光伏项目投标文件.docx",
    "block_id": "perf_001"
}
```

**personnel 每条增加**：
```json
{
    "name": "张三",
    "position": "项目经理",
    "certifications": "一级建造师,注册检测工程师",
    "phone": "138xxxx",
    "email": "zhang@xx.com",
    "source_file": "XX光伏项目投标文件.docx",
    "personal_performances": [
        {"project_name": "XX光伏检测", "role": "项目负责人", "date": "2024-03"},
        {"project_name": "YY招标代理", "role": "技术负责人", "date": "2023-11"}
    ]
}
```

#### import_index.json（docs/ 目录）

```json
{
    "XX光伏项目投标文件.docx": {
        "file_path": "docs/XX光伏项目投标文件.docx",
        "imported_at": "2026-07-29T10:30:00",
        "images_dir": "static/proof_images/XX光伏项目投标文件/",
        "performance_blocks": [
            {
                "block_id": "perf_001",
                "title": "2.1 XX光伏电站检测项目",
                "para_range": [52, 60],
                "text_content": "该项目位于XX，装机容量100MW...",
                "images": ["contract.jpg", "report.jpg"]
            }
        ],
        "qualification_blocks": [
            {
                "block_id": "qual_001",
                "title": "电力工程检测甲级证书",
                "para_range": [12, 18],
                "text_content": "...",
                "images": ["cert_scan.png"]
            }
        ],
        "personnel_blocks": [
            {
                "block_id": "person_001",
                "name": "张三",
                "para_range": [65, 72],
                "text_content": "...",
                "images": []
            }
        ]
    }
}
```

#### 图片存储

```
static/proof_images/
└── XX光伏项目投标文件/
    ├── contract.jpg
    ├── report.jpg
    └── cert_scan.png
```

---

## Phase 2：根据标讯要求推荐并生成业绩 docx

### 使用场景

> 有新标讯需要投标 → 系统读取标讯的评分要求 → 从公司资料库中推荐匹配的业绩 → 用户勾选确认 → 自动从原始 docx 中提取对应内容（文字+图片） → 生成新的业绩材料.docx

### 整体流程

```
标讯详情页 (/notices/{id})
    ↓ 点击"生成业绩材料"按钮
读取标讯要求（qualification_requirements + assessment JSON）
    ↓ 关键词提取（项目类型/规模/金额/资质等级/...）
在 Company 资料库中匹配
    ├── 资质匹配：所需资质 vs Company.qualifications
    ├── 业绩匹配：项目类型/金额范围/区域 vs Company.performances
    └── 人员匹配：所需持证 vs Company.personnel
    ↓
推荐列表（按匹配度 + contract_date 降序排列）
    ↓ 展示在网页上，用户勾选
确认生成
    ↓
读取 import_index.json → 找到被选中业绩的 block_id
    ↓ → 定位原始 docx 文件
    ↓ → 按 para_range 提取段落内容
    ↓ → 复制对应图片
    ↓
生成 业绩材料.docx
    ├── 封面/标题
    ├── 业绩汇总表（用户选中的业绩概览）
    ├── 各业绩详情（原文文字 + 证明材料图）
    └── 资质证书复印件（原文 + 扫描件）
    ↓
浏览器下载 docx 文件
```

### 推荐排序规则

- **第一优先级**：匹配度（项目类型相同 > 金额在同一量级 > 关键词匹配）
- **第二优先级**：contract_date 降序（时间越新越靠前）
- **第三优先级**：描述完整度（描述越长越靠前，信息更丰富）

### 用户操作页面

#### 入口：标讯详情页 (`/notices/{id}`)

操作栏新增按钮：
```
[触发评估] [决定投标] [生成倒排计划] [📄 生成业绩材料] ← 新增
```

#### 推荐选择页 (`/notices/{id}/generate-performance`)

```
┌────────────────────────────────────────────────────┐
│ 标讯：XX光伏电站2026年度检测服务招标   截止：2026-09-15│
├────────────────────────────────────────────────────┤
│ 评分要求分析：                                      │
│   - 项目类型：光伏检测                              │
│   - 合同金额：约200万                               │
│   - 资质要求：电力工程检测乙级以上                   │
│   - 业绩要求：近3年类似项目 ≥ 2个                   │
│                                                    │
│ ─── 推荐资质 ────────────────────────────────────   │
│ ☑ 电力工程检测甲级 (2024-01) ── 来源: XX项目.docx  │
│ ☐ 光伏电站安全评价乙级 (2023-06)                     │
│                                                    │
│ ─── 推荐业绩 (按匹配度排序) ─────────────────────   │
│ ☑ XX光伏电站检测 120万 2024-03 ⭐⭐⭐ 匹配度高      │
│   业主: XX能源 | 来源: XX项目.docx [预览]           │
│ ☑ YY光伏组件检测 80万 2023-11 ⭐⭐⭐ 匹配度中       │
│   业主: YY新能源 | 来源: YY项目.docx [预览]         │
│ ☐ ZZ风电场检测 300万 2025-01 ⭐⭐ 匹配度低          │
│   业主: ZZ电力 | 来源: ZZ项目.docx [预览]           │
│                                                    │
│ ─── 推荐人员 ────────────────────────────────────   │
│ ☑ 张三 (项目经理/一级建造师) ── 来源: XX项目.docx   │
│   个人业绩: XX光伏检测, YY招标代理                   │
│ ☐ 李四 (检测工程师/注册检测工程师)                   │
│                                                    │
│ [👁 预览] [📥 生成并下载 docx]                      │
└────────────────────────────────────────────────────┘
```

### 生成 docx 的实现

```python
# services/docx_generator.py（Phase 2 新增）

def generate_performance_docx(
    notice_id: str,
    selected_quals: list[str],    # block_id 列表
    selected_perfs: list[str],    # block_id 列表
    selected_personnel: list[str],# block_id 列表
    output_path: str
) -> str:
    """
    1. 从 import_index.json 读取每个 block_id 对应的:
       - 源文件路径
       - 段落范围 (para_range)
       - 关联图片列表
    2. 打开源 docx，按 para_range 提取段落内容
    3. 复制关联图片
    4. 用 python-docx 组装新文档:
       - 封面/标题（标讯名称 + 日期）
       - 资质证明部分（证书描述 + 扫描件）
       - 业绩汇总表（用户选中的业绩概览表格）
       - 各业绩详情（原始文字 + 证明材料图）
       - 人员简历部分（个人信息 + 个人业绩）
    5. 保存为 docx，返回文件路径
    """

def build_summary_table(doc, selected_perfs, performances_data):
    """生成业绩汇总表：序号 | 项目名称 | 金额 | 业主 | 日期"""

def copy_block_content(doc, source_docx_path, para_range, images):
    """从源文件复制指定段落范围的文字 + 图片到新文档"""
```

### 生成文档结构

```
业绩材料.docx
├── 封面
│   标讯名称：XX光伏电站2026年度检测服务
│   投标人：XX检测有限公司
│   日期：2026-07-29
├── 一、资质证明
│   ├── 资质汇总表
│   ├── 1.1 电力工程检测甲级（原文 + 证书扫描件）
│   └── 1.2 ...
├── 二、同类项目业绩
│   ├── 业绩汇总表
│   │   ┌─────────────────────────────────────────┐
│   │   │ 序号│ 项目名称 │ 金额 │ 业主 │ 日期   │
│   │   │  1  │ XX光伏检测│ 120 │ XX  │ 2024-03│
│   │   │  2  │ YY光伏组件│ 80  │ YY  │ 2023-11│
│   │   └─────────────────────────────────────────┘
│   ├── 2.1 XX光伏电站检测项目（从原docx提取的文字+图）
│   └── 2.2 YY光伏组件检测项目（从原docx提取的文字+图）
└── 三、项目团队
    ├── 人员汇总表
    ├── 3.1 张三（简历信息 + 个人业绩）
    └── 3.2 ...
```

---

## 技术方案

### 新增依赖

| 库 | Phase | 用途 |
|---|---|---|
| `python-docx>=1.1` | Phase 1+2 | 读取/写入 .docx，段落定位，表格提取，图片提取 |

仅 1 个依赖，两个 Phase 共用。

### 新增文件

| 文件 | Phase | 说明 |
|------|-------|------|
| `services/doc_parser.py` | 1 | 章节定位 + 汇总表格提取 + 详情块切分 + 图片提取 |
| `services/dedup.py` | 1 | 资质/业绩/人员去重 |
| `services/index_manager.py` | 1 | 管理 `docs/import_index.json` |
| `scan_docs.py` | 1 | CLI 扫描脚本，解析 + 去重 + 写入 Company 表 |
| `services/docx_generator.py` | 2 | 读取索引 → 提取内容 → 生成新 docx |
| `templates/notices/generate_performance.html` | 2 | 推荐选择页 |
| `templates/company/library.html` | 1+2 | 文件库浏览页 |

### 修改文件

| 文件 | Phase | 改动 |
|------|-------|------|
| `requirements.txt` | 1 | +`python-docx>=1.1` |
| `routers/company.py` | 1 | +2 路由；列表加 source_file 列 |
| `routers/notices.py` | 2 | +1 路由 `GET /notices/{id}/generate-performance`；详情页增加按钮 |
| `templates/company/edit.html` | 1 | 业绩/人员/资质表加"来源文件"列 + "投标文件库"入口 |
| `templates/notices/detail.html` | 2 | 操作栏增加"生成业绩材料"按钮 |

---

## 实现步骤

### Phase 1：导入

1. 安装 `python-docx`，更新 requirements.txt
2. 创建 `services/index_manager.py`
3. 创建 `services/doc_parser.py`
4. 创建 `services/dedup.py`
5. 创建 `scan_docs.py`
6. 创建 `templates/company/library.html`
7. 修改 `routers/company.py` + `templates/company/edit.html`
8. 真实文件测试

### Phase 2：推荐与生成

1. 创建 `services/docx_generator.py`
2. 创建 `templates/notices/generate_performance.html`
3. 修改 `routers/notices.py`（推荐路由 + 生成下载路由）
4. 修改 `templates/notices/detail.html`（入口按钮）
5. 端到端测试：标讯 → 推荐 → 勾选 → 生成下载

---

## 验证

### Phase 1
1. 准备含业绩/资质/人员章节的真实 .docx 放入 `docs/`
2. `python scan_docs.py --dry-run` 验证提取正确
3. `python scan_docs.py` 正式导入
4. `/company` 查看新增数据 + 来源列
5. `/company/library` 按文件浏览
6. 重复运行验证去重

### Phase 2
1. 在系统中创建一条标讯（含评分要求）
2. 点击"生成业绩材料" → 确认推荐结果合理
3. 勾选业绩/资质/人员 → 生成 docx
4. 打开生成的 docx 检查内容完整（表格 + 文字 + 图片）
