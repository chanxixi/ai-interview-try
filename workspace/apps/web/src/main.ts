import {
  ElAlert,
  ElButton,
  ElCollapse,
  ElCollapseItem,
  ElConfigProvider,
  ElEmpty,
  ElInput,
  ElLink,
  ElStep,
  ElSteps,
  ElTag,
  ElUpload,
} from 'element-plus';
import { createApp } from 'vue';

import App from './App.vue';
import { router } from './router';

// 样式加载顺序**不能换**：
// 1) Element 自己的 CSS 先落地（定义 --el-* 默认值）
// 2) element-theme.scss 再覆盖（同权重下后加载者胜）
// 3) styles.css 收尾（页面级布局 + 少量对 Element 的微调）
// 把主题放到前面，会出现「主色还是默认蓝」的诡异现象。
import 'element-plus/dist/index.css';
import './styles/element-theme.scss';
import './styles.css';

/**
 * **按需注册**而不是 `app.use(ElementPlus)`。
 *
 * 全量 `app.use` 会把整个组件库打进包（实测 940 KB / gzip 302 KB），
 * 而我们只用十来个组件。逐个注册后 rollup 的 tree-shaking 能删掉未引用的
 * 组件实现 —— 这是前端最容易忽略、收益却最直接的一处优化。
 *
 * 代价：新增用到的 Element 组件时**必须在这里补一行**，否则模板里只是个
 * 不认识的标签（不报错、也不渲染）。所以下面按字母序列全，便于对照。
 *
 * 语言包走 `ElConfigProvider`（按需模式下 `app.use(ElementPlus, { locale })`
 * 那条路不存在了），由 `App.vue` 在最外层包一层。
 */
const components = {
  ElAlert,
  ElButton,
  ElCollapse,
  ElCollapseItem,
  ElConfigProvider,
  ElEmpty,
  ElInput,
  ElLink,
  ElStep,
  ElSteps,
  ElTag,
  ElUpload,
} as const;

const app = createApp(App).use(router);

for (const [name, component] of Object.entries(components)) {
  app.component(name, component);
}

app.mount('#app');
