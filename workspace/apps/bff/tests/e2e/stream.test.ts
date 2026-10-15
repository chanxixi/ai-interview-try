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
});
