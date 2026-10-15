import { TIMEOUT_MS } from '../config/constants';
import { UpstreamTransportError } from '../errors/appError';
import type { UploadPayload } from '../middleware/upload.middleware';
import type { AnalysisStreamDeps, UpstreamStream } from './analysis.service';

/**
 * 流式分析的**下游适配** —— BFF → Java（tasks.md M6.4）。
 *
 * <h2>为什么单独一个文件</h2>
 * 它是 `AnalysisStreamDeps.forward` 的实现，也就是「BFF 怎么跟 Java 说话」。
 * 与 service 分开后：service 只管编排，adapter 只管协议；测试可以只 stub 这一个函数，
 * 不需要起一个真 Java。
 *
 * <h2>C3 的物理保证</h2>
 * 本文件里**只有** `job-service` 的 base URL。全仓库搜 `8000` / `analyzer`
 * 在 BFF 侧应该 0 命中 —— 那是附录 C 的审核项，也是「BFF 不直连 Python」的证据。
 *
 * <h2>超时</h2>
 * 用 `AbortSignal.timeout(120s)`（plan.md §6.1：BFF→Java 是 120s，Java→Python 是 110s，
 * <b>外层必须大于内层</b>）。流式场景的超时是「整条流的预算」而不是「首字节」，
 * 因为 LLM 思考阶段可能几十秒不出字符。
 */
export function createAnalysisDeps(baseUrl: string = process.env.JOB_SERVICE_URL ?? 'http://localhost:8080') {
  return {
    async forward(
      payload: UploadPayload,
      fields: Record<string, string>,
      traceId: string,
    ): Promise<UpstreamStream> {
      const form = new FormData();
      if (payload.file) {
        // Blob 必须带 type：Java 侧按 MIME 做第二道校验
        const blob = new Blob([new Uint8Array(payload.file.buffer)], {
          type: payload.file.mimetype || 'application/pdf',
        });
        form.append('file', blob, payload.file.filename);
      }
      for (const [key, value] of Object.entries(fields)) {
        if (key === 'file') {
          continue;
        }
        form.append(key, value);
      }
      if (!payload.file && fields.resumeText) {
        form.append('resumeText', fields.resumeText);
      }

      let response: Response;
      try {
        response = await fetch(`${baseUrl}/api/analysis/stream`, {
          method: 'POST',
          headers: {
            Accept: 'text/event-stream',
            'X-Trace-Id': traceId,
          },
          body: form,
          signal: AbortSignal.timeout(TIMEOUT_MS.stream),
        });
      } catch (error) {
        throw new UpstreamTransportError(
          'job-service',
          error instanceof Error && (error.name === 'TimeoutError' || error.name === 'AbortError')
            ? 'timeout'
            : 'network',
          error,
        );
      }

      return {
        status: response.status,
        body: toTextStream(response),
      };
    },

    logger: {
      info: (msg: string, meta?: unknown) => console.log(JSON.stringify({ level: 'info', msg, ...(meta as object) })),
      warn: (msg: string, meta?: unknown) => console.warn(JSON.stringify({ level: 'warn', msg, ...(meta as object) })),
    },
  } satisfies AnalysisStreamDeps;
}

/**
 * 把 `Response.body`（Uint8Array 流）转成字符串流。
 *
 * **必须按 UTF-8 边界解码**：直接用 `TextDecoderStream` 而不是手工 `decode()` 每个 chunk ——
 * 中文是多字节的，chunk 边界可能落在字符中间，手工解会出现乱码（在 evidence 里尤其刺眼）。
 */
export async function* toTextStream(response: Response): AsyncIterable<string> {
  const body = response.body;
  if (!body) {
    return;
  }
  const reader = body.pipeThrough(new TextDecoderStream('utf-8')).getReader();
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) {
        return;
      }
      yield value;
    }
  } finally {
    reader.releaseLock();
  }
}
