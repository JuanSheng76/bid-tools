# CLAUDE.md

## 项目概述

标策台 — 面向小团队（2-5人）的轻量化投标管理系统。目标行业：光伏检测、招标代理。

## 协作约定

- **修改前先确认**：收到修改意见 → 复述理解 + 列出方案（文件/位置/改动）→ 等用户确认 → 执行（typo 修复可跳过）
- **"更新"指令**：用户说"更新" → 自动将本次对话中的新规则/决策写入 memory + git commit 当前修改

## 技术栈

| 层级 | 选型 |
|------|------|
| Web 框架 | FastAPI (异步) |
| 模板 | Jinja2 (服务端渲染) |
| 前端交互 | HTMX (无刷新) + Alpine.js (响应式状态) + SortableJS (拖拽) |
| CSS | Pico.css (CDN) |
| 数据库 | SQLite + SQLAlchemy 2.0 异步 (aiosqlite) |
| 爬虫 | httpx + BeautifulSoup4 |
| 定时任务 | APScheduler (进程内) |
| 认证 | Session + Cookie (内存存储，直接使用 bcrypt) |
| 图表 | Chart.js (CDN) |
| Excel | openpyxl |

**核心原则：纯 Python，零 Node.js 依赖，单进程 `python main.py` 启动。**

## 项目结构

```
bid tools/
├── main.py              # FastAPI 入口，路由注册，lifespan（含 APScheduler 定时爬取）
├── config.py            # 配置常量（任务模板、评分权重、阈值）
├── database.py          # SQLAlchemy 异步引擎 + get_db 依赖注入
├── models.py            # 7 个 SQLAlchemy 模型（User/Company/BidSource/BidNotice/Registration/Task/BidResult）
├── schemas.py           # Pydantic 校验模型（备用）
├── auth.py              # 登录/注册/Session 管理（bcrypt 直接调用）
├── templates_config.py  # 共享 Jinja2 配置（TemplatesWithNow + notice_color 过滤器）
├── routers/
│   ├── dashboard.py       # GET / 仪表盘 + Chart.js 月度统计 + 7天提醒
│   ├── notices.py         # 标讯 CRUD + 评估触发 + 投标决策 + 放弃投标 + Excel 导出 + 分页筛选 + 表单日期预设
│   ├── company.py         # 公司资料 + 资质/业绩/人员增删（JSON 字段操作）
│   ├── tasks.py           # 任务看板（三列） + 倒排计划两步表单 + checklist + 拖拽状态更新
│   ├── results.py         # 开标/结果/合同管理 + Excel 导出 + 竞对报价
│   ├── sources.py         # 标讯来源配置 + 手动/定时爬取 + scrape_config JSON 编辑
│   ├── registrations.py   # 报名管理 + 自动填表（从公司资料填充） + 状态/缴费流转
│   └── calendar.py        # 投标日历视图（月视图 + 截止日期标记 + 颜色编码）
├── services/
│   ├── scraper.py       # 配置驱动通用爬虫（CSS selector + 正则，httpx 异步）
│   ├── assessor.py      # 5维评分引擎（关键词匹配，非精确）
│   ├── planner.py       # 倒排计划生成（7 模板 × 工作日计算）
│   ├── reminders.py     # 提醒查询（标讯截止/任务到期/合同到期，按紧急度排序）
│   └── excel_export.py  # 标讯/结果 Excel 导出的统一样式
├── templates/           # Jinja2 模板 (base.html + 各模块)
│   ├── auth/            # login.html
│   ├── notices/         # list.html / detail.html / form.html
│   ├── tasks/           # kanban.html / detail.html / generate.html
│   ├── results/         # list.html
│   ├── company/         # edit.html
│   ├── sources/         # list.html
│   ├── registrations/   # list.html
│   └── calendar.html     # 投标日历月视图
├── static/
│   ├── app.js           # 客户端逻辑（看板拖拽、checklist 勾选、toast 提示、计数动画、键盘快捷键、页面过渡）
│   └── style.css        # 自定义样式（拖拽效果、Toast 动画、HTMX 过渡、滚动条美化）
├── requirements.txt     # 12 个 Python 依赖（版本宽松，兼容 Python 3.14）
├── run.bat              # Windows 一键启动脚本（4步：依赖→建库→种子→启动）
├── seed_sources.py      # 种子数据：初始化默认标讯来源
├── seed_results.py      # 可重复执行的历史投标结果演示数据（北上广深线上循环）
├── test_scrape_urls.py  # 测试候选标讯网站的 HTTP 可访问性
├── 前端风格参考/          # 当前 UI 设计规范、设计令牌与组件示例
├── 代码功能说明.md        # 面向非开发人员的代码功能通俗说明
├── CLAUDE.md            # 本文件
├── PLAN_投标文件库.md    # 规划文档：过往投标文件导入 + 智能业绩推荐生成（两阶段方案）
├── PLAN_招标文件解析.md  # 规划文档：招标文件上传解析 + 资格/评分提取 + 智能推荐
```

## 数据库表关系

```
User (users)
  └── Task (tasks) via assignee_id

Company (company) — 单例，JSON 字段存资质/业绩/人员/银行信息

BidSource (bid_sources)
  └── BidNotice (bid_notices) via source_id
        ├── Registration (registrations) via notice_id
        ├── Task (tasks) via notice_id
        └── BidResult (bid_results) via notice_id (unique, 一对一)
```

### JSON 字段结构

- **Company.qualifications**: `[{name, level, cert_no, issuing_authority, issue_date, expiry_date, is_permanent}]`
  - *规划扩展*：每条增加 `source_file` 字段追踪来源投标文件
- **Company.performances**: `[{project_name, project_type, contract_amount, client_name, contract_date, description}]`
  - *规划扩展*：每条增加 `source_file`、`block_id` 字段，关联 `docs/import_index.json` 中的原始内容位置
- **Company.personnel**: `[{name, position, certifications, phone, email}]`
  - *规划扩展*：每条增加 `source_file`、`personal_performances: [{project_name, role, date}]` 字段
- **Company.bank_info**: `{bank_name, account_no, tax_no}`
- **BidSource.scrape_config**: `{list_url, item_selector, fields, detail_fields, pagination}`
- **BidNotice.assessment**: `{total_score, qual_score, perf_score, personnel_score, financial_score, other_score, recommendation, risk_notes, missing_requirements, assessed_at}`
- **BidNotice.abandon_reason**: Text 字段，放弃投标原因（决定投标后又放弃时填写）
- **Task.checklist**: `[{text: "...", done: false}]`
- **Task.priority**: `low / medium / high / urgent`（非 JSON，但为关键枚举字段）
- **BidResult.competitor_quotes**: `[{company, quote}]`

## 关键约定

### 模板上下文
- **所有模板自动获得 `now = datetime.utcnow()`** — 由 `templates_config.py` 的 `TemplatesWithNow` 类注入
- Starlette 1.x 要求 `TemplateResponse(request, name, context)` — `TemplatesWithNow` 自动从 context 提取 `request` 作为第一个位置参数
- 所有路由使用共享的 `from templates_config import templates` 实例
- 模板上下文必须包含 `request` 和 `session`

### 认证
- 内存 `SESSION_STORE` 字典存储会话（生产环境应换 Redis）
- Cookie 名：`session_id`，httponly，7 天有效期
- 密码使用 `bcrypt` 直接调用（`hashpw` / `checkpw`），**不是 passlib**
- 首个注册用户自动成为 `admin`，后续为 `staff`
- 路由入口统一检查 `get_session(request)` 是否为 None，未登录重定向 `/login`
- `get_current_user()` 可作为 FastAPI 依赖注入使用

### 标讯状态流转
```
new → assessing → worth → registered → bidding → completed
                 → not_worth → ignored
worth (bid_decision=bid) → ignored (via 放弃投标)
```
- 评估结果 ≥70 → `worth`，40-69 → `assessing`，<40 → `not_worth`
- 生成倒排计划后 → `bidding`
- 录入开标结果后 → `completed`

### 投标决策
- `BidNotice.bid_decision` 字段与评估**独立**：`bid`（决定投）/ `no_bid`（决定不投）/ `NULL`（未决定）
- 评估是自动建议，决策是人工最终判断 — 即使评分低也可手动决定投标
- 决定投标 → 自动将 status 升级为 `worth`（如当前为 new/assessing/not_worth）
- 决定不投 → status 变为 `ignored`
- 决策按钮在标讯详情页的操作栏，列表页同步显示决策状态

### 放弃投标
- 已决定投标（`bid_decision='bid'`）的标讯可「放弃投标」，与普通「决定不投」的区别在于必须填写原因
- `BidNotice.abandon_reason` (Text) 存储放弃原因，`bid_decision` → `no_bid`，`status` → `ignored`
- 详情页弹出 `<dialog>` 弹窗提供预设原因（点击自动填入），也可自行输入
- 路由：`POST /notices/{id}/abandon`

### 评估引擎 (`services/assessor.py`)
- 5 维度加权评分：资质(40%) + 业绩(25%) + 人员(15%) + 财务(10%) + 其他(10%)
- 关键词匹配（非精确），基于 Company 的 JSON 字段
- 其他因素：平台注册(3) + 标书费(1) + 期限(3) + 区域(2) + 联系信息(1)
- ≥70 推荐投（recommend），40-69 可考虑（consider），<40 不推荐（not_recommend）
- 评估结果内嵌在 `BidNotice.assessment` JSON 字段，无需独立评估表

### 倒排计划 (`services/planner.py`)
- 7 个标准任务模板定义在 `config.py` 的 `TASK_TEMPLATE`
- `days_before` 表示距目标截止日期的**工作日天数**
- 工作日计算排除周六日 (`weekday() < 5`)
- 每个任务类型有预设 checklist（3 项）
- 从 deadline 倒推：planned_end = deadline - days_before 个工作日
- `generate_schedule()` 支持 `target_deadline` 和 `days_before_map` 可选参数（自定义截止日期和每阶段天数）
- `preview_schedule()` 用于预览倒排计划而不写入数据库
- 生成流程：GET 显示设置表单 → 用户确认 → POST 执行生成
- POST 支持 `replace=1` 参数，先删除已有任务再重新生成（重排模式）

### 爬虫 (`services/scraper.py`)
- 配置驱动：JSON 格式的 `scrape_config` 存 BidSource
- 通用爬虫 `scrape_source()` 支持 CSS selector + 正则提取
- 去重依据 `external_id`
- 列表字段：`list_url` + `item_selector` + `fields`（external_id/title/detail_url/date）
- 详情字段：`detail_fields`（可指定 selector + attr + regex + processor）
- 分页：`pagination.max` + `pagination.next_selector`
- 请求间隔：30 秒超时，自动跟随重定向
- **注意**：目前未实现 `use_playwright` JS 渲染，仅支持静态 HTML

### 定时任务
- APScheduler 在 `lifespan` 中启动，每 30 分钟自动爬取所有活跃来源
- `next_run_time=None` 表示启动后不立即执行，等待第一个间隔
- `sources/{id}/scrape` 路由支持手动触发单个来源

### Excel 导出
- 使用 `openpyxl`，统一调用 `services/excel_export.py` 的 `style_export_sheet()` 设置样式
- **中文文件名必须用 RFC 5987 编码**（`urllib.parse.quote`），否则 HTTP 头报 `UnicodeEncodeError`
- 导出前用 `selectinload()` 预加载关联数据，避免异步懒加载报错
- 使用 `Response(content=..., media_type=..., headers=...)` 而非 `StreamingResponse`

## 开发环境

### 系统要求
- Python 3.12+（已在 Python 3.14 上测试通过）
- Windows / Linux / macOS
- 无需 Node.js、npm 或其他外部依赖

### 启动方式

```bash
# 方式一：Windows 一键启动（自动检查依赖、初始化数据库、启动服务）
run.bat

# 方式二：手动启动
pip install -r requirements.txt
python main.py

# 浏览器打开 http://localhost:8000
```

`run.bat` 流程（4步）：
1. `chcp 65001` 切换到 UTF-8 编码避免中文乱码
2. 检测 Python（`python` → `py` 回退）
3. 自动安装依赖（如缺少 fastapi）
4. 初始化数据库表（`asyncio.run(init_db())`）
5. 初始化标讯来源（`python seed_sources.py`，幂等，已存在则跳过）
6. 启动 `python main.py`

### 测试账号
- 用户名：`admin`，密码：`admin123`（角色：管理员）
- 新注册用户：浏览器访问 `/login` 点击注册

## 招标文件解析（已实现 ✅）

> 详见 `PLAN_招标文件解析.md`。核心实现：`services/llm_parser.py` + `services/tender_parser.py` + `routers/tender.py`。

- **解析方式**：LLM 优先 + 规则 fallback，决定投标后上传 .docx/.pdf 触发
- **核心原则**：LLM 只做理解（提取资格/评分/注意事项），推荐匹配由规则引擎精确执行
- **数据存储**：`BidNotice.tender_analysis` JSON 字段
- **LLM 配置**：环境变量 `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` / `LLM_MAX_CHARS`，默认使用 DeepSeek

### 投标文件库（规划中）

> 详见 `PLAN_投标文件库.md`。两阶段：Phase 1 导入过往投标文件（解析→去重→入库），Phase 2 智能推荐并生成业绩 docx。新增依赖 `python-docx>=1.1`。

## 开发注意事项

### 日期处理
- 日期字段使用 `datetime.utcnow()` 和 `datetime.strptime`，不带时区
- Form 日期提交需要 `parse_date()` 函数尝试多种格式（`%Y-%m-%dT%H:%M` / `%Y-%m-%d %H:%M` / `%Y-%m-%d`）
- 爬虫中的日期解析额外支持中文格式（`%Y年%m月%d日`）和正则提取
- **手动添加标讯表单日期预设值**（`/notices/new` 路由计算，传入模板 `defaults` 字典）：
  - 日期部分：默认当前年月，日固定为 `01`（由用户自行修改具体日期）
  - 报名截止：`YYYY-MM-01T17:00`
  - 开标时间：`YYYY-MM-01T09:30`
  - 投标截止：与开标时间保持一致
  - 发布日期：`YYYY-MM-01`

### 数值字段
- `budget_amount` 等 Float 字段用户输入单位为**万元**
- `bid_document_fee` 单位为**元**
- 爬虫自动识别"万元/万"后缀并转换

### JSON 字段操作
- `qualifications` / `performances` / `personnel` 增删时必须用 `list()` 浅拷贝，再 `append` / `pop`，最后赋值回去
- 不要直接 `company.qualifications.append()` — SQLAlchemy 不会检测到变异

### 前端交互
- JS 函数挂载在 `window`（非 module 模式），模板中直接调用如 `onclick="deleteNotice('...')"`
- Alpine.js 组件通过 `x-data="checklistApp(...)"` 初始化
- SortableJS 在 `DOMContentLoaded` 和 `htmx:afterSwap` 事件中初始化看板拖拽
- HTMX 响应通常返回 HTML 片段，直接插入 DOM
- 标讯列表仅对进行中的项目显示剩余/逾期天数；`completed` 项目在截止日期下显示中标、未中标、废标或流标，结果关系须通过 `selectinload(BidNotice.result)` 预加载

### 自定义 Jinja2 过滤器
- `templates_config.py` 中注册了 `notice_color` 过滤器
- 输入 notice_id，返回 `{"primary": "#hex", "bg": "#hex"}` 颜色字典
- 12 色调色板，基于 MD5 hash 取模，同一标讯始终同色
- 用于任务看板卡片上的标讯标签颜色区分

### 任务-标讯关联
- 任务看板每个卡片顶部有 `task-notice-tag` 标签显示所属标讯名称
- 标讯名称 13px 加粗 + 左侧色条（notice_color 提供），任务标题 13px 次级色
- 任务查询使用 `selectinload(Task.notice)` 和 `selectinload(Task.assignee)` 预加载避免 N+1
- 标讯详情路由使用 `selectinload(BidNotice.tasks)` 预加载任务列表
- 倒排计划入口按钮由 `bid_decision == 'bid'` 驱动（非 status），已有任务显示「重排计划」

### 提醒服务 (`services/reminders.py`)
- 仪表盘近期提醒查询三类截止项：标讯投标截止（7天）、任务到期（7天）、合同到期（30天）
- 任务提醒包含 `notice_title` 和 `notice_id` 字段，在仪表盘中显示关联标讯
- 任务查询使用 `selectinload(Task.notice)` 预加载关联标讯
- 按紧急程度（days_left）升序排列

### UI 设计系统（2026-07-29 当前基线）
- **品牌**：中文名称「标策台」，Logo 图形标记使用「标」，英文副标为 `BID OPERATIONS`
- **配色**：采用浅色商务工作台；主工作区为冷白/浅灰背景，侧边栏保留克制的深蓝渐变，主色为商务蓝，状态色使用低饱和绿/黄/红
- **视觉原则**：信息密度优先、层级清晰、边框轻、阴影克制，避免大面积深色、过亮标签、过大圆角和过度渐变
- **设计依据**：**所有前端页面改动必须以 `前端风格参考/` 为视觉依据** — 修改前查阅 `设计规范.md`（视觉原则）、`tokens.css`（设计令牌）、`组件示例.html`（组件样式），新增组件优先参照已有组件样式
- **登录页**：深蓝品牌区与浅色悬浮登录卡片形成层次；使用光晕、网格漂移、信号点和入场动画，并支持 `prefers-reduced-motion`
- **侧边栏**：Logo 显示「标策台 / BID OPERATIONS」，激活项使用低对比蓝色强调，保证导航可读性
- **统计卡片**：紧凑排布、低饱和强调色、轻边框和克制悬浮反馈
- **表格与表单**：使用浅色背景、细分隔线、紧凑字号和统一控件高度
- **任务看板**：标讯标签使用 12 组低饱和确定性色；已完成列“收起/展开”按钮采用白底深色字，并同步 `aria-expanded`
- **日历**：与工作台统一使用浅色卡片、细边框和低饱和期限状态色
- **CSS 组织**：基础结构仍在 `base.html`，当前主题、组件增强、登录动效、图表和漏斗样式主要维护在 `static/style.css`

### 仪表盘图表与投标漏斗
- **月度趋势图**：展示近 12 个自然月的中标、未中标、废标、流标数量，不再展示“中标率”
- **柱形设计**：使用窄柱和清晰网格；纵轴按常规每周 2–3 次投标频次设计，基础上限为 12，并根据实际峰值向上扩展
- **中标标注**：中标月份在图表上直接标明中标项目名称，完整名称可通过交互提示查看
- **摘要信息**：显示结果总数、中标项目数、未中标项目数和最活跃月份
- **视图切换**：趋势图与转化漏斗共用同一张卡片，通过按钮切换，避免额外占用首页宽度
- **漏斗阶段**：获取标讯 → 确定投标 → 完成投标 → 中标；未中标、废标和流标只作为补充结果，不参与漏斗阶段
- **漏斗样式**：采用宽度递减的圆角长方形，突出侧边阶段转化率；服务端 `_get_bid_funnel()` 兼容已有结果但未记录 `bid_decision` 的历史数据

### 历史投标结果演示数据
- `seed_results.py` 提供 18 条可重复生成的过往投标结果，覆盖中标、未中标、废标和流标
- 演示标讯使用 `DEMO-RESULT-` 前缀；重复运行时只替换该前缀的数据，不修改用户真实数据
- 项目地址固定按「北京市 → 上海市 → 广州市 → 深圳市 → 线上」循环
- 数据包含开标时间、报价、竞争对手报价、中标单位、合同金额、失标原因等，用于验证结果列表、仪表盘图表和漏斗

### Python 3.14 兼容
- `pydantic>=2.10` 版本约束已放宽，pip 会自动拉取兼容 cp314 的 wheel
- 不再使用 `passlib`（不兼容 bcrypt 5.x），改用 `bcrypt` 直接调用
- `requirements.txt` 中所有版本使用 `>=` 而非 `==`，确保跨版本兼容

### Starlette 1.x API 变更
- `Jinja2Templates.TemplateResponse` 签名变更为 `(request, name, context, **kwargs)`
- `templates_config.py` 中的 `TemplatesWithNow` 封装了此变更，路由层无需关心
- 所有路由调用 `templates.TemplateResponse("模板名", {"request": request, ...})` 即可

### Windows Shell 注意事项
- Git Bash / 终端可能使用 GBK 编码，Python print 中文可能报 `UnicodeEncodeError`
- 解决方法：使用 `python -X utf8` 或将输出重定向到文件
- 数据库中的中文数据不受影响（SQLite 使用 UTF-8 存储）

### Jinja2 模板中的 dict 方法名陷阱 ⚠️
- Jinja2 的 `dict.key` 语法优先查找**属性**而非键：若 key 与 dict 内置方法同名（`items`、`keys`、`values`、`get`、`update`），返回的是方法对象而非数据
- 例如 `ta.scoring_criteria.items` 返回 `dict.items` 方法，而非 JSON 数据中 `"items"` 字段的列表
- **必须用 `dict["items"]` 或 `dict.get("items", [])` 访问这类键名**
- 建议：模板中涉及 JSON 数据的 `items` 键时，先用 `{% set items = data.get("items", []) %}` 设局部变量

### 耗时同步操作的线程化模式
- CPU 密集型同步操作（文档解析、大文件处理、复杂正则扫描）不应直接放在 `async def` 路由中
- 使用 `asyncio.to_thread(sync_func, arg1, arg2, ...)` 将操作丢入线程池，释放事件循环
- 对应的同步函数声明为普通 `def`（非 `async def`），避免误导
- 线程中的对象访问：确保传入的数据已完全加载到内存（如 SQLAlchemy JSON 字段、标量属性），不要依赖 lazy load
- 路由层加 `print(flush=True)` 日志，方便观察解析进度和耗时
