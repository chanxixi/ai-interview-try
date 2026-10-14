import pino from 'pino';

import { config } from '../config';

/**
 * 结构化 JSON 日志（spec.md §2.8）。
 *
 * 两条约定：
 *   1. 每条日志都带 `service` / `version`，容器里多服务混流时能分清来源
 *   2. 请求级日志用 `logger.child({ traceId })`（见 middleware/traceId.middleware.ts），
 *      这样按 traceId 就能 grep 出全链
 *
 * 密钥绝不进日志（spec.md §3.3）—— redact 是最后一道保险，不是第一道。
 */
export const logger = pino({
  level: config.logLevel,
  base: { service: config.serviceName, version: config.version },
  timestamp: pino.stdTimeFunctions.isoTime,
  formatters: {
    level: (label) => ({ level: label }),
  },
  redact: {
    paths: [
      'req.headers.authorization',
      'req.headers.cookie',
      '*.apiKey',
      '*.api_key',
      '*.password',
      '*.MYSQL_PASSWORD',
      '*.LLM_API_KEY',
    ],
    censor: '[REDACTED]',
  },
});

export type Logger = pino.Logger;
