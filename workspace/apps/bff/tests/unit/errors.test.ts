import { AppError, UpstreamStatusError, UpstreamTransportError } from '../../src/errors/appError';
import { ERROR_CODES } from '../../src/errors/errorCode';
import { mapUpstreamError } from '../../src/errors/mapUpstream';

/**
 * 错误映射表逐条验证（plan.md §6.4）。
 *
 * 这个文件是「改下游故障表现」时的**唯一回归网**：
 * 改了 `errors/mapUpstream.ts` 就必须先在这里改期望值，避免顺手把 404 改成 503。
 */
describe('unit · mapUpstreamError（下游表现 → 对外错误码）', () => {
  it('已经是 AppError 时原样返回，不被二次包装', () => {
    const original = AppError.resumeTooLong(20_000);
    expect(mapUpstreamError(original)).toBe(original);
  });

  it('传输层超时 → 504 UPSTREAM_TIMEOUT', () => {
    const mapped = mapUpstreamError(new UpstreamTransportError('analyzer', 'timeout'));
    expect(mapped).toMatchObject({ status: 504, code: 'UPSTREAM_TIMEOUT' });
  });

  it('连不上 / 响应不可解析 → 503 SERVICE_UNAVAILABLE', () => {
    for (const reason of ['network', 'malformed'] as const) {
      const mapped = mapUpstreamError(new UpstreamTransportError('job-service', reason));
      expect(mapped).toMatchObject({ status: 503, code: 'SERVICE_UNAVAILABLE' });
    }
  });

  it('job-service 404 → 404 JOB_NOT_FOUND', () => {
    const mapped = mapUpstreamError(new UpstreamStatusError('job-service', 404));
    expect(mapped).toMatchObject({ status: 404, code: 'JOB_NOT_FOUND' });
  });

  it('job-service 5xx → 503 SERVICE_UNAVAILABLE', () => {
    const mapped = mapUpstreamError(new UpstreamStatusError('job-service', 500));
    expect(mapped).toMatchObject({ status: 503, code: 'SERVICE_UNAVAILABLE' });
  });

  it('analyzer 4xx → 422 ANALYSIS_FAILED', () => {
    const mapped = mapUpstreamError(new UpstreamStatusError('analyzer', 422));
    expect(mapped).toMatchObject({ status: 422, code: 'ANALYSIS_FAILED' });
  });

  it('analyzer 5xx → 503 SERVICE_UNAVAILABLE', () => {
    const mapped = mapUpstreamError(new UpstreamStatusError('analyzer', 503));
    expect(mapped).toMatchObject({ status: 503, code: 'SERVICE_UNAVAILABLE' });
  });

  it('未知异常 → 500 INTERNAL_ERROR，且不含原始信息', () => {
    const mapped = mapUpstreamError(new Error('raw stack detail'));
    expect(mapped).toMatchObject({ status: 500, code: 'INTERNAL_ERROR' });
    expect(mapped.message).not.toContain('raw stack');
  });

  it('错误码表与 spec §2.3 + part2 §2.5 完全一致（冻结清单）', () => {
    // part2 新增三个：
    //   FILE_TOO_LARGE / UNSUPPORTED_FILE_TYPE —— 上传准入，建流前的同步错误（§2.5）
    //   STREAM_ABORTED                        —— 断连，**仅日志**（§2.5 明确不进响应体）
    expect([...ERROR_CODES].sort()).toEqual(
      [
        'INVALID_INPUT',
        'RESUME_TOO_LONG',
        'JOB_NOT_FOUND',
        'ANALYSIS_FAILED',
        'RATE_LIMITED',
        'SERVICE_UNAVAILABLE',
        'UPSTREAM_TIMEOUT',
        'INTERNAL_ERROR',
        'FILE_TOO_LARGE',
        'UNSUPPORTED_FILE_TYPE',
        'STREAM_ABORTED',
      ].sort(),
    );
  });
});
