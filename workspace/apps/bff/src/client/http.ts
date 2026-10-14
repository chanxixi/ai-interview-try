import { UpstreamStatusError, UpstreamTransportError } from '../errors/appError';

/**
 * 下游 HTTP 调用封装。
 *
 * - 使用 Node 内置的 undici（全局 fetch），不引第三方 HTTP 库（plan.md §2 选型）
 * - **禁止无超时的外部调用**（spec.md §3.3）→ 一律 `AbortSignal.timeout`
 * - 透传 `X-Trace-Id`，保证全链可 grep（spec.md §2.8）
 */
export interface RequestOptions {
  /** 下游服务名，仅用于日志与错误信息 */
  service: string;
  url: string;
  timeoutMs: number;
  traceId: string;
  method?: 'GET' | 'POST';
  body?: unknown;
}

export async function requestJson<T>(options: RequestOptions): Promise<T> {
  const { service, url, timeoutMs, traceId, method = 'GET', body } = options;

  let response: Response;
  try {
    response = await fetch(url, {
      method,
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
        'X-Trace-Id': traceId,
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(timeoutMs),
    });
  } catch (error) {
    throw new UpstreamTransportError(service, isTimeout(error) ? 'timeout' : 'network', error);
  }

  if (!response.ok) {
    throw new UpstreamStatusError(service, response.status);
  }

  try {
    return (await response.json()) as T;
  } catch (error) {
    throw new UpstreamTransportError(service, 'malformed', error);
  }
}

function isTimeout(error: unknown): boolean {
  return error instanceof Error && (error.name === 'TimeoutError' || error.name === 'AbortError');
}
