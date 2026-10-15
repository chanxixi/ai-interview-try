import { fileURLToPath } from 'node:url';

import vue from '@vitejs/plugin-vue';
import { defineConfig } from 'vitest/config';

/**
 * 单测配置（tasks.md M8.4 的 `web` 增量）。
 *
 * - `environment: 'happy-dom'`：`useAnalysisStream` 用到 `fetch` / `FormData` / `TextDecoder`，
 *   需要一个 DOM 形状的全局环境；happy-dom 比 jsdom 轻且启动快。
 * - `include` 只收 `tests/**`：不把 node_modules 里第三方包的测试拖进来。
 *
 * envDir 与 `vite.config.ts` 保持一致（仓库根 `.env`），否则两个入口读到的环境不同。
 */
const envDir = fileURLToPath(new URL('../..', import.meta.url));

/**
 * vitest 默认把缓存（含 `results.json`）写进 `node_modules/.vite/`。
 *
 * **为什么挪走**：缓存是**可再生的构建中间物**，不属于依赖，写进 `node_modules/`
 * 会让「依赖目录」和「临时文件」混在一起 —— 清缓存要动 node_modules，
 * 而任何把 `node_modules` 设为只读的环境（容器层、CI 缓存挂载、受限沙箱）
 * 都会连带让测试跑不起来（症状是 `EPERM: open node_modules/.vite/vitest/results.json`，
 * 报错点在测试**之前**，看起来像配置坏了）。
 *
 * 落到 `workspace/.logs/`（已在 .gitignore）与 pytest 的 `-p no:cacheprovider` 同一个思路：
 * **临时产物集中一处，仓库里不留**。
 */
const cacheDir = fileURLToPath(new URL('../../.logs/vitest-cache', import.meta.url));

export default defineConfig({
  plugins: [vue()],
  envDir,
  // 顶层 `cacheDir` 是 Vite 的选项，vitest 会把缓存写到 `<cacheDir>/vitest`。
  // 不要再写 `test.cache.dir` —— 那个写法已废弃（会打 deprecation 警告）。
  cacheDir,
  test: {
    environment: 'happy-dom',
    include: ['tests/**/*.spec.ts'],
    globals: true,
  },
});
