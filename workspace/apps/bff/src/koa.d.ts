import type { Logger } from 'pino';

/**
 * 扩展 Koa 的 `ctx.state`，让 `ctx.state.traceId` / `ctx.state.log`
 * 在中间件与路由里都有类型（spec.md §2.8）。
 */
declare module 'koa' {
  interface DefaultState {
    /** 全链 traceId，由 traceId 中间件写入 */
    traceId: string;
    /** 已绑定 traceId 的子 logger */
    log: Logger;
  }
}
