/**
 * `GET /healthz` 响应 —— spec.md §2.8（冻结）。
 *
 * ⚠️ BFF 自身无存储，因此**没有** `storage` 字段。
 *    `storage`（mysql / local / mock）只由 job-service 暴露（spec.md §2.9），
 *    两条降级链不要混：LLM 看 `meta.degraded`，存储看 Java `/healthz.storage`。
 */
export interface HealthResponse {
  status: 'ok';
  service: string;
}
