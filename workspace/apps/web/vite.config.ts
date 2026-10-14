import { fileURLToPath } from 'node:url';

import vue from '@vitejs/plugin-vue';
import { defineConfig, loadEnv } from 'vite';

/**
 * 环境变量单点维护在**仓库根** `.env`（模板见 workspace/.env.example），
 * 因此这里把 envDir 指到 `../../`，而不是 apps/web。
 */
const envDir = fileURLToPath(new URL('../..', import.meta.url));

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, envDir, '');

  return {
    plugins: [vue()],
    envDir,
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
  };
});
