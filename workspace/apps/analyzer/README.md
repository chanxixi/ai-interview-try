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
│  ├─ stream.py                         ★ 流式端点：建流前校验 + StreamingResponse 三个头
│  └─ internal.py                       同步端点（part2 的降级路径；`deep` 在此明确 400）
├─ service/                             ② 业务层：**按功能域分组**（每个组一个 __init__.py 说明边界）
│  ├─ document/                        文件 → 干净文本
│  │  ├─ parser_plugin.py              ★ 解析器「插件」框架：协议 + 注册表 + 组合根
│  │  ├─ pdf_parser.py                 ★ **唯一** import pypdf 的文件（M2.2，CI 门禁②守着）
│  │  ├─ docx_parser.py                自己用标准库实现的 Word 解析（本期预留，见 DELIVERY.md D-2）
│  │  └─ cleaner.py                    ★ 文本清洗七步（M2.4）
│  ├─ skill/                           技能归一化（独立领域：别名 / 分类 / 去重）
│  │  └─ normalizer.py                 ★ SkillDictionary 领域对象
│  ├─ match/                           匹配与推荐（共用同一套打分口径）
│  │  ├─ matcher.py                    ★ **唯一**的匹配打分公式（score_of）
│  │  └─ recommender.py                Top-N 推荐（只调 matcher，不自己算分）
│  ├─ advice/                          part2 规则建议（判的是「简历写得好不好」）
│  │  └─ rules.py                      五条检测 + 供 part3 复用的量化/时间原语
│  ├─ profile/                         part3 能力画像（判的是「vs 这个岗位」）
│  │  ├─ rubric.py                     ★ 六维 rubric 的读入口（宽容加载）
│  │  ├─ advisor_rules.py              ★ 判定 / 六维判档 / 优化点 / 方向的**规则兜底**
│  │  └─ ability_profile.py            ★ 档位→分数与加权求和 `overall` 的**唯一**实现
│  └─ orchestration/                   编排层：只管顺序 / 时序 / 容错，不管算法
│     ├─ analysis_service.py           同步编排（骨架 stub；流式才是真实实现）
│     ├─ stream.py                     ★ 流式编排：**唯一**按 spec §2.4 发事件的地方
│     ├─ frames.py                     SSE 帧构造 + 阶段计时（只管「发什么形状」）
│     └─ mappers.py                    内部领域对象 → 契约 DTO（**唯一**的字段名转换点）
├─ llm/                                ③ LLM 客户端（唯一的外部智能依赖，失败即降级）
│  ├─ events.py                        事件类型 + `LlmClient` 协议（三个模块共享的类型）
│  ├─ prompts.py                       Prompt-2（issues）/ Prompt-3（判定+六维档）/ Prompt-4（文案）
│  ├─ parsers.py                       parse_issues / parse_review / parse_advice（**宁可丢不可编**）
│  └─ client.py                        stream_issues / stream_review / stream_advice（三层降级同形）
├─ data/                               仓库数据（随代码分发的只读资源，由 core/resources.py 读）
│  ├─ skills.yaml                      技能词典真源（C4）
│  └─ rubric.yaml                      ★ part3：六维定义 / 可读信号 / 档位分 / 按 level 分档的权重
├─ schema/                             ④ DTO：契约形状的唯一落点
│  ├─ request/analyze_request.py
│  └─ response/{analyze,error,health}_response.py + sse_event.py
├─ core/                               横切：配置 / 常量 / 资源 / 可观测 / 错误 / 装配
│  ├─ config.py                        可被环境覆盖的值（端口、密钥）
│  ├─ constants.py                     永不随环境变化的值（长度上限、权重、枚举、header 名）
│  ├─ resources.py                     ★ `app/data/*.yaml` 的唯一读取点（路径 + 解析 + 顶层校验）
│  ├─ errors/                          错误码 + 唯一把异常翻译成 HTTP 的地方
│  │  ├─ exceptions.py                 ErrorCode + AppException
│  │  └─ exception_handlers.py         ★ handler 是唯一出口
│  ├─ observability/                   日志 + traceId（两者共同决定「日志里有没有 traceId」）
│  │  ├─ trace.py                      ★ ContextVar + TraceIdMiddleware
│  │  └─ logging.py                    结构化 JSON，traceId 自动注入
│  └─ wiring/                          ★ 组合根：**唯一**允许 import service 的 core 子目录
│     └─ dependencies.py               装配具体实现的地方
└─ util/                               无状态工具
   ├─ rounding.py                      ★ 四舍五入口径的唯一实现（matcher 与 ability_profile 共用）
   └─ http/                            往外写字节：响应体 + SSE 帧
      ├─ response.py                   错误响应体的唯一构造点
      └─ sse.py                        ★ SSE 线上格式的唯一真源（发帧与解帧同一份代码）
```

**依赖方向**（指南 §1.1）：`api → service → schema`；`core` / `util` 是横切，
可被任意层引用，但 **`core` 不得 import `service`**。

**注意 `api/v1/` 只是目录分组**：路径上**不加** `/v1` 前缀 —— `spec.md §2.2` 的
路径是冻结契约。真要并行维护两版时，改 `include_router(prefix=...)` 即可，不用挪文件。

## 溯源地图 —— 现象 → 该看哪个文件

| 现象 | 第一个该看的文件 | 再看 |
|---|---|---|
| 接口报错，但不知道 `code` 从哪来 | `core/errors/exceptions.py` | `core/errors/exception_handlers.py` |
| 入参校验失败返回 422 而不是 400 | `core/errors/exception_handlers.py` `handle_validation` | FastAPI 默认 422，契约里 422 属 ANALYSIS_FAILED |
| 错误响应里出现了堆栈 / 异常类名 | `core/errors/exception_handlers.py` | `util/http/response.py` |
| 响应字段名/层级变了，前端解析失败 | `schema/response/analyze_response.py` | ⚠️ 这是 spec.md §2.2 冻结契约 |
| 想改长度上限 / 打分权重 | `core/constants.py` | 同步 `spec.md` §2.1 / ADR-002 + 契约 |
| 词典认不出某个技能 / 要加一个数据文件 | `app/data/skills.yaml` | `core/resources.py`（路径拼接与 YAML 读取的**唯一**落点） |
| 日志里 traceId 断了或串号 | `core/observability/trace.py` | `core/observability/logging.py`（从 contextvar 自动取） |
| 想改 traceId 的 header 名 | `core/constants.py` `TRACE_ID_HEADER` | ⚠️ 三个服务必须同时改（spec.md §2.8 冻结） |
| 某条 URL 由谁处理 | `api/v1/` 下按路径找 | `main.py` 的 `include_router` |
| 分析结果不对 | `service/orchestration/analysis_service.py` | T5 后的 `cleaner/normalizer/matcher` |
| LLM 没生效 / 一直 `degraded=true` | `core/config.py` `llm_enabled` | 仓库根 `.env.example` 的三个 `LLM_*` 变量 |
| 启动就崩，报配置错误 | `core/config.py` | `.env`（相对**进程 CWD** 解析，不是文件位置） |
| 想替换 Service 做测试 | `core/wiring/dependencies.py` | 用 `app.dependency_overrides[...]`，不要 monkeypatch |
| 上传的 PDF 解析报错 / 文本抽不干净 | `service/document/pdf_parser.py` | 换库改这里；**别在别处 import pypdf**（有测试守） |
| 抽出来的文本错乱 / 段落粘成一片 | `service/document/cleaner.py` `merge_broken_lines` | `core/constants.py` 的 `READING_ORDER_*` 阈值 |
| 章节切不出来（`sections` 只有 `header`） | `service/document/cleaner.py` `SECTION_ALIASES` | 先看**清洗后的文本**，行结构塌了的话加别名也没用 |
| 文本里出现 `\uf06c` 这类怪字符 | `service/document/cleaner.py` `_SYMBOL_GLYPH_RE` | 图标字体的私用区字形；行首的会被换成 `•` |
| 想支持新格式（xlsx / txt） | `service/document/parser_plugin.py` `default_registry()` | 新写一个 `*_parser.py`，`cleaner` 一行都不用动 |
| 想知道某份样本为什么解析成这样 | `tests/integration/test_real_resume_samples.py` | 真样本门禁；样本缺失时会 skip |
| SSE 事件少了一帧 / 顺序不对 | `service/orchestration/stream.py` | `schema/response/sse_event.py` 的 `STAGE_ORDER`；契约同步见 CI 门禁⑧ |
| 深分析没出那四个块 | `service/orchestration/stream.py` 的 reviewed 阶段 | `api/v1/stream.py` 有没有收到 `analysisDepth`（**三层都要透传**，见 DELIVERY §7 D-16） |
| 六维分 / 综合分不对 | `service/profile/ability_profile.py`（**唯一**公式） | `app/data/rubric.yaml`（档位分 + 权重）；`overall` 的手算依据见 DELIVERY §8.3 |
| 某个维度「无依据」/ 雷达图缺一角 | `app/data/rubric.yaml` 的 `signals` + `service/profile/advisor_rules.py` 判档 | `L0` 是常态不是缺点（spec §2.5.2 ①）；前端必须显示「无依据」而不是 0 |
| 断 LLM 后四块空了 / 想调兜底判据 | `service/profile/advisor_rules.py` | **与 `rules.py` 同源**（量化 / 时间正则只有一份） |
| 改权重（或换岗位档位） | `app/data/rubric.yaml` 的 `weights` | **只改这一处**；Java 读的是同一份文件（Maven 资源并入） |
| 改了 `rubric.yaml` 但 Java 没生效 | `apps/job-service/pom.xml` 的第二个 `<resource>` | `RubricWeightsProvider` 从 classpath 读，缺了它权重字段会是 null（Python 会回退，不会报错） |

## 变更路径 —— 要改什么 → 动哪些文件 → 千万别动

| 要改什么 | 动哪些文件 | 千万别动 |
|---|---|---|
| 加一个错误码 | `core/errors/exceptions.py` **+ 先改 `spec.md` §2.3** | 不要 `raise HTTPException`（业务层不认识 HTTP） |
| 加一个接口 | `api/v1/` 新建 → `service/` 加方法 → `schema/` 加形状 | 不要把算法写进 `api/` |
| 改响应字段 | `schema/response/` **+ 先改 `spec.md` §2.2** | 冻结契约，改它等于改三份 OpenAPI |
| 加一个算法步骤 | `service/` 下新建纯函数模块 | 不要在 `schema/` 的 validator 里做计算 |
| 加配置项 | `core/config.py` + 仓库根 `.env.example` | 两处必须同步 |
| 加一个数据资源文件（YAML） | `app/data/<name>.yaml` + 用 `core/resources.py` 的 `resource_path` / `read_yaml` 读 | **路径拼接只允许出现在 `core/resources.py` 一处**；`core` 不得 import `service`，所以「解释成领域对象」留在各自 service |
| 换日志格式 | `core/observability/logging.py` | traceId 来源别改成手写参数（会漏） |
| 引入 LLM（T5） | `llm/` 新建 + `service/` 编排 + `core/wiring/dependencies.py` 装配 | 不要在 `api/` 里直接调 LLM |
| 加一种文档格式 | 新建 `service/<fmt>_parser.py` + `parser_plugin.py` 注册一行 | 不要改 `cleaner.py`（清洗与格式无关）；入口白名单在 **BFF**，不在本服务 |
| 换 PDF 解析库（ADR-103） | 只改 `service/document/pdf_parser.py` | 不要把 pypdf 的 API 泄漏到 `ParseResult` 之外 |
| 加一个章节别名 | `service/document/cleaner.py` `SECTION_ALIASES` | 别名表按「归一化后精确相等」匹配，别加太短的词（会误切正文） |
| 改「有没有文本层」的阈值 | `core/constants.py` `PDF_MIN_TEXT_LAYER_CHARS` | 同步 `spec.md` §2.5（它决定 `PDF_NO_TEXT_LAYER` 的触发点） |
| 加 / 改一个能力维度 | `app/data/rubric.yaml` + `core/constants.py` `DIMENSIONS` **+ 先改 `spec.md` §2.5** | **三处必须同步**（有测试锁「逐字同序」）；只改 YAML 会让雷达图与权重表错位 |
| 改某个维度的可读信号 | `app/data/rubric.yaml` 的 `signals` **+** `service/profile/advisor_rules.py` 的判档策略 | 两处都要动（兜底判档消费 signals，只改一处会**静默**退化成全 `L0`）；DoD 15 |
| 改分档权重 | 只改 `app/data/rubric.yaml` 的 `weights` | **不要改代码**（DoD 12）；`weights` 每档之和必须为 1.0，有测试守 |
| 加一个分级档位 | 只改 `app/data/rubric.yaml` 的 `levels` | **不改 Python 代码**即生效（AC31）：兜底判档用的是「档位序号 → `level_at()`」而不是硬编码 `"L3"` |
| 调 LLM 的判定口径 | `llm/prompts.py` 的 Prompt-3 | 改完**必须复跑 `bash scripts/drill-part3.sh`**（确认兜底仍非空）；DoD 13 |
| 动 `reviewed` 阶段的位置 | `schema/response/sse_event.py` 的 `STAGE_ORDER` | **三处必须同步**：spec §2.4 + 三份 `contracts/*.yaml` + 前端的 `STAGE_ORDER`（CI 门禁⑧守其中两处） |
| 给四项分数加「出处」字段 | 先走 C8：`spec.md` §2.1/§7 + 三份契约的 `AbilityProfile` | 本期**不改**契约（见 DELIVERY §7 **D-13**）；`overall` 的出处现在挂在它的 `dimensions` 上 |

## 未接线清单（先行落地，等主线功能接入）

> 判据：**契约形状与横切组件可以先行；调用链必须跟功能同步进**，否则就是死代码。

| 已就位 | 接线点 | 什么时候接 |
|---|---|---|
| `core/constants.py` 的 `WEIGHT_REQUIRED` / `WEIGHT_PREFERRED` | 无消费者 | T5：`service/match/matcher.py` |
| `service/{parser_plugin,pdf_parser,docx_parser,cleaner}.py` | 无 HTTP 调用方 | **M4**：`service/orchestration/stream.py` 的流式编排 |
| `service/document/parser_plugin.py` 的 `ParserRegistry` | 只有 `default_registry()` 在用 | M4：按 magic number 分派（BFF 已先拦过一道） |
| `service/document/docx_parser.py` | **故意不接** | 本期 DOCX 属 Out of Scope（spec §1 / AC12）；入口放开只需改 BFF 白名单 |
| `core/constants.py` 的 `RESUME_MAX_LENGTH` / `JD_MAX_LENGTH` | ✅ 已接入 `AnalyzeRequest`；`RESUME_MAX_LENGTH` 另被 `cleaner.clean` 用作截断上限 | — |
| `service/orchestration/analysis_service.py` 的编排 | ✅ 已接入 `api/v1/internal.py` | T5 填充真实算法 |

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
| `unit/core/test_trace.py` | 单元 | header 透传/回写、**请求结束后 contextvar 被 reset**、非空保证 |
| `unit/core/test_exception_handlers.py` | 单元 | 400 校验、traceId 贯穿、长度上限、**500 不泄漏堆栈** |
| `unit/document/test_parser_plugin.py` | 单元 | 注册表（重复注册炸 / 稳定顺序 / 415）、`detect` 不抛错、文本层阈值边界 |
| `unit/document/test_pdf_parser.py` | 单元 | **正常 / 损坏 / 加密 / 无文本层 / 超页数**、所有者密码不算失败、错误不泄漏内部细节 |
| `unit/document/test_docx_parser.py` | 单元 | 段落/换行/制表位/表格/修订删除、`.doc` 提示可照做、zip 炸弹拦在解压前 |
| `unit/document/test_cleaner.py` | 单元 | 隐形字符 / 全半角 / 图标字形 / 合并断行 / 章节切块 / 阅读顺序 / 超长截断 |
| `unit/skill/test_normalizer.py` | 单元 | 别名 / 大小写 / 编辑距离兜底 / 边界（`C++` 不被拆成 `C`）/ 词典歧义检查 |
| `unit/match/test_matcher.py` | 单元 | 打分手算（AC18）· 集合自洽 · 四类边界（岗位 0 技能 / 简历 0 技能 / 全命中 / 同技能多条） |
| `unit/match/test_recommender.py` | 单元 | 排序确定性（AC16）· 只调 matcher 不自己算分 · `reason` 模板 |
| `unit/llm/test_rules_llm.py` | 单元 | 规则兜底五条 · Prompt 的安全设计 · 三个解析器的「严进」· **真 HTTP 的真实客户端路径** |
| `unit/orchestration/test_stream.py` | 单元 | SSE 契约（meta 首 / done 尾 / 互斥 / 降级）+ **part3 的 deep 与 standard 两条路径** |
| `unit/profile/test_rubric_consistency.py` | 单元 | `rubric.yaml` ↔ `constants.DIMENSIONS` **逐字同序**；每维 signals 非空 / ≥3 档 / 有 `L0` / 分数单调；权重覆盖六维且每档和 = 1 |
| `unit/profile/test_ability_profile.py` | 单元 | **AC28 手算复现** · `.5` 必须进位（不是银行家舍入）· 缺维归一（N2.2）· 权重是数据（AC31） |
| `unit/profile/test_advisor_rules.py` | 单元 | 判定条数 = `match` 条数 · 六维全有档位 · 两维纯代码可算 · **同源守卫**（与 `NO_QUANTIFY` 看同一批句子）· 兜底不编分 |
| `unit/match/test_seed_consistency.py` | 单元 | `db/seed/jobs/*.json` ↔ `seed.sql` ↔ `skills.yaml` 三处一致 |
| `api/test_health.py` | 接口 | healthz 形状 + 「不得出现 storage 字段」 |
| `api/test_internal.py` | 接口 | ping / analyze 基础行为、traceId 优先级 |
| `api/test_contract_shape.py` | 接口 | **spec.md §2.2 冻结字段快照** + part3 的「两个模型」边界（`standard` 无新键） |
| `integration/test_real_resume_samples.py` | 集成（门禁） | 20 份真实简历全部抽出干净文本；**PDF 未进 `apps/`**、上传不落盘、只有 `pdf_parser.py` import pypdf |

> 真样本门禁在找不到 `脱敏资料/*.pdf` 时 **skip** 而不是 fail（样本目录不入库，见该文件文档）。

**降级演练**（不在 `pytest` 里，单独跑；也可单独调某几条）：

```bash
bash ../../scripts/drill-part3.sh        # part3 四条（进程内打桩，零依赖 → CI 里也跑）
bash ../../scripts/drill-part3.sh 2 3    # 只跑第 2、3 条
```


## 配置

见仓库根 `../.env.example`。LLM 三项留空时 `llm_enabled = false`，自动走规则降级分支
（`meta.degraded = true`，这是**主动降级**不是错误）。

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` | 空 | 三项齐全才启用 LLM |
| `LLM_TIMEOUT_SECONDS` | 20 | LLM 调用超时（spec.md §3.3 禁止无超时调用） |
| `LOG_LEVEL` | INFO | 日志级别 |

## 已知缺口

- **同步** `/internal/analyze` 仍是空结构 stub（part2 起流式才是真实实现）；`analysisDepth=deep`
  在同步入口**明确 400**，不静默降级（见 `../../DELIVERY.md` §8.10 P6）
- **part3 的判定准确率不承诺**（spec §1.3 Non-Goals）：每处展示都带 `rubricRef` + 双向原文证据，
  且前端标注「AI 判定，仅供参考」
- **兜底档位比 LLM 粗**：断 LLM 时只看词与结构，读不懂语义（ADR-206 的取舍）
- **`overall` 没有独立出处字段**：spec 散文与契约冲突，本期取「出处挂在 dimensions 上」，
  见 `../../DELIVERY.md` §7 **D-13**（要落字段需走 C8）
- **权重映射词表在 Java / Python 各一份**（岗位 `level` → 权重档的别名表），见 §8.10 P7
- **行结构塌陷**：`resume_06.pdf` / `resume_08.pdf` 这类 PDF 的换行全靠绝对定位，
  pypdf 抽出来整页是一行 → 章节切不出来（文本本身可用，`sections` 只有 `header`）。
  已试过 `extraction_mode="layout"`：能救 1 份、却让另外 6 份变差，**净负**，故保留默认模式。
  真正的解法是 ADR-103 里的备选 `pdfplumber`，换库只改 `pdf_parser.py`
- **私用区字形**：`_SYMBOL_GLYPH_RE` 把 U+E000–U+F8FF 一律当图标字形删。
  极老的中文字体若把生僻字映射到私用区，会被误删 —— 样本里 100% 是图标，真遇到再收窄范围
- `env_file=".env"` 相对**进程 CWD** 解析：从 `apps/analyzer/` 启动时读不到仓库根 `.env`，
  当前依赖代码里的默认值运行（`scripts/start-all.sh` 会 `source` 它再启动）。T7 容器化时统一改为真实环境变量注入

