/**
 * 流式分析端到端（tasks.md M6.6）—— 起真实 Koa app，只把**下游 HTTP** 换成 stub。
 *
 * 打桩点选在最外层（下游适配器）：Service / Controller / 中间件全跑真实实现，
 * 所以「SSE 头对不对」「meta 是不是第一个」「error 有没有被二次包装」这些契约级
 * 行为都是真测出来的，不是靠 mock 假装。
 *
 * 覆盖：
 *   - AC11 事件序列（meta 首 / done 尾 / stage 齐全）
 *   - AC12 改名成 .pdf 的 docx → 415（magic number 判据）
 *   - AC13 >10MB → 413 且不建流
 *   - M6.5 Python error 事件**原样透传**，不二次包装
 *   - AC21 Accept 不含 text/event-stream → 回退同步 JSON
 */

import request from 'supertest';

import { AnalysisController } from '../../src/controller/analysis.controller';
import { createApp } from '../../src/app';
import { API_PREFIX, TRACE_ID_HEADER } from '../../src/config/constants';
import type { UploadPayload } from '../../src/middleware/upload.middleware';
import type { AnalysisStreamDeps, UpstreamStream } from '../../src/service/analysis.service';
import { containerWithJobServiceClient } from '../support/container';

/** 造一段「Python 会发出来的」SSE 字节流，故意按奇怪的边界切块。 */
function upstreamFrames(): string[] {
  const all =
    'event: meta\ndata: {"traceId":"t","source":"pdf"}\n\n' +
    'event: stage\ndata: {"stage":"parsed","status":"ok"}\n\n' +
    'event: result\ndata: {"match":{"score":52},"recommendations":[]}\n\n' +
    'event: done\ndata: {"elapsedMs":81}\n\n';
  // 从中间切开，验证 BFF 的分帧器有行缓冲（chunk 边界 ≠ 帧边界）
  return [all.slice(0, 40), all.slice(40, 95), all.slice(95)];
}

function errorFrames(): string[] {
  return ['event: meta\ndata: {"traceId":"t","source":"pdf"}\n\n', 'event: error\ndata: {"code":"PDF_ENCRYPTED","message":"文件有密码","traceId":"t"}\n\n', 'event: done\ndata: {"elapsedMs":5}\n\n'];
}

/**
 * part3 `deep` 模式的帧：比 standard 多一个 `stage(reviewed)`，
 * `result` 里多四个块。**BFF 对它们不透明** —— 这一段就是用来验证「不解读、不裁剪」的。
 */
function deepFrames(): string[] {
  const result = {
    resume: { sections: {}, skills: [] },
    issues: [],
    match: { score: 52, matched: [], missing: [] },
    recommendations: [],
    meta: {
      traceId: 't', llmUsed: true, degraded: false, elapsedMs: 120,
      source: 'text', truncated: false, recommendationCount: 0,
      analysisDepth: 'deep', verdictCount: 2, directionCount: 1,
    },
    verdicts: [{ skill: 'Kafka', importance: 'required', verdict: 'missing', reason: '无证据' }],
    improvements: [{ area: '缺失能力', action: '补一条实践', evidence: '负责订单系统重构', targets: ['Kafka'] }],
    growthDirections: [{ direction: '消息队列', why: '零证据', firstStep: '用一次', priority: 1 }],
    abilityProfile: { dimensions: [{ name: '技术深度', score: 65, rubricRef: 'tech_depth.L2', evidence: 'x' }], overall: 65 },
  };
  const all =
    'event: meta\ndata: {"traceId":"t","source":"text"}\n\n' +
    'event: stage\ndata: {"stage":"llm","status":"ok"}\n\n' +
    'event: stage\ndata: {"stage":"reviewed","status":"ok"}\n\n' +
    `event: result\ndata: ${JSON.stringify(result)}\n\n` +
    'event: done\ndata: {"elapsedMs":120}\n\n';
  return [all.slice(0, 60), all.slice(60, 200), all.slice(200)];
}

function makeContainer(frames: string[], status = 200) {
  const forwarded: Array<Record<string, string>> = [];

  // 只替换「BFF → Java」这一跳：Service / Controller / 中间件全跑真实实现
  const analysisDeps: AnalysisStreamDeps = {
    async forward(payload: UploadPayload, fields: Record<string, string>): Promise<UpstreamStream> {
      forwarded.push({ hasFile: String(payload.file !== null), ...fields });
      return {
        status,
        body: (async function* () {
          for (const chunk of frames) yield chunk;
        })(),
      };
    },
    logger: { info: () => undefined, warn: () => undefined },
  };

  const base = containerWithJobServiceClient({
    ping: async () => ({
      service: 'job-service',
      status: 'ok',
      version: '0.1.0',
      runtime: 'java 17',
      traceId: 't',
    }),
  } as never);

  return {
    ...base,
    controllers: { ...base.controllers, analysis: new AnalysisController(analysisDeps) },
    forwarded,
  };
}

describe('POST /api/analysis/stream', () => {
  it('AC11：事件序列 meta 首 / done 尾，且中间是完整的 stage 流', async () => {
    const container = makeContainer(upstreamFrames());
    const app = createApp(container as never);

    const res = await request(app.callback())
      .post(`${API_PREFIX}/analysis/stream`)
      .set('Accept', 'text/event-stream')
      .attach('file', Buffer.from('%PDF-1.4 fake'), { filename: 'resume.pdf', contentType: 'application/pdf' })
      .buffer(true)
      .parse((res, callback) => {
        let text = '';
        res.on('data', (chunk: Buffer) => (text += chunk.toString('utf8')));
        res.on('end', () => callback(null, text));
      });

    expect(res.status).toBe(200);
    // SSE 三件套
    expect(res.headers['content-type']).toContain('text/event-stream');
    expect(res.headers['cache-control']).toBe('no-cache');
    expect(res.headers['x-accel-buffering']).toBe('no');

    const events = String(res.body).match(/^event: .+$/gm) ?? [];
    expect(events[0]).toBe('event: meta');
    expect(events[events.length - 1]).toBe('event: done');
    expect(events).toContain('event: result');
  });

  it('AC12：改名成 .pdf 的 docx → 415（magic number，不是扩展名）', async () => {
    const container = makeContainer(upstreamFrames());
    const app = createApp(container as never);

    const res = await request(app.callback())
      .post(`${API_PREFIX}/analysis/stream`)
      .set('Accept', 'text/event-stream')
      // docx / zip 的文件头是 PK\x03\x04
      .attach('file', Buffer.from([0x50, 0x4b, 0x03, 0x04, 0x00, 0x01]), {
        filename: 'resume.pdf',
        contentType: 'application/pdf',
      });

    expect(res.status).toBe(415);
    expect(res.body.code).toBe('UNSUPPORTED_FILE_TYPE');
    // 校验在建流之前完成 —— 上游一个字节都没收到
    expect(container.forwarded).toHaveLength(0);
  });

  it('AC13：>10MB → 413，且不建立 SSE 流', async () => {
    const container = makeContainer(upstreamFrames());
    const app = createApp(container as never);

    const big = Buffer.concat([Buffer.from('%PDF-1.4'), Buffer.alloc(10 * 1024 * 1024, 0x20)]);
    const res = await request(app.callback())
      .post(`${API_PREFIX}/analysis/stream`)
      .set('Accept', 'text/event-stream')
      .attach('file', big, { filename: 'big.pdf', contentType: 'application/pdf' });

    expect(res.status).toBe(413);
    expect(res.body.code).toBe('FILE_TOO_LARGE');
    expect(container.forwarded).toHaveLength(0);
  });

  it('file 与 resumeText 都没有 → 400 INVALID_INPUT', async () => {
    const container = makeContainer(upstreamFrames());
    const app = createApp(container as never);

    const res = await request(app.callback())
      .post(`${API_PREFIX}/analysis/stream`)
      .set('Accept', 'text/event-stream')
      .field('jobId', 'job-a');

    expect(res.status).toBe(400);
    expect(res.body.code).toBe('INVALID_INPUT');
  });

  it('AC21：Accept 不含 text/event-stream → 回退同步 JSON（只取 result）', async () => {
    const container = makeContainer(upstreamFrames());
    const app = createApp(container as never);

    const res = await request(app.callback())
      .post(`${API_PREFIX}/analysis/stream`)
      .set('Accept', 'application/json')
      .field('resumeText', '张三 熟悉 Java');

    expect(res.status).toBe(200);
    expect(res.headers['content-type']).toContain('application/json');
    expect(res.body).toMatchObject({ match: { score: 52 }, recommendations: [] });
  });

  it('M6.5：Python 的 error 事件原样透传，不二次包装', async () => {
    const container = makeContainer(errorFrames());
    const app = createApp(container as never);

    const res = await request(app.callback())
      .post(`${API_PREFIX}/analysis/stream`)
      .set('Accept', 'text/event-stream')
      .field('resumeText', '张三')
      .buffer(true)
      .parse((res, callback) => {
        let text = '';
        res.on('data', (chunk: Buffer) => (text += chunk.toString('utf8')));
        res.on('end', () => callback(null, text));
      });

    const body = String(res.body);
    expect(body).toContain('event: error');
    // code 与 message 必须是上游原样，不能被 BFF 改写成 ANALYSIS_FAILED
    expect(body).toContain('"code":"PDF_ENCRYPTED"');
    expect(body).toContain('文件有密码');
    expect(body).not.toContain('ANALYSIS_FAILED');
  });

  it('traceId 贯通：响应头带回同一个 traceId', async () => {
    const container = makeContainer(upstreamFrames());
    const app = createApp(container as never);

    const res = await request(app.callback())
      .post(`${API_PREFIX}/analysis/stream`)
      .set('Accept', 'text/event-stream')
      .set(TRACE_ID_HEADER, 'trace-e2e-001')
      .field('resumeText', '张三');

    expect(res.headers[TRACE_ID_HEADER.toLowerCase()]).toBe('trace-e2e-001');
  });

  // ------------------------------------------------------------------ part3（N4）

  it('part3 deep：analysisDepth / topN 透传给 Java，且四个新块原样透传回前端', async () => {
    const container = makeContainer(deepFrames());
    const app = createApp(container as never);

    const res = await request(app.callback())
      .post(`${API_PREFIX}/analysis/stream`)
      .set('Accept', 'text/event-stream')
      .field('resumeText', '张三 熟悉 Java')
      .field('jobId', 'job-a')
      .field('analysisDepth', 'deep')
      .field('topN', '5')
      .buffer(true)
      .parse((res, callback) => {
        let text = '';
        res.on('data', (chunk: Buffer) => (text += chunk.toString('utf8')));
        res.on('end', () => callback(null, text));
      });

    expect(res.status).toBe(200);

    // ① 两个新参数必须真的转发给 Java —— BFF 不做业务，但**不能把参数吃掉**
    expect(container.forwarded[0]).toMatchObject({ analysisDepth: 'deep', topN: '5' });

    // ② `reviewed` 阶段与四个新块对 BFF 是**不透明**的：原样透传，不解读、不裁剪
    const body = String(res.body);
    expect(body).toContain('"stage":"reviewed"');
    for (const key of ['verdicts', 'improvements', 'growthDirections', 'abilityProfile']) {
      expect(body).toContain(`"${key}"`);
    }
  });

  it('part3：缺省（不传两个新参数）→ 转发里也不出现它们，由 analyzer 落回默认', async () => {
    const container = makeContainer(upstreamFrames());
    const app = createApp(container as never);

    await request(app.callback())
      .post(`${API_PREFIX}/analysis/stream`)
      .set('Accept', 'text/event-stream')
      .field('resumeText', '张三');

    // 默认值只由 analyzer 一处决定；BFF 再写一遍就是两处默认值，迟早漂移
    expect(container.forwarded[0]).not.toHaveProperty('analysisDepth');
    expect(container.forwarded[0]).not.toHaveProperty('topN');
  });

  it('part3：非法 analysisDepth / 越界 topN → 400，且不建立流', async () => {
    const cases: Array<[string, string]> = [
      ['analysisDepth', 'ultra'],
      ['topN', '0'],
      ['topN', '11'],
      ['topN', '3abc'],
    ];

    for (const [field, value] of cases) {
      const container = makeContainer(upstreamFrames());
      const app = createApp(container as never);

      const res = await request(app.callback())
        .post(`${API_PREFIX}/analysis/stream`)
        .set('Accept', 'text/event-stream')
        .field('resumeText', '张三')
        .field(field, value);

      expect(res.status).toBe(400);
      expect(res.body.code).toBe('INVALID_INPUT');
      // 建流前就拒了 —— 上游一个字节都没收到
      expect(container.forwarded).toHaveLength(0);
    }
  });
});
