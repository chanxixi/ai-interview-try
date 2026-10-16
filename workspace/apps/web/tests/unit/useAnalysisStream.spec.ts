import { beforeEach, describe, expect, it, vi } from 'vitest';

import { STAGE_ORDER, STANDARD_STAGE_ORDER, type AnalyzeResult } from '../../src/api/analysis';
import { useAnalysisStream } from '../../src/pages/analyzer/composables/useAnalysisStream';

/**
 * `useAnalysisStream` 单测（tasks.md M7.3 / M8.4 的 web 增量）。
 *
 * 用**假的 `fetch` + 真 `ReadableStream`**，而不是 mock 掉解析逻辑 ——
 * 要验的正是「分包流能不能被正确还原」。所以这里必须真的把字节切碎喂进去。
 */

/** 造一个 body 是字符串流的 Response，chunks 按给定切分顺序入队。 */
function streamResponse(chunks: string[], init: { ok?: boolean; status?: number; errorBody?: unknown } = {}): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(encoder.encode(chunk));
      }
      controller.close();
    },
  });

  return {
    ok: init.ok ?? true,
    status: init.status ?? 200,
    body,
    json: async () => init.errorBody ?? {},
  } as unknown as Response;
}

function frame(event: string, data: unknown): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

/** 一条「完整成功」的事件序列，与 analyzer 真实输出同形。 */
function happyPathFrames(): string[] {
  const frames: string[] = [frame('meta', { traceId: 't-1', source: 'pdf' })];
  for (const stage of STAGE_ORDER) {
    frames.push(frame('stage', { stage, status: 'start', elapsedMs: 0, detail: {} }));
    frames.push(frame('stage', { stage, status: 'ok', elapsedMs: 5, detail: { pages: 2 } }));
  }
  frames.push(frame('thinking', { delta: '这份简历' }));
  frames.push(frame('thinking', { delta: '缺少量化。' }));
  frames.push(frame('result', RESULT));
  frames.push(frame('done', { elapsedMs: 1234 }));
  return frames;
}

const RESULT: AnalyzeResult = {
  resume: {
    sections: { education: ['某大学'], experience: ['某公司'], projects: [], skills: ['Java'] },
    skills: [{ raw: 'Java', canonical: 'Java', category: 'language' }],
  },
  issues: [
    { type: 'NO_QUANTIFY', severity: 'high', evidence: '优化了接口', suggestion: '补充耗时下降比例' },
  ],
  match: null,
  recommendations: [
    {
      jobId: 'job-java-01',
      title: 'Java 后端开发',
      company: '某科技',
      level: '校招',
      score: 82,
      matched: [{ skill: 'Java', importance: 'required' }],
      missing: [{ skill: 'Redis', importance: 'required', suggestion: '补一个缓存实战项目' }],
      reason: '命中 1/2 项要求，缺口为 Redis',
    },
  ],
  meta: {
    traceId: 't-1',
    llmUsed: true,
    degraded: false,
    elapsedMs: 1234,
    source: 'pdf',
    truncated: false,
    recommendationCount: 1,
  },
};

describe('useAnalysisStream', () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  it('完整事件序列：stages 全部 ok / thinking 累加 / result 落库 / done 收尾', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => streamResponse(happyPathFrames())));

    const stream = useAnalysisStream();
    const file = new File(['%PDF-1.4'], 'resume.pdf', { type: 'application/pdf' });
    await stream.start({ file });

    expect(stream.isStreaming.value).toBe(false);
    expect(stream.meta.value).toEqual({ traceId: 't-1', source: 'pdf' });
    expect(stream.stages.value.map((s) => s.stage)).toEqual([...STANDARD_STAGE_ORDER]);
    expect(stream.stages.value.every((s) => s.status === 'ok')).toBe(true);
    expect(stream.thinking.value).toBe('这份简历缺少量化。');
    expect(stream.result.value?.recommendations[0].jobId).toBe('job-java-01');
    expect(stream.receivedDone.value).toBe(true);
    expect(stream.elapsedMs.value).toBe(1234);
    expect(stream.error.value).toBeNull();
  });

  it('★ 跨 chunk 截断：把每一帧都从中间劈开，仍能还原全部事件', async () => {
    const whole = happyPathFrames().join('');
    const chunks: string[] = [];
    // 每 7 个字符切一刀 —— 保证会切在 JSON 与中文（多字节）中间
    for (let i = 0; i < whole.length; i += 7) {
      chunks.push(whole.slice(i, i + 7));
    }
    vi.stubGlobal('fetch', vi.fn(async () => streamResponse(chunks)));

    const stream = useAnalysisStream();
    await stream.start({ resumeText: '张三的简历' });

    expect(stream.stages.value.every((s) => s.status === 'ok')).toBe(true);
    expect(stream.thinking.value).toBe('这份简历缺少量化。');
    expect(stream.result.value?.meta.traceId).toBe('t-1');
    expect(stream.receivedDone.value).toBe(true);
  });

  it('match 为 null 时不报错（part2 的关键差异：不选岗位就只出推荐）', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => streamResponse(happyPathFrames())));

    const stream = useAnalysisStream();
    await stream.start({ resumeText: '简历' });

    expect(stream.result.value?.match).toBeNull();
    expect(stream.error.value).toBeNull();
  });

  it('同步 415（改名 docx）：走 HTTP 错误体，不进 SSE', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        streamResponse([], {
          ok: false,
          status: 415,
          errorBody: { code: 'UNSUPPORTED_FILE_TYPE', message: '文件内容不是 PDF', traceId: 't-9' },
        }),
      ),
    );

    const stream = useAnalysisStream();
    await stream.start({ resumeText: '简历' });

    expect(stream.error.value).toEqual({
      code: 'UNSUPPORTED_FILE_TYPE',
      message: '文件内容不是 PDF',
      traceId: 't-9',
    });
    expect(stream.result.value).toBeNull();
    expect(stream.isStreaming.value).toBe(false);
  });

  it('流内 error 事件：error 落库、result 保持 null、后面仍收 done', async () => {
    const frames = [
      frame('meta', { traceId: 't-2', source: 'pdf' }),
      frame('stage', { stage: 'accepted', status: 'start', elapsedMs: 0, detail: {} }),
      frame('stage', { stage: 'accepted', status: 'ok', elapsedMs: 1, detail: {} }),
      frame('stage', { stage: 'parsed', status: 'fail', elapsedMs: 3, detail: {} }),
      frame('error', { code: 'PDF_NO_TEXT_LAYER', message: '未检测到文本层', traceId: 't-2' }),
      frame('done', { elapsedMs: 4 }),
    ];
    vi.stubGlobal('fetch', vi.fn(async () => streamResponse(frames)));

    const stream = useAnalysisStream();
    await stream.start({ file: new File(['%PDF-'], 'scan.pdf') });

    expect(stream.error.value?.code).toBe('PDF_NO_TEXT_LAYER');
    expect(stream.result.value).toBeNull();
    expect(stream.receivedDone.value).toBe(true);
    expect(stream.isStreaming.value).toBe(false);
  });

  it('单帧 JSON 坏掉不影响后续帧（容错）', async () => {
    const frames = [
      frame('meta', { traceId: 't-3', source: 'pdf' }),
      'event: stage\ndata: {坏掉的 JSON\n\n',
      frame('done', { elapsedMs: 8 }),
    ];
    vi.stubGlobal('fetch', vi.fn(async () => streamResponse(frames)));

    const stream = useAnalysisStream();
    await stream.start({ resumeText: '简历' });

    expect(stream.meta.value?.traceId).toBe('t-3');
    expect(stream.receivedDone.value).toBe(true);
  });

  it('网络不通：给出 NETWORK_ERROR 而不是抛异常', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('Failed to fetch');
      }),
    );

    const stream = useAnalysisStream();
    await stream.start({ resumeText: '简历' });

    expect(stream.error.value?.code).toBe('NETWORK_ERROR');
    expect(stream.isStreaming.value).toBe(false);
  });

  it('abort() 中止后 isStreaming 归位', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => streamResponse(happyPathFrames())));

    const stream = useAnalysisStream();
    const pending = stream.start({ resumeText: '简历' });
    stream.abort();
    await pending;

    expect(stream.isStreaming.value).toBe(false);
  });

  it('提交的是 multipart：file 存在时不重复带 resumeText', async () => {
    const fetchMock = vi.fn(async () => streamResponse(happyPathFrames()));
    vi.stubGlobal('fetch', fetchMock);

    const stream = useAnalysisStream();
    await stream.start({ file: new File(['%PDF-'], 'a.pdf'), resumeText: '不该出现' });

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    const form = init.body as FormData;
    expect(form.get('file')).toBeInstanceOf(File);
    expect(form.get('resumeText')).toBeNull();
    expect((init.headers as Record<string, string>).Accept).toBe('text/event-stream');
  });

  // ------------------------------------------------------------------ part3（N4）

  it('part3：缺省不发送 analysisDepth / topN —— 默认值只由后端定义一处', async () => {
    const fetchMock = vi.fn(async () => streamResponse(happyPathFrames()));
    vi.stubGlobal('fetch', fetchMock);

    const stream = useAnalysisStream();
    await stream.start({ resumeText: '简历' });

    const form = (fetchMock.mock.calls[0][1] as RequestInit).body as FormData;
    expect(form.get('analysisDepth')).toBeNull();
    expect(form.get('topN')).toBeNull();
    // 进度条按 standard 建：7 格，没有 reviewed
    expect(stream.stages.value.map((s) => s.stage)).toEqual([...STANDARD_STAGE_ORDER]);
    expect(stream.analysisDepth.value).toBe('standard');
  });

  it('part3 deep：带上 analysisDepth 与 topN，且进度条是 8 格（含 reviewed）', async () => {
    const fetchMock = vi.fn(async () => streamResponse(happyPathFrames()));
    vi.stubGlobal('fetch', fetchMock);

    const stream = useAnalysisStream();
    await stream.start({ resumeText: '简历', analysisDepth: 'deep', topN: 5 });

    const form = (fetchMock.mock.calls[0][1] as RequestInit).body as FormData;
    expect(form.get('analysisDepth')).toBe('deep');
    expect(form.get('topN')).toBe('5');

    // ★ 进度条必须在**请求发出的那一刻**就是 8 格，而不是等后端发 reviewed 才补一格
    expect(stream.stages.value.map((s) => s.stage)).toEqual([...STAGE_ORDER]);
    expect(stream.analysisDepth.value).toBe('deep');
  });

  it('part3：显式选 standard 时也不发送该字段（避免两处默认值漂移）', async () => {
    const fetchMock = vi.fn(async () => streamResponse(happyPathFrames()));
    vi.stubGlobal('fetch', fetchMock);

    const stream = useAnalysisStream();
    await stream.start({ resumeText: '简历', analysisDepth: 'standard' });

    const form = (fetchMock.mock.calls[0][1] as RequestInit).body as FormData;
    expect(form.get('analysisDepth')).toBeNull();
  });

  it('part3 deep：result 里的四个新块被原样落库', async () => {
    const deepResult = {
      ...RESULT,
      verdicts: [
        { skill: 'Kafka', importance: 'required', verdict: 'missing', reason: '无证据' },
      ],
      improvements: [
        { area: '缺失能力', action: '补实践', evidence: '负责订单系统重构', targets: ['Kafka'] },
      ],
      growthDirections: [
        { direction: '消息队列', why: '零证据', firstStep: '用一次', priority: 1 },
      ],
      abilityProfile: {
        dimensions: [{ name: '技术深度', score: 65, rubricRef: 'tech_depth.L2', evidence: 'x' }],
        overall: 65,
      },
      meta: { ...RESULT.meta, analysisDepth: 'deep', verdictCount: 1, directionCount: 1 },
    };
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => streamResponse([frame('result', deepResult), frame('done', { elapsedMs: 9 })])),
    );

    const stream = useAnalysisStream();
    await stream.start({ resumeText: '简历', analysisDepth: 'deep' });

    expect(stream.result.value?.verdicts?.[0].skill).toBe('Kafka');
    expect(stream.result.value?.growthDirections?.[0].priority).toBe(1);
    expect(stream.result.value?.abilityProfile?.overall).toBe(65);
    expect(stream.error.value).toBeNull();
  });
});
