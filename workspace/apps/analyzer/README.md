# analyzer — Python 计算与算法层

链路位置：`Vue → BFF → job-service → **analyzer** → LLM`

## 职责与禁止

| | 内容 |
|---|---|
| **职责**（spec.md §2.6） | 文本清洗、技能归一化、匹配打分、LLM 编排与**降级** |
| **禁止** | 鉴权、岗位数据 CRUD、**直连数据库** |

**本服务不拥有任何数据库**：技能词典是随代码分发的只读 YAML 资源（T5 落地），
不属于持久层。因此这里**没有** `model/` 与 `repository/`，也**没有** `auth/` —— 这不是遗漏。

## 接口

| 方法 | 路径 | 说明 | 契约 |
|---|---|---|---|
| GET | `/healthz` | 健康检查 | spec.md §2.8 |
| GET | `/internal/ping` | 连通性探针，回显 `X-Trace-Id` | 非契约（探针） |
| POST | `/internal/analyze` | 分析入口 | ⬜ 骨架阶段返回空结构，T5 填充 |

## 目录结构（分层）

```
app/
├─ main.py                              入口：配置日志 / 挂中间件 / 注册路由（无业务逻辑）
├─ api/v1/                              ① 控制层：声明路径与出入参，调 Service
│  ├─ health.py
│  └─ internal.py
├─ service/                             ② 业务层：编排三步链、决定降级
│  ├─ analysis_service.py               编排（T5 填充真实算法）
│  ├─ parser_plugin.py                  ★ 解析器「插件」框架：协议 + 注册表 + 组合根
│  ├─ pdf_parser.py                     ★ **唯一** import pypdf 的文件（M2.2）
│  ├─ docx_parser.py                    自己用标准库实现的 Word 解析（本期预留，见 DELIVERY.md D-2）
│  └─ cleaner.py                        ★ 文本清洗七步（M2.4）
├─ data/skills.yaml                     技能词典真源（C4，随代码分发的只读资源）
├─ schema/                              ④ DTO：契约形状的唯一落点
│  ├─ request/analyze_request.py
│  └─ response/{analyze,error,health}_response.py
├─ core/                                横切：配置 / 常量 / 资源 / 日志 / 追踪 / 异常 / 装配
│  ├─ config.py                         可被环境覆盖的值（端口、密钥）
│  ├─ constants.py                      永不随环境变化的值（长度上限、权重、header 名）
│  ├─ resources.py                      ★ `app/data/*.yaml` 的唯一读取点（路径 + 解析 + 顶层校验）
│  ├─ trace.py                          ★ ContextVar + TraceIdMiddleware
│  ├─ logging.py                        结构化 JSON，traceId 自动注入
│  ├─ exceptions.py                     ErrorCode + AppException
│  ├─ exception_handlers.py             ★ 唯一把异常翻译成 HTTP 的地方
│  └─ dependencies.py                   ★ 组合根：唯一装配具体实现的地方
└─ util/response.py                     错误响应体的唯一构造点
```

**依赖方向**（指南 §1.1）：`api → service → schema`；`core` / `util` 是横切，
可被任意层引用，但 **`core` 不得 import `service`**。

**注意 `api/v1/` 只是目录分组**：路径上**不加** `/v1` 前缀 —— `spec.md §2.2` 的
路径是冻结契约。真要并行维护两版时，改 `include_router(prefix=...)` 即可，不用挪文件。

## 溯源地图 —— 现象 → 该看哪个文件

| 现象 | 第一个该看的文件 | 再看 |
|---|---|---|
| 接口报错，但不知道 `code` 从哪来 | `core/exceptions.py` | `core/exception_handlers.py` |
| 入参校验失败返回 422 而不是 400 | `core/exception_handlers.py` `handle_validation` | FastAPI 默认 422，契约里 422 属 ANALYSIS_FAILED |
| 错误响应里出现了堆栈 / 异常类名 | `core/exception_handlers.py` | `util/response.py` |
| 响应字段名/层级变了，前端解析失败 | `schema/response/analyze_response.py` | ⚠️ 这是 spec.md §2.2 冻结契约 |
| 想改长度上限 / 打分权重 | `core/constants.py` | 同步 `spec.md` §2.1 / ADR-002 + 契约 |
| 词典认不出某个技能 / 要加一个数据文件 | `app/data/skills.yaml` | `core/resources.py`（路径拼接与 YAML 读取的**唯一**落点） |
| 日志里 traceId 断了或串号 | `core/trace.py` | `core/logging.py`（从 contextvar 自动取） |
| 想改 traceId 的 header 名 | `core/constants.py` `TRACE_ID_HEADER` | ⚠️ 三个服务必须同时改（spec.md §2.8 冻结） |
| 某条 URL 由谁处理 | `api/v1/` 下按路径找 | `main.py` 的 `include_router` |
| 分析结果不对 | `service/analysis_service.py` | T5 后的 `cleaner/normalizer/matcher` |
| LLM 没生效 / 一直 `degraded=true` | `core/config.py` `llm_enabled` | 仓库根 `.env.example` 的三个 `LLM_*` 变量 |
| 启动就崩，报配置错误 | `core/config.py` | `.env`（相对**进程 CWD** 解析，不是文件位置） |
| 想替换 Service 做测试 | `core/dependencies.py` | 用 `app.dependency_overrides[...]`，不要 monkeypatch |
| 上传的 PDF 解析报错 / 文本抽不干净 | `service/pdf_parser.py` | 换库改这里；**别在别处 import pypdf**（有测试守） |
| 抽出来的文本错乱 / 段落粘成一片 | `service/cleaner.py` `merge_broken_lines` | `core/constants.py` 的 `READING_ORDER_*` 阈值 |
| 章节切不出来（`sections` 只有 `header`） | `service/cleaner.py` `SECTION_ALIASES` | 先看**清洗后的文本**，行结构塌了的话加别名也没用 |
| 文本里出现 `\uf06c` 这类怪字符 | `service/cleaner.py` `_SYMBOL_GLYPH_RE` | 图标字体的私用区字形；行首的会被换成 `•` |
| 想支持新格式（xlsx / txt） | `service/parser_plugin.py` `default_registry()` | 新写一个 `*_parser.py`，`cleaner` 一行都不用动 |
| 想知道某份样本为什么解析成这样 | `tests/integration/test_real_resume_samples.py` | 真样本门禁；样本缺失时会 skip |

## 变更路径 —— 要改什么 → 动哪些文件 → 千万别动

| 要改什么 | 动哪些文件 | 千万别动 |
|---|---|---|
| 加一个错误码 | `core/exceptions.py` **+ 先改 `spec.md` §2.3** | 不要 `raise HTTPException`（业务层不认识 HTTP） |
| 加一个接口 | `api/v1/` 新建 → `service/` 加方法 → `schema/` 加形状 | 不要把算法写进 `api/` |
| 改响应字段 | `schema/response/` **+ 先改 `spec.md` §2.2** | 冻结契约，改它等于改三份 OpenAPI |
| 加一个算法步骤 | `service/` 下新建纯函数模块 | 不要在 `schema/` 的 validator 里做计算 |
| 加配置项 | `core/config.py` + 仓库根 `.env.example` | 两处必须同步 |
| 加一个数据资源文件（YAML） | `app/data/<name>.yaml` + 用 `core/resources.py` 的 `resource_path` / `read_yaml` 读 | **路径拼接只允许出现在 `core/resources.py` 一处**；`core` 不得 import `service`，所以「解释成领域对象」留在各自 service |
| 换日志格式 | `core/logging.py` | traceId 来源别改成手写参数（会漏） |
| 引入 LLM（T5） | `llm/` 新建 + `service/` 编排 + `core/dependencies.py` 装配 | 不要在 `api/` 里直接调 LLM |
| 加一种文档格式 | 新建 `service/<fmt>_parser.py` + `parser_plugin.py` 注册一行 | 不要改 `cleaner.py`（清洗与格式无关）；入口白名单在 **BFF**，不在本服务 |
| 换 PDF 解析库（ADR-103） | 只改 `service/pdf_parser.py` | 不要把 pypdf 的 API 泄漏到 `ParseResult` 之外 |
| 加一个章节别名 | `service/cleaner.py` `SECTION_ALIASES` | 别名表按「归一化后精确相等」匹配，别加太短的词（会误切正文） |
| 改「有没有文本层」的阈值 | `core/constants.py` `PDF_MIN_TEXT_LAYER_CHARS` | 同步 `spec.md` §2.5（它决定 `PDF_NO_TEXT_LAYER` 的触发点） |

## 未接线清单（先行落地，等主线功能接入）

> 判据：**契约形状与横切组件可以先行；调用链必须跟功能同步进**，否则就是死代码。

| 已就位 | 接线点 | 什么时候接 |
|---|---|---|
| `core/constants.py` 的 `WEIGHT_REQUIRED` / `WEIGHT_PREFERRED` | 无消费者 | T5：`service/matcher.py` |
| `service/{parser_plugin,pdf_parser,docx_parser,cleaner}.py` | 无 HTTP 调用方 | **M4**：`service/analysis_stream_service.py` 的流式编排 |
| `service/parser_plugin.py` 的 `ParserRegistry` | 只有 `default_registry()` 在用 | M4：按 magic number 分派（BFF 已先拦过一道） |
| `service/docx_parser.py` | **故意不接** | 本期 DOCX 属 Out of Scope（spec §1 / AC12）；入口放开只需改 BFF 白名单 |
| `core/constants.py` 的 `RESUME_MAX_LENGTH` / `JD_MAX_LENGTH` | ✅ 已接入 `AnalyzeRequest`；`RESUME_MAX_LENGTH` 另被 `cleaner.clean` 用作截断上限 | — |
| `service/analysis_service.py` 的编排 | ✅ 已接入 `api/v1/internal.py` | T5 填充真实算法 |

## 本地运行

```bash
python -m venv .venv
source .venv/Scripts/activate      # Windows Git Bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

## 测试

```bash
pytest
```

| 测试 | 层次 | 覆盖 |
|---|---|---|
| `unit/test_trace.py` | 单元 | header 透传/回写、**请求结束后 contextvar 被 reset**、非空保证 |
| `unit/test_exception_handlers.py` | 单元 | 400 校验、traceId 贯穿、长度上限、**500 不泄漏堆栈** |
| `unit/test_parser_plugin.py` | 单元 | 注册表（重复注册炸 / 稳定顺序 / 415）、`detect` 不抛错、文本层阈值边界 |
| `unit/test_pdf_parser.py` | 单元 | **正常 / 损坏 / 加密 / 无文本层 / 超页数**、所有者密码不算失败、错误不泄漏内部细节 |
| `unit/test_docx_parser.py` | 单元 | 段落/换行/制表位/表格/修订删除、`.doc` 提示可照做、zip 炸弹拦在解压前 |
| `unit/test_cleaner.py` | 单元 | 隐形字符 / 全半角 / 图标字形 / 合并断行 / 章节切块 / 阅读顺序 / 超长截断 |
| `api/test_health.py` | 接口 | healthz 形状 + 「不得出现 storage 字段」 |
| `api/test_internal.py` | 接口 | ping / analyze 基础行为、traceId 优先级 |
| `api/test_contract_shape.py` | 接口 | **spec.md §2.2 冻结字段快照** |
| `integration/test_real_resume_samples.py` | 集成（门禁） | 20 份真实简历全部抽出干净文本；**PDF 未进 `apps/`**、上传不落盘、只有 `pdf_parser.py` import pypdf |

> 真样本门禁在找不到 `脱敏资料/*.pdf` 时 **skip** 而不是 fail（样本目录不入库，见该文件文档）。

## 配置

见仓库根 `../.env.example`。LLM 三项留空时 `llm_enabled = false`，自动走规则降级分支
（`meta.degraded = true`，这是**主动降级**不是错误）。

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` | 空 | 三项齐全才启用 LLM |
| `LLM_TIMEOUT_SECONDS` | 20 | LLM 调用超时（spec.md §3.3 禁止无超时调用） |
| `LOG_LEVEL` | INFO | 日志级别 |

## 已知缺口

- `/internal/analyze` 返回空结构，真实实现见 `../../sdd/part1/tasks.md` T5
- `parser_plugin` / `pdf_parser` / `cleaner` 已就位但**尚未接入 HTTP**（M4 的流式编排接）
- 尚无 `service/{normalizer,matcher,rules}.py`（技能归一化与匹配）与 `llm/`（客户端与 prompts）
- **行结构塌陷**：`resume_06.pdf` / `resume_08.pdf` 这类 PDF 的换行全靠绝对定位，
  pypdf 抽出来整页是一行 → 章节切不出来（文本本身可用，`sections` 只有 `header`）。
  已试过 `extraction_mode="layout"`：能救 1 份、却让另外 6 份变差，**净负**，故保留默认模式。
  真正的解法是 ADR-103 里的备选 `pdfplumber`，换库只改 `pdf_parser.py`
- **私用区字形**：`_SYMBOL_GLYPH_RE` 把 U+E000–U+F8FF 一律当图标字形删。
  极老的中文字体若把生僻字映射到私用区，会被误删 —— 样本里 100% 是图标，真遇到再收窄范围
- `env_file=".env"` 相对**进程 CWD** 解析：从 `apps/analyzer/` 启动时读不到仓库根 `.env`，
  当前依赖代码里的默认值运行。T7 容器化时统一改为真实环境变量注入
