import type { Server } from 'node:http';

import { createApp } from './app';
import { config } from './config';
import { buildContainer } from './container';
import { logger } from './util/logger';

/**
 * BFF 启动入口。
 *
 * 只负责三件事：建容器 → 监听 → 优雅退出。
 * 请求处理逻辑全部在 app.ts / controller / service 里，便于测试。
 */
const container = buildContainer();
const app = createApp(container);

const server: Server = app.listen(config.port, () => {
  logger.info(
    {
      port: config.port,
      envFile: config.envFile,
      jobService: config.jobService,
      analyzer: config.analyzer,
    },
    'bff listening',
  );
});

/** 优雅退出：先停止接收新连接，再关闭进程，避免请求被硬切。 */
function shutdown(signal: string): void {
  logger.info({ signal }, 'shutting down');
  server.close((error) => {
    if (error) {
      logger.error({ err: error }, 'shutdown failed');
      process.exit(1);
    }
    logger.info('shutdown complete');
    process.exit(0);
  });
}

for (const signal of ['SIGINT', 'SIGTERM'] as const) {
  process.on(signal, () => shutdown(signal));
}
