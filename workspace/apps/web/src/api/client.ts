import type { ApiErrorBody, PingResult } from './types';

/**
 * 前端只与 BFF 通信（spec.md §3.1 禁止跳层）。
 *
 * 开发环境走 Vite 代理 `/api` → BFF，因此 BASE_URL 默认为空；
 * 需要直连（例如部署后）时用 `VITE_BFF_BASE_URL` 覆盖。
 */
const BASE_URL = import.meta.env.VITE_BFF_BASE_URL ?? '';

/** BFF 返回的统一错误体（spec.md §2.3）—— 直接拿来展示，不做二次解读。 */
export class ApiRequestError extends Error {
  readonly status: number;
  readonly code: string;
  readonly traceId?: string;

  constructor(status: number, body: ApiErrorBody) {
    super(body.message);
    this.name = 'ApiRequestError';
    this.status = status;
    this.code = body.code;
    this.traceId = body.traceId;
  }
}

export interface PingChainResult {
  data: PingResult;
  /** 响应头回写的 traceId，应与请求头一致（spec.md §2.8） */
  traceId: string;
}

/**
 * 全链连通性探针。
 *
 * traceId 由**前端生成**并主动带上：如果它能在响应里原样回来，
 * 就证明 Vue → BFF → job-service → analyzer 全链透传成功。
 */
export async function fetchPingChain(clientTraceId: string): Promise<PingChainResult> {
  const response = await fetch(`${BASE_URL}/api/ping`, {
    headers: { 'X-Trace-Id': clientTraceId },
  });

  const text = await response.text();
  const payload: unknown = text === '' ? null : safeParse(text);

  if (!response.ok) {
    const body = (payload ?? {}) as Partial<ApiErrorBody>;
    throw new ApiRequestError(response.status, {
      code: body.code ?? 'INTERNAL_ERROR',
      message: body.message ?? `请求失败（HTTP ${response.status}）`,
      traceId: body.traceId,
    });
  }

  return {
    data: payload as PingResult,
    traceId: response.headers.get('X-Trace-Id') ?? clientTraceId,
  };
}

function safeParse(text: string): unknown {
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return null;
  }
}
