import pino from 'pino';

import { config } from './config';

/**
 * 结构化 JSON 日志（spec.md §2.8）。
 *
 * 每条日志都带 `service` 与 `traceId`，便于按 traceId 全链 grep。
 */
export const logger = pino({
  level: config.logLevel,
  base: { service: config.serviceName, version: config.version },
  timestamp: pino.stdTimeFunctions.isoTime,
  formatters: {
    level: (label) => ({ level: label }),
  },
  // 密钥绝不进日志（spec.md §3.3）
  redact: {
    paths: [
      'req.headers.authorization',
      'req.headers.cookie',
      '*.apiKey',
      '*.api_key',
      '*.password',
      '*.MYSQL_PASSWORD',
    ],
    censor: '[REDACTED]',
  },
});

export type Logger = pino.Logger;
