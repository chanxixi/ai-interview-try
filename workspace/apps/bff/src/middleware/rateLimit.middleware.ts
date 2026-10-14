import type { Context, Next } from 'koa';

import { AppError } from '../errors/appError';

/**
 * ★ **预留骨架** —— 本期不启用（spec.md §1.4 Out of Scope）。
 *
 * `429 RATE_LIMITED` 作为错误码已存在于 spec.md §2.3，但限流不在本期范围内；
 * 这里保留可用的实现，避免将来重新设计。
 *
 * 启用条件：BFF 需要公开部署、入口会被刷时。
 * 启用方式：在 `app.ts` 里 `app.use(createRateLimitMiddleware({ capacity: 60, refillPerSec: 1 }))`，
 *          挂在 traceId 之后、路由之前。
 *
 * ⚠️ 生产实现请换成 **Redis 令牌桶** —— 进程内 Map 只在单实例下有效，
 *    多副本部署时每个实例各算一份，限流形同虚设。
 */
export function createRateLimitMiddleware(opts: { capacity: number; refillPerSec: number }) {
  const buckets = new Map<string, { tokens: number; updatedAt: number }>();

  return async (ctx: Context, next: Next): Promise<void> => {
    const key = ctx.ip;
    const now = Date.now();

    const bucket = buckets.get(key) ?? { tokens: opts.capacity, updatedAt: now };
    bucket.tokens = Math.min(
      opts.capacity,
      bucket.tokens + ((now - bucket.updatedAt) / 1000) * opts.refillPerSec,
    );
    bucket.updatedAt = now;

    if (bucket.tokens < 1) {
      buckets.set(key, bucket);
      ctx.set('Retry-After', '1');
      throw AppError.rateLimited();
    }

    bucket.tokens -= 1;
    buckets.set(key, bucket);
    await next();
  };
}
