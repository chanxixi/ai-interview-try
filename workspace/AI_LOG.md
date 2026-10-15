# AI_LOG.md — AI 协作留痕

> 用途：记录**人对 AI 产出做了什么改造、为什么改**。
>
> 这份日志存在的理由只有一个：本项目的组件库与骨架由 AI 生成，
> 而「纯 AI UI」（默认主题 + 默认交互 + 无改造痕迹）在答辩里是要扣分的
> （`sdd/part2/plan.md` ADR-107）。所以下面每条都写到「**改了哪个属性 / 哪一行，为什么**」，
> 而不是「优化了 UI」。

---

## 0. 安全约定（全程遵守）

| 项 | 约定 | 落地位置 |
|---|---|---|
| 密钥 | **不入档、不打印**。LLM 的 API Key 只从环境变量读，日志里永远只出现「有没有配」 | `apps/analyzer/app/llm/client.py` |
| 简历正文 | **不入档、不入日志**。日志只允许 `traceId` / 字节数 / 文本长度 / `sha256` 前 8 位 | `apps/analyzer/app/api/v1/stream.py`、BFF `analysis.service.ts` |
| 上传物 | **一律不落盘**（内存中处理完即释放），仓库内不存在任何 `.pdf` 中间产物 | BFF `upload.middleware.ts`（memoryStorage）+ `workspace/.gitignore` 的 `*.pdf` 兜底 |
| 演练样本 | 降级演练用的两个假样本**现场生成**（几十字节、内容是我们自己写的），**不使用真简历** | `scripts/drill_fixtures.py` → 落在 `.logs/drills/`（已 gitignore） |
| 本文件 | 只写「做法与理由」，**不粘贴任何简历片段 / JD 原文 / 密钥** | —— |

---

## part2 · 前端改造留痕

### L1 `el-upload` 关掉自动上传与内置文件列表

- **改了什么**：`UploadPanel.vue` 上 `:auto-upload="false"`、`:show-file-list="false"`，
  自己画了一条「已选文件」信息条（`.picked`）。
- **为什么**：`el-upload` 默认「选中即 POST」，而本项目的提交是
  **`POST /api/analysis/stream`（multipart + `jobId`）且必须由页面统一发起** ——
  否则换一次文件就会多打一次分析，后端白跑一次 LLM。
  内置文件列表的删除按钮只清组件内部状态，会与页面持有的 `File` 对象脱钩，
  所以干脆自绘，保证「界面所见 = 实际会提交的文件」。

### L2 `el-steps` 改横向滚动而不是换行

- **改了什么**：`styles/element-theme.scss` 里 `.analyzer-stages .el-steps { overflow-x: auto; }`，
  并保留 `align-center`。
- **为什么**：7 个阶段在 1280px 以下会被挤压换行，一旦换行，
  「阶段是**线性推进**的」这个最重要的语义就没了。横向滚动牺牲一点横向空间，
  换来「一条直线往前走」的读法。窄屏时同理（媒体查询里也是横向）。

### L3 降级 / 截断提示用「不可关闭的 warning alert」

- **改了什么**：`ResultPanel.vue` 里 `meta.degraded` 与 `meta.truncated` 各渲染一个
  `<el-alert type="warning" :closable="false" show-icon>`。
- **为什么**：这两件事都属于**静默降级** —— 结果看起来完全正常，
  但 `issues` 其实是规则模板生成的、或只分析了前 20000 字。
  静默降级比报错更危险（用户会把模板输出当成 AI 判断），所以：
  ① 位置放在结果最上方；② `type="warning"` 而不是 `info`；③ **不给关闭按钮**。

### L4 Element Plus 从「全量注册」改为「按需注册 12 个组件」

- **改了什么**：`main.ts` 里去掉 `app.use(ElementPlus, {...})`，
  改为显式 `app.component(name, component)` 循环注册；语言包改由
  `App.vue` 的 `<el-config-provider :locale="zhCn">` 注入。
- **为什么**：全量注册把整库打进包（实测 **940 KB / gzip 302 KB**），
  而我们只用 12 个组件。按需后 `vendor` 里的 Element 部分降到 **130 KB / gzip 46 KB**。
  另一处关键：`vite.config.ts` 的 `manualChunks` **不能**写 `element-plus` ——
  一旦写进去，rollup 会当成「整包搬」，tree-shaking 直接失效（第一版就是这么写的，
  体积不降反升）。

### L5 主题：只覆盖 `--el-color-primary` 是不够的

- **改了什么**：`styles/element-theme.scss` 用 `@for` 循环 + `color.mix()`
  生成 `--el-color-primary-light-1..9` 与 `--el-color-primary-dark-2`，主色换成深青 `#0d9488`。
- **为什么**：Element 的按钮 hover / disabled / plain 用的是**派生色阶**，
  只改主色会出现「静止是青色、hover 变回默认蓝」的割裂感。
  手抄 9 个近似色必然有一档偏色，所以用 sass 按 Element 自己的混合比例算。
  （没有走 `theme-chalk` 源码定制：那要重编译整套变量，3 小时里编译代价不划算，
  而 Element 2.x 的颜色已经全部是 CSS 变量。）

### L6 ECharts 按需引入

- **改了什么**：`ScoreRing.vue` 用 `echarts/core` + `echarts.use([GaugeChart, TooltipComponent, CanvasRenderer])`，
  而不是 `import * as echarts from 'echarts'`。
- **为什么**：全量 echarts 约 1 MB，这里只用到一个仪表盘。
  按需后是 392 KB（gzip 133 KB）。同时用 `ResizeObserver` 而非 `window.resize`
  做重绘 —— 侧栏折叠这类不触发 window resize 的场景也能跟着重画。

### L7 打字机是前端「揭示节奏」，不是后端「推得慢」

- **改了什么**：`ThinkingConsole.vue` 把收到的文本放进缓冲，按 28ms 的 tick
  逐字揭示（剩余越多每 tick 揭示越多），流结束时一次性 `flush()`。
- **为什么**：后端确实逐条推 `thinking` 增量，但**一次 delta 多大不受前端控制** ——
  LLM 一次吐 40 字，界面就一次蹦 40 字，观感是卡顿而不是「在思考」。
  收尾必须补齐：流结束还在慢慢打字，用户会以为「还没完」。

---

## part2 · 后端/链路的取舍留痕

### L8 候选集由 Java 装配下发，Python 拿不到 JD 原文

- **改了什么**：`AnalysisOrchestrationService.java` 是**唯一**把领域数据交给 Python 的地方；
  下发的 `jobCandidates` 只含结构化 `requirements`，不含 `jdText`。
- **为什么**：让「数据归 Java、算法归 Python」从**口头约定**变成**物理保证** ——
  Python 手里没有 JD 原文，就写不出「自己连库查岗位」的代码。
  代价：精确匹配（指定 `jobId`）时要额外把该岗位的 `jdText` 塞进 `jobCandidates[0]`，
  由 Java 显式决定（见 `sdd/part2/plan.md` §3）。

### L9 流式错误分两条路：建流前走 HTTP，建流后走 SSE

- **改了什么**：大小 / 类型校验放在 BFF 中间件（建流前，返回 413 / 415）；
  损坏 / 加密 / 无文本层放在 Python 编排层（建流后，发 `event: error`）。
- **为什么**：`ctx.status = 200` + `flushHeaders()` 一旦执行，**状态码就改不了了**。
  最初把「至少提供一个输入」的校验放在 service 里，结果什么都没传时
  返回的是「200 + 空流」，用户完全看不出哪里错了。校验点因此前移到中间件。

---

## part2 · M8 联调与降级演练留痕

> 这一节记的都是**AI 自己的错**：不是「我做了什么」，而是「我漏了什么、怎么发现的、怎么修的」。
> 降级路径的共同特征是「不跑也不会报错」，所以下面每条都是**主动制造故障**才暴露出来的。

### L10 扫描件会一路走到 `result`（AI 漏接策略，演练 3 暴露）

- **现象**：`PDF_NO_TEXT_LAYER` 这个错误码在 `ErrorCode` 里定义了，
  但**全仓没有任何地方抛出它**。扫描件因此拿到一份「0 技能 / 0 推荐」、结构完全正常的响应。
- **根因**：M2 的 `pdf_parser.py` 明确把「要不要因此报错」留给上层
  （解析器只报事实 `has_text_layer=False`），而 M4 的流式编排**没有接**。
  两处 docstring 都写着「这是上层策略」，**两边都以为对方做了**。
- **为什么危险**：这不是报错，是**静默的错**。用户会以为简历写得不好，
  真正的原因（文件里根本没有文字）被彻底藏起来；而 `error` 与 `result` 的互斥约束
  也没能拦住它 —— 因为压根没发 `error`。
- **改了什么**：`analysis_stream_service.py` 的 `parsed` 阶段，解析成功后判
  `has_text_layer`，不达标就抛 `AppException(PDF_NO_TEXT_LAYER)`；
  已有的 `except AppException` 会留下 `fail` + `code` 的 stage 记录，再走 `error → done`。
  新增 `test_scanned_pdf_is_reported_as_no_text_layer` 钉住。
- **教训**：**「留给上层」的约定必须有一个明确的落点**。写「这是上层的策略」时，
  必须同时说清「哪个文件、哪个函数」——否则它就是一句没人认领的注释。

### L11 演练脚本的断言不能只写「类型对」

- **现象**：新加的用例断言 `parsed[-1]["code"]`，报 `KeyError: 'code'`。
- **根因**：`_stage_frame(..., **detail)` 把附加字段统一塞进 `detail` 子对象，
  所以是 `parsed[-1]["detail"]["code"]`。
- **为什么值得记**：这跟 S-4（`sections` 变逐字符列表）是**同一类错** ——
  断言写得太浅，看不出值的**形态**。契约测试要断言到「字段在哪一层、是什么形状」。

### L12 BFF 有一条测试从写下就一直是红的

- **现象**：`tests/unit/upload.middleware.test.ts` 的
  「非字符串字段被丢弃」失败，抛 `AppError: file 与 resumeText 至少提供一个`。
- **根因**：这条用例只传了 `{ a: '1', b: 2, c: null }`，没有 `file`、也没有 `resumeText`。
  而 `extractUpload` 收尾会调 `ensureHasInput` —— **「既没文件也没文本」是 400，是有意为之**。
  于是这条用例实际测的是「空请求被拒」，不是「非字符串被丢弃」。
- **改了什么**：用例补一个合法的 `resumeText`，断言改成
  `{ a: '1', resumeText: '张三' }`（非字符串的 `b` / `c` 仍被丢弃）。
- **教训**：**写完测试必须真跑一遍**。这条从写下到被发现一直是红的，
  而「红」在没跑过的情况下跟「绿」看起来一样。

### L13 降级演练用 socket，不用 `curl --max-time`

- **改了什么**：演练 5（AC19 连上就断）用 `socket.create_connection` → 发请求 →
  `recv(64)` → `close()`，跑 20 次。
- **为什么不能用 curl**：整条流（LLM 关着）只要**几十毫秒**，
  `curl --max-time 0.3` 大概率是**跑完了**才退出 —— 那样测的是「正常请求」，不是「断连」。
  必须用 socket 才能确定地做到「在服务端还在写的时候拆连接」。
- **顺带**：`STREAM_ABORTED` 是 BFF 侧**仅日志**的错误码（不进响应体），
  所以断言要去日志里数，而不是看响应。

### L14 更正 DELIVERY 里一条**没有依据**的偏离记录

- **现象**：`DELIVERY.md` §7 的 D-1 声称「**施工单**要求 Java 用 MyBatis-Plus，
  本步决定改用 MyBatis-Plus」，并据此写了一段「代价与回退」。
- **核查**：全仓 grep（`sdd/` 三份文档 + `docs/` + `pom.xml`）**没有任何地方提到 MyBatis-Plus**。
  `sdd/part2/tasks.md` M5.3 的原话是「`repository/impl/` **双实现（JPA + InMemory）** +
  `@ConditionalOnProperty`」。实际实现也确实是 Spring Data JPA（`pom.xml` 里只有
  `spring-boot-starter-data-jpa`）。
- **改了什么**：D-1 重写为「**保留 JPA，未引入 MyBatis-Plus**」，
  并指出真实偏离是「双实现 + 条件装配 → 单实现 + 数据源 URL 切换」（与 D-9 同源）。
- **教训（最重要的一条）**：**偏离登记比正文更需要核实**。
  正文写错，读者会去代码里对照；偏离登记写错，读者会**相信它**，
  并据此以为「代码没按需求做」——一个不存在的偏差，比一个没登记的偏差危害更大。
  以后写 ADR / 偏离登记，**每条都要能指到原文的行**。

### L15 vitest 缓存移出 `node_modules`

- **改了什么**：`apps/web/vitest.config.ts` 加顶层 `cacheDir`，指向 `workspace/.logs/vitest-cache`。
- **为什么**：默认的 `node_modules/.vite/` 在当前环境里不可写，vitest 写 `results.json`
  时 `EPERM`，**报错点在测试之前**，看起来像配置坏了。
- **不只是 workaround**：缓存是可再生的构建中间物，写进依赖目录本身就不对 ——
  任何把 `node_modules` 设为只读的环境（容器层、CI 缓存挂载）都会连带让测试跑不起来。
  与 pytest 的 `-p no:cacheprovider` 同一个思路。
- **踩坑**：`test.cache.dir` 这个写法已废弃（会打 deprecation 警告），要用 Vite 的顶层 `cacheDir`。

---

## 提交纪律

- 本仓库**禁止未经人工审核的提交**（`sdd/part1/spec.md` §3.5 / part2 附录 C）。
  文档里写「提交 xxx」= 「准备好一次提交」，实际 commit 由人执行。
- `AI_LOG.md` 与 `DELIVERY.md` 都**不含**简历正文、JD 原文、任何密钥。
