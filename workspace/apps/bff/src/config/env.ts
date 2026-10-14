import path from 'node:path';

import { config as loadEnvFile } from 'dotenv';
import { z } from 'zod';

import { TIMEOUT_MS } from './constants';

/**
 * 环境变量加载与校验（spec.md §3.3）。
 *
 * 优先级（高 → 低）：
 *   1. 进程环境变量（容器 / CI 注入）
 *   2. 仓库根 `.env`（单点维护，模板见 workspace/.env.example）
 *
 * dotenv 默认**不覆盖**已存在的变量，正好实现上面的优先级。
 * 密钥绝不硬编码 —— 本文件只读环境，不写默认凭据。
 *
 * ⚠️ 校验失败即 `exit(1)`：宁可启动失败，也不带着半截配置对外服务。
 */
const ENV_FILE = process.env.ENV_FILE ?? path.resolve(__dirname, '../../../../.env');
loadEnvFile({ path: ENV_FILE });

const envSchema = z.object({
  BFF_PORT: z.coerce.number().int().positive().max(65535).default(3000),
  LOG_LEVEL: z
    .enum(['silent', 'fatal', 'error', 'warn', 'info', 'debug', 'trace'])
    .default('info'),

  // ---- 下游 1：job-service（Java / Spring Boot）----
  JOB_SERVICE_URL: z.string().url().default('http://localhost:8080'),
  // 默认值来自 constants.ts 的超时矩阵，允许环境覆盖（容器里按需调）
  JOB_SERVICE_TIMEOUT_MS: z.coerce.number().int().positive().default(TIMEOUT_MS.jobService),

  // ---- 下游 2：analyzer（Python / FastAPI）----
  ANALYZER_URL: z.string().url().default('http://localhost:8000'),
  ANALYZER_TIMEOUT_MS: z.coerce.number().int().positive().default(TIMEOUT_MS.analyzer),
});

const parsed = envSchema.safeParse(process.env);

if (!parsed.success) {
  process.stderr.write(
    `${JSON.stringify({
      level: 'fatal',
      service: 'bff',
      message: '环境变量校验失败，请检查 .env（模板见 workspace/.env.example）',
      issues: parsed.error.issues.map((issue) => ({
        path: issue.path.join('.'),
        message: issue.message,
      })),
    })}\n`,
  );
  process.exit(1);
}

const env = parsed.data;

/** URL 统一去掉尾部斜杠，避免拼成 `//api/jobs` */
const trimSlash = (url: string): string => url.replace(/\/+$/, '');

export const config = {
  serviceName: 'bff',
  version: '0.1.0',
  envFile: ENV_FILE,
  port: env.BFF_PORT,
  logLevel: env.LOG_LEVEL,
  jobService: {
    baseUrl: trimSlash(env.JOB_SERVICE_URL),
    timeoutMs: env.JOB_SERVICE_TIMEOUT_MS,
  },
  analyzer: {
    baseUrl: trimSlash(env.ANALYZER_URL),
    timeoutMs: env.ANALYZER_TIMEOUT_MS,
  },
} as const;

export type Config = typeof config;
