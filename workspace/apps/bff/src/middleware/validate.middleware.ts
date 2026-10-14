import type { Context, Next } from 'koa';
import type { ZodTypeAny } from 'zod';

import { AppError } from '../errors/appError';

/**
 * 请求体校验中间件（spec.md §2.6：输入校验是 BFF 职责）。
 *
 * 校验通过才进 controller，并把结果写进 `ctx.state.dto`；
 * 失败直接抛 `400 INVALID_INPUT`，由 errorHandler 收口。
 *
 * ⚠️ 依赖 `koa-bodyparser`（app.ts 已挂载）解析出的 `ctx.request.body`。
 *
 * 接线点：`route/index.ts` —— T3 的 `POST /api/analysis` 会这样用：
 *   `router.post(\`${API_PREFIX}/analysis\`, validateBody(analyzeRequestSchema), deps.analysis.analyze)`
 *
 * 注意分层：这里只做**形状校验**，业务不变量（如简历 20000 上限）由 Service 守（spec.md §2.3）。
 */
export function validateBody(schema: ZodTypeAny) {
  return async (ctx: Context, next: Next): Promise<void> => {
    const parsed = schema.safeParse(ctx.request.body);
    if (!parsed.success) {
      const detail = parsed.error.issues
        .map((issue) => `${issue.path.join('.') || 'body'}: ${issue.message}`)
        .join('; ');
      throw AppError.invalidInput(detail);
    }

    ctx.state.dto = parsed.data;
    await next();
  };
}
