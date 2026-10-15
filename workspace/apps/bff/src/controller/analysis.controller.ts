import type { Context } from 'koa';

import { AppError } from '../errors/appError';
import type { UploadPayload } from '../middleware/upload.middleware';
import { streamAnalysis, type AnalysisStreamDeps } from '../service/analysis.service';
import { SSE_HEADERS } from '../util/sse';

/**
 * 流式分析 controller（tasks.md M6.4）。
 *
 * **本文件只做三件事**：取已校验的上传载荷 → 决定走流式还是回退同步 → 把 Koa 的
 * 响应对象适配成 service 需要的 sink。任何业务判断都不在这里。
 *
 * <h2>AC21：Accept 不含 text/event-stream → 回退同步 JSON</h2>
 * 判定放在<b>建流之前</b>，依据是请求头。这样「不支持 SSE 的客户端」（curl 默认、
 * 某些网关）拿到的是一次性 JSON，而不是一条它不会解析的流。
 */
export class AnalysisController {
  constructor(private readonly deps: AnalysisStreamDeps) {}

  stream = async (ctx: Context): Promise<void> => {
    const payload = ctx.state.upload as UploadPayload | undefined;
    if (!payload) {
      // 没过 uploadGuard 就进来了 —— 路由接错了，属于配置错误
      throw AppError.internal();
    }

    const traceId = ctx.state.traceId as string | undefined;

    // ---- AC21：不支持流的客户端走同步回退 ----------------------------------
    if (!wantsEventStream(ctx)) {
      await this.fallbackToJson(ctx, payload, traceId);
      return;
    }

    // ---- 建流 --------------------------------------------------------------
    ctx.status = 200;
    ctx.set(SSE_HEADERS);
    // 关掉 Koa 的 buffer：否则响应会被攒到结束才发出去，流式就没了
    ctx.res.flushHeaders?.();

    const sink = {
      write: (chunk: string): boolean => {
        // 已断开就别写了 —— 写会抛 EPIPE，而那时响应头已经发出去了，
        // 抛出去只会产生一条没意义的全局错误（plan.md §6.3）。
        if (ctx.res.writableEnded || ctx.res.destroyed) {
          return false;
        }
        try {
          return ctx.res.write(chunk, 'utf8');
        } catch {
          return false;
        }
      },
      end: (): void => {
        if (!ctx.res.writableEnded) {
          ctx.res.end();
        }
      },
      onClose: (handler: () => void): void => {
        ctx.res.on('close', handler);
      },
    };

    await streamAnalysis(this.deps, payload, traceId ?? '', sink);
  };

  /**
   * 同步回退（AC21）：把整条流收完，只把 `result` 事件的 data 作为 JSON 返回。
   *
   * 为什么不直接调同步接口 `POST /api/analysis`：part2 的同步接口仍是 part1 的骨架
   * （返回 stub），而流式链路才是真实实现。收完流再取 result，
   * 保证两条入口的**结果一致** —— 这正是「同一份算法两个出口」该有的样子。
   */
  private async fallbackToJson(
    ctx: Context,
    payload: UploadPayload,
    traceId: string | undefined,
  ): Promise<void> {
    let result: unknown = null;
    let upstreamError: unknown = null;

    await streamAnalysis(
      this.deps,
      payload,
      // traceId 由 traceId 中间件保证非空；这里再兜一层，是因为 fallback 路径
      // 可能在中间件链之外被直接调用（测试）。
      traceId ?? '',
      {
        write: (chunk: string) => {
          // 只挑 result 帧，其余（stage / thinking / error）丢弃
          const match = /^event: result\ndata: (.+)\n\n$/s.exec(chunk);
          const data = match?.[1];
          if (data) {
            try {
              result = JSON.parse(data);
            } catch {
              // 解析失败就让它保持 null，下面统一报 ANALYSIS_FAILED
            }
          }
          if (chunk.startsWith('event: error')) {
            const data = /data: (.+)\n\n$/s.exec(chunk);
            upstreamError = data ? data[1] : 'unknown';
          }
          return true;
        },
        end: () => undefined,
        onClose: () => undefined,
      },
    );

    if (upstreamError) {
      this.deps.logger.warn('sync fallback saw upstream error', { traceId, upstreamError });
      throw AppError.analysisFailed();
    }
    if (!result) {
      throw AppError.analysisFailed();
    }

    ctx.status = 200;
    ctx.type = 'application/json';
    ctx.body = result;
  }
}

/** AC21 的判定：`Accept` 里含 `text/event-stream` 才走流式。 */
export function wantsEventStream(ctx: Context): boolean {
  const accept = ctx.get('accept') || '';
  return accept.includes('text/event-stream');
}
