/**
 * 常量集中地 —— 避免魔法值散落在 controller / middleware 里。
 *
 * 溯源：
 *   - `TRACE_ID_HEADER` 是 spec.md §2.8 冻结的 header 名，前端 / Java / Python 三处必须一致
 *   - `TIMEOUT_MS` 对齐 plan.md §6.1 超时矩阵；改这里必须同步改 plan.md，否则契约与实现脱节
 *   - `BODY_LIMIT` 是防御性上限；业务侧另有 `resumeText ≤ 20000` 字符限制（spec.md §2.1）
 */

/** 全链追踪头，spec.md §2.8（冻结） */
export const TRACE_ID_HEADER = 'X-Trace-Id';

/** BFF 对外路由前缀。spec.md §2.1 冻结为 `/api`，**不加版本号**（见指南 §6.6） */
export const API_PREFIX = '/api';

/** 请求体上限，防止超大 body 打爆内存 */
export const BODY_LIMIT = '512kb';

/** 下游超时矩阵 —— plan.md §6.1（冻结） */
export const TIMEOUT_MS = {
  /** 岗位查询是本地库读取，短超时即可 */
  jobService: 5_000,
  /** 分析要过 LLM，给足时间；超时后由 analyzer 内部降级（ADR-004） */
  analyzer: 45_000,
  /**
   * part2：BFF → Java 的**整条流**预算（120s）。
   *
   * 必须大于 Java → Python 的 110s（外层 > 内层，plan.md §6.1）——
   * 否则 Java 还没放弃、BFF 就先断了，用户看到的是 504 而不是「分析慢」。
   *
   * 注意它是**整条流**而不是首字节：LLM 思考阶段可能几十秒不出字符，
   * 按首字节超时会把正常的慢思考误判成故障。
   */
  stream: 120_000,
} as const;
