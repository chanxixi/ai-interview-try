/**
 * 全链连通性探针响应（`GET /api/ping`）。
 *
 * job-service 与 analyzer 的探针形状一致，因此四层共用这一个 DTO：
 * 每一跳回显自己的 `service` / `runtime` / `traceId`，并把自己下游的结果挂在 `downstream`。
 *
 * 这个 DTO 原先内联在 `client/jobService.client.ts` 里 —— 属于「DTO 与适配器混住」，
 * P1 把它提到 DTO 层：client 只负责取数据，形状归 DTO 管。
 */
export interface PingResult {
  /** 该跳的服务名 */
  service: string;
  status: 'ok' | 'down';
  version?: string;
  /** 运行时标识，例如 `node v22.22.2` / `java 17.0.2` / `python 3.13.14` */
  runtime?: string;
  /** 该跳收到的 traceId，用于肉眼核对全链是否一致 */
  traceId?: string | null;
  error?: string;
  /** 下一跳的结果；最后一跳（analyzer）没有该字段 */
  downstream?: PingResult;
}
