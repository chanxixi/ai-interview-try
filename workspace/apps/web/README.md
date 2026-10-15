# web — Vue 3 前端

链路位置：`**Vue** → BFF → job-service → analyzer → LLM`

## 职责

- 文件拖拽与**本地预校验**（不合法则不发请求）、流式渲染、结果可视化、错误提示
- 把 SSE 事件翻译成响应式状态（阶段条 / 思考文本 / 结果面板）

## 禁止（spec.md §2.7）

- 解析 PDF、判断技能、自行排序推荐、直连 Java / Python
- **重排推荐**：顺序由后端给定（`(-score, jobId)`），前端再排一次会让并列项顺序不稳定

## 目录（part2）

```
src/
├─ main.ts                      入口：路由 + Element Plus **按需注册**
├─ App.vue                      外壳：顶栏 + <el-config-provider> + RouterView
├─ router/index.ts              / → /analyzer；/connectivity 承载 part1 连通页
├─ styles.css                   页面级布局（Element 不提供的部分）
├─ styles/element-theme.scss    主题：覆盖 --el-color-primary 及其派生色阶
├─ api/
│  ├─ client.ts                 part1：fetch 封装 + 统一错误体
│  ├─ types.ts                  part1：ping / 错误体类型
│  └─ analysis.ts               part2：SSE 事件、result 五块、stage 顺序（契约镜像）
├─ components/                  part1：ChainPanel / HopCard（连通页专用）
├─ utils/
│  ├─ chain.ts                  递归 downstream → 线性跳数
│  ├─ sse.ts                    ★ 增量分帧器（跨 chunk 截断的唯一防线）
│  └─ upload.ts                 ★ 本地预校验（大小 / MIME / magic number）
└─ pages/
   ├─ connectivity/index.vue    part1 连通页原样迁入（功能不丢）
   └─ analyzer/
      ├─ index.vue              两栏布局：左输入 / 右过程与结果
      ├─ composables/useAnalysisStream.ts   ★ 流式状态机（可脱离组件单测）
      └─ components/
         ├─ UploadPanel.vue     el-upload 拖拽 + 本地预校验 + 文本入口
         ├─ StageProgress.vue   el-steps × 7 阶段
         ├─ ThinkingConsole.vue 打字机式追加 LLM 增量
         ├─ ScoreRing.vue       ECharts 分数环（按需引入）
         ├─ MatchList.vue       命中/缺口 + 双向证据折叠
         ├─ IssueList.vue       简历诊断（唯一由 LLM 产出的内容）
         ├─ RecommendList.vue   Top-3 卡片（不重排、不截断）
         └─ ResultPanel.vue     结果五块的布局 + 降级/截断提示
tests/
├─ unit/sse.spec.ts             ★ 跨 chunk 截断（含逐字节切分）
└─ unit/useAnalysisStream.spec.ts  ★ 事件序列 / 415 同步错误 / 流内 error / 容错
```

## 本地运行

```bash
npm install
npm run dev          # http://localhost:5173 → 自动跳 /analyzer
```

`/api` 由 Vite 代理到 BFF（`BFF_URL`，默认 `http://localhost:3000`），因此不存在跨域问题，也不会绕过 BFF 直连后端。

## 校验

```bash
npm run type-check   # vue-tsc --noEmit
npm test             # vitest run（19 条）
npm run build        # vue-tsc + vite build（产物会按 vue / echarts 拆 chunk）
```

## 溯源地图（给个现象 → 看哪个文件）

| 现象 | 先看 |
|---|---|
| 阶段条不动 / 少一格 | `utils/sse.ts` 的分帧 → `composables/useAnalysisStream.ts` 的 `applyStage` |
| 思考文本一次性蹦出来 | `components/ThinkingConsole.vue` 的 tick 节奏 |
| 传了非 PDF 却"没反应" | `utils/upload.ts` 的本地预校验（**预期**：不发请求，只提示） |
| 传了 PDF 却被 415 | BFF `upload.middleware.ts`（magic number 判据）→ 与本地判据是否一致 |
| 推荐顺序两次不一样 | 不该发生；查后端排序键（前端不排序） |
| 分数环空白 | `ScoreRing.vue`：ECharts 未按需注册 / 容器高度为 0 |
| 主题变回默认蓝 | `main.ts` 里 CSS 的**加载顺序**（theme 必须在 element-plus 之后） |
| 新增 Element 组件不渲染 | `main.ts` 的按需注册表里补一行 |

## 已知缺口

- 未引入 Pinia：状态都在页面内，跨页共享只有 traceId（够用，不提前引入）
- 未做 SSE 自动重连（ADR-104：本期只提示错误，不自动重试）
- `el-upload` 未接 `before-upload` 的服务端校验（校验在 BFF，且是**权威**判据）
