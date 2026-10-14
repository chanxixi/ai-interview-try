# web — Vue 3 前端

链路位置：`**Vue** → BFF → job-service → analyzer`

## 职责

- 表单、loading、结果可视化、错误提示

## 禁止

- 业务判断、直连 Java / Python（spec.md §3.1）

## 目录

```
src/
├─ main.ts                入口
├─ App.vue                页面骨架：触发检查 + 状态编排
├─ styles.css             手写样式（T6 会由 shadcn-vue 组件替换）
├─ api/
│  ├─ client.ts           fetch 封装 + 统一错误体解析
│  └─ types.ts            与 BFF 的接口类型
├─ components/
│  ├─ ChainPanel.vue      链路面板（逐跳）
│  └─ HopCard.vue         单跳卡片
└─ utils/
   └─ chain.ts            递归 downstream → 线性跳数列表
```

## 本地运行

```bash
npm install
npm run dev          # http://localhost:5173
```

`/api` 由 Vite 代理到 BFF（`BFF_URL`，默认 `http://localhost:3000`），因此不存在跨域问题，也不会绕过 BFF 直连后端。

## 测试

```bash
npm run type-check   # vue-tsc
```

## 骨架阶段的已知缺口

- 只有连通性自检面板，简历提交与分析结果界面见 `../../sdd/part1/tasks.md` T3 / T6
- 未引入 Pinia / ECharts / shadcn-vue（T6）
- 未接单元测试框架（T6 引入 Vitest）
