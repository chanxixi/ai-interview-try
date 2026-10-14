import type { Context, Next } from 'koa';

/**
 * 访问日志（结构化 JSON，spec.md §2.8）。
 *
 * 只在请求正常走完时输出；异常路径由 errorHandler 统一记录，避免重复刷日志。
 */
export async function requestLogMiddleware(ctx: Context, next: Next): Promise<void> {
  const startedAt = process.hrtime.bigint();

  await next();

  const durationMs = Number(process.hrtime.bigint() - startedAt) / 1_000_000;
  ctx.state.log.info(
    {
      method: ctx.method,
      path: ctx.path,
      status: ctx.status,
      durationMs: Math.round(durationMs * 100) / 100,
    },
    'request completed',
  );
}
