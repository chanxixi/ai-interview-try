import type { Logger } from 'pino';

/**
 * 扩展 Koa 的 `ctx.state`，让横切数据在中间件与 controller 里都有类型（spec.md §2.8）。
 *
 * 三个字段的写入者（**唯一**，不要在别处重复写）：
 *   - `traceId` / `log` → middleware/traceId.middleware.ts
 *   - `dto`             → middleware/validate.middleware.ts
 *
 * 自检（指南 §A.1 第 1 条）：业务层（service/）**不应** import 本文件 ——
 * 一旦 import，说明它开始依赖 Koa 的上下文了。
 */
declare module 'koa' {
  interface DefaultState {
    /** 全链 traceId，由 traceId 中间件写入 */
    traceId: string;
    /** 已绑定 traceId 的子 logger */
    log: Logger;
    /** 已通过 zod 校验的请求体；由 validate 中间件写入，controller 里按具体 DTO 断言 */
    dto?: unknown;
  }
}
