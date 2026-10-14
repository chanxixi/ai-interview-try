import type { PingResult } from '../api/types';

/** 拍平后的一跳，供逐跳渲染。 */
export interface ChainHop {
  index: number;
  service: string;
  status: 'ok' | 'down';
  runtime?: string;
  version?: string;
  traceId?: string | null;
  error?: string;
}

/** 递归的 `downstream` → 线性跳数列表（每一跳自带状态，断在哪跳一目了然）。 */
export function flattenChain(root: PingResult | undefined): ChainHop[] {
  const hops: ChainHop[] = [];
  let node: PingResult | undefined = root;

  while (node !== undefined) {
    hops.push({
      index: hops.length + 1,
      service: node.service,
      status: node.status,
      runtime: node.runtime,
      version: node.version,
      traceId: node.traceId,
      error: node.error,
    });
    node = node.downstream;
  }

  return hops;
}

/**
 * 拼出前端视角的完整链路。
 *
 * BFF 的响应从 BFF 自己开始，所以这里补上第 1 跳 `web`（traceId 由前端生成并主动带上）。
 */
export function buildChain(payload: PingResult, clientTraceId: string): ChainHop[] {
  const frontend: ChainHop = {
    index: 1,
    service: 'web',
    status: 'ok',
    runtime: 'browser',
    traceId: clientTraceId,
  };

  return [frontend, ...flattenChain(payload)].map((hop, index) => ({ ...hop, index: index + 1 }));
}
