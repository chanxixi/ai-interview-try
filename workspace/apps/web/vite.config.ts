import { fileURLToPath } from 'node:url';

import vue from '@vitejs/plugin-vue';
import { defineConfig, loadEnv } from 'vite';

/**
 * 环境变量单点维护在**仓库根** `.env`（模板见 workspace/.env.example），
 * 因此这里把 envDir 指到 `../../`，而不是 apps/web。
 */
const envDir = fileURLToPath(new URL('../..', import.meta.url));

/**
 * Vite 的依赖预构建缓存（`deps/`）默认落在 `node_modules/.vite/`。
 *
 * **为什么挪走**：理由与 `vitest.config.ts` 里的 `cacheDir` 完全一致 ——
 * 缓存是**可再生的构建中间物**，不属于依赖。写进 `node_modules/` 会让
 * 「依赖目录」和「临时文件」混在一起；任何把 `node_modules` 设为只读的环境
 * （容器层、CI 缓存挂载、受限沙箱）都会连带让 `dev` / `build` 起不来。
 *
 * 落到 `workspace/.logs/`（已在 .gitignore）：临时产物集中一处，仓库里不留。
 */
const cacheDir = fileURLToPath(new URL('../../.logs/vite-cache', import.meta.url));

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, envDir, '');

  return {
    plugins: [vue()],
    envDir,
    cacheDir,
    server: {
      port: Number(env.WEB_PORT || 5173),
      // 前端只与 BFF 通信（禁止直连 Java / Python，spec.md §3.1）。
      // 走代理而不是写死后端地址，避免 CORS 并让后端地址可配置。
      proxy: {
        '/api': {
          target: env.BFF_URL || 'http://localhost:3000',
          changeOrigin: true,
        },
      },
    },
    css: {
      preprocessorOptions: {
        // Vite 5 默认走 sass 的 legacy API（Dart Sass 2.0 会移除），
        // 显式切到 modern API：构建日志干净，也避免未来升级直接报错。
        scss: { api: 'modern' as const },
      },
    },
    build: {
      // Element Plus 的按需 tree-shaking 依赖 rollup 自己的依赖分析：
      // 一旦把 `element-plus` 写进 manualChunks，它就会被当成「整包一起搬」，
      // 体积不降反升（实测 940 KB → 拆开后按需只剩 130 KB）。
      // 所以这里只手动拆 vue / echarts，Element 交给 rollup 按实际引用决定。
      // 不覆盖 chunkSizeWarningLimit：默认 500 KB 的告警留着，才能发现真的变大。
      rollupOptions: {
        output: {
          manualChunks: {
            'vendor-vue': ['vue', 'vue-router'],
            'vendor-echarts': [
              'echarts/core',
              'echarts/charts',
              'echarts/components',
              'echarts/renderers',
            ],
          },
        },
      },
    },
  };
});
