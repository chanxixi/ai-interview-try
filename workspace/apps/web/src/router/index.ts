import { createRouter, createWebHistory } from 'vue-router';

/**
 * 路由表（tasks.md M7.2）。
 *
 * - `/` → `/analyzer`：**默认落在简历分析页**（part2 的主入口），
 *   而不是把 part1 的连通页留在根路径 —— 演示时打开就是正题。
 * - `/connectivity`：part1 的全链连通性自检**整体迁入**，功能不丢（M7.2 的硬要求）。
 *
 * 两个页面都用动态 `import()`：首屏只加载分析页需要的 chunk，
 * 连通页（只在排障时才看）不拖慢正常打开速度。
 */
export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/analyzer' },
    {
      path: '/analyzer',
      name: 'analyzer',
      component: () => import('../pages/analyzer/index.vue'),
      meta: { title: '简历分析' },
    },
    {
      path: '/connectivity',
      name: 'connectivity',
      component: () => import('../pages/connectivity/index.vue'),
      meta: { title: '全链自检' },
    },
    // 兜底：未知路径回首页，避免演示时手抖打错就白屏
    { path: '/:pathMatch(.*)*', redirect: '/analyzer' },
  ],
});
