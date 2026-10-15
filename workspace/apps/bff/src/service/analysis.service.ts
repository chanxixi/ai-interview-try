import { AppError, UpstreamStatusError, UpstreamTransportError } from '../errors/appError';
import type { UploadPayload } from '../middleware/upload.middleware';
import { createFrameParser, formatEvent, SSE_HEADERS } from '../util/sse';

/**
 * 流式分析编排（tasks.md M6.4）。
 *
 * <h2>本层的职责边界（C3：严格线性 Vue → BFF → Java → Python → LLM）</h2>
 * <ul>
 *   <li><b>做</b>：前置校验、建响应头、发 meta、把 Java 的 SSE 帧<b>原样</b>透传给前端</li>
 *   <li><b>不做</b>：解析 PDF、判技能、算分、排序（全在 Python / Java 侧）</li>
 *   <li><b>禁止</b>：直连 Python —— BFF 只与 Java 对话（spec.md §2.7）</li>
 * </ul>
 *
 * <h2>为什么 BFF 要重新分帧而不是直接把字节转发</h2>
 * 直接 `pipe` 字节也能工作，但会丢掉三样东西：
 *   ① **断连检测** —— 只在帧边界上判断「客户端还在不在」，代价最小；
 *   ② **错误事件的可见性** —— Python 的 `error` 事件要能被 BFF 记录（而不是无脑透传后
 *      什么也不知道）；这里记日志但**不二次包装**（M6.5 的硬要求）；
 *   ③ **心跳** —— 上游 15s 无事件时补发 `: ping`，防止代理掐连接。
 *
 * <h2>断连与 EPIPE</h2>
 * 客户端断开后继续写会抛 `EPIPE` / `ERR_STREAM_WRITE_AFTER_END`。
 * 这类错误<b>绝不能抛到全局</b>：响应头已经写了，再抛会让 errorHandler 尝试
 * 写第二个响应，产生「二次错误」把日志污染（plan.md §6.3）。
 * 所以所有写操作都包在 try/catch 里，断连只记一条 `STREAM_ABORTED`（spec.md §2.5，仅日志）。
 */

export interface AnalysisStreamDeps {
  /** 转发到 Java 的流式端点；返回上游响应（含 body 流） */
  forward: (payload: UploadPayload, fields: Record<string, string>, traceId: string) => Promise<UpstreamStream>;
  logger: { info: (msg: string, meta?: unknown) => void; warn: (msg: string, meta?: unknown) => void };
}

export interface UpstreamStream {
  status: number;
  /** 上游字节流。分块边界与 SSE 帧边界无关，所以必须走 createFrameParser。 */
  body: AsyncIterable<string>;
}

export interface StreamSink {
  /** 写一段文本到客户端。客户端已断开时返回 false。 */
  write: (chunk: string) => boolean;
  end: () => void;
  /** 注册客户端断开回调 */
  onClose: (handler: () => void) => void;
}

/**
 * 执行一次流式分析：校验 → 建头 → meta → 透传 → 结束。
 *
 * @throws AppError —— 只在**建流之前**抛（校验失败 / 上游非 200）。
 *                     一旦开始写响应体，就不允许再抛（改由 error 事件表达）。
 */
export async function streamAnalysis(
  deps: AnalysisStreamDeps,
  payload: UploadPayload,
  traceId: string,
  sink: StreamSink,
): Promise<void> {
  const { forward, logger } = deps;

  // ---- 前置校验：全部在建流之前完成（spec.md §2.5 的分界线）----------------
  if (!payload.file && !String(payload.fields.resumeText ?? '').trim()) {
    throw AppError.invalidInput('file 与 resumeText 至少提供一个');
  }

  let aborted = false;
  sink.onClose(() => {
    aborted = true;
    // STREAM_ABORTED **仅日志**（spec.md §2.5 的 499），不进响应体 ——
    // 连接都没了，往里写什么都没意义。
    logger.info('stream aborted by client', { traceId, code: 'STREAM_ABORTED' });
  });

  // ---- 转发前先连上游：拿不到 200 就还能返回同步错误 ------------------------
  const upstream = await forward(payload, payload.fields, traceId);
  if (upstream.status !== 200) {
    throw new UpstreamStatusError('job-service', upstream.status);
  }

  // ---- 建头 + meta --------------------------------------------------------
  // meta 必须是**第一个**事件（spec.md §2.4）。它由 BFF 自己发，
  // 这样前端在 Java 还没吐出任何东西时就已经拿得到 traceId 与 source。
  if (!sink.write(formatEvent('meta', { traceId, source: payload.file ? 'pdf' : 'text' }))) {
    return;
  }

  const parser = createFrameParser((frame) => {
    if (aborted) {
      return;
    }
    if (frame.event === 'error') {
      // Python 的 error 事件**原样透传，不二次包装**（M6.5）。
      // 这里只记日志：BFF 需要知道「这一条流是失败结束的」，但不改动帧内容 ——
      // 一旦包装，前端的 error.code 就不再是契约里的那几个值了。
      logger.warn('upstream error event', { traceId, data: frame.data });
    }
    // 原样重发：event + data 两行 + 空行。与上游字节级一致。
    sink.write(frame.event === null ? `: ${frame.data}\n\n` : `event: ${frame.event}\ndata: ${frame.data}\n\n`);
  });

  try {
    for await (const chunk of upstream.body) {
      if (aborted) {
        break;
      }
      parser.write(chunk);
    }
    parser.end();
  } catch (error) {
    if (aborted || isStreamWriteError(error)) {
      // 客户端断开 / 写失败：不抛全局（plan.md §6.3）
      logger.info('stream stopped', { traceId, reason: 'client-gone' });
      return;
    }
    throw error instanceof Error ? error : new UpstreamTransportError('job-service', 'network', error);
  }

  sink.end();
}

/** 客户端已断开后继续写的典型错误 —— 都不该抛到全局。 */
export function isStreamWriteError(error: unknown): boolean {
  if (!(error instanceof Error)) {
    return false;
  }
  const code = (error as NodeJS.ErrnoException).code;
  return code === 'EPIPE' || code === 'ERR_STREAM_WRITE_AFTER_END' || code === 'ECONNRESET';
}

/** 导出给 controller 用：SSE 响应头。 */
export { SSE_HEADERS };
