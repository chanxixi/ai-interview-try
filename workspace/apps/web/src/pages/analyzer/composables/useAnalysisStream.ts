import { computed, ref, shallowRef } from 'vue';

import {
  STAGE_ORDER,
  type AnalysisInput,
  type AnalyzeResult,
  type DonePayload,
  type ErrorPayload,
  type MetaPayload,
  type StageName,
  type StagePayload,
  type StageStatus,
  type SyncErrorBody,
} from '../../../api/analysis';
import { createSseFrameParser } from '../../../utils/sse';

/**
 * 流式分析组合式函数（tasks.md M7.3）。
 *
 * <h2>它做什么</h2>
 * 发一次 `POST /api/analysis/stream`（multipart），然后把回来的 SSE 帧
 * 映射成一组**响应式状态**给页面用：`stages` / `thinking` / `result` / `error`。
 *
 * <h2>它不做什么（spec §2.7）</h2>
 * 不解析 PDF、不判断技能、不排序推荐 —— 那些都在后端。这里连 `score` 都不碰。
 *
 * <h2>两种错误，两条路</h2>
 * | 类型 | 时机 | 表现 |
 * |---|---|---|
 * | **同步错误** | 建流之前（413 超大 / 415 非 PDF / 400 空输入） | `response.ok === false`，读 JSON 错误体 |
 * | **流内错误** | 建流之后（422 损坏 / 加密 / 无文本层） | `event: error`，之后还会来 `done` |
 *
 * 这条分界线来自 spec §2.5：「建流前能判定的」走 HTTP 状态码，
 * 「必须读完文件才知道的」只能走流内事件。前端两条都要处理，否则 415 会显示成「没反应」。
 */

/** 单个阶段的视图状态。进度条按 `STAGE_ORDER` 渲染，状态从事件里回填。 */
export interface StageState {
  stage: StageName;
  status: StageStatus | 'pending';
  elapsedMs: number;
  detail: Record<string, unknown>;
}

function initialStages(): StageState[] {
  return STAGE_ORDER.map((stage) => ({ stage, status: 'pending', elapsedMs: 0, detail: {} }));
}

export function useAnalysisStream(baseUrl = '') {
  const isStreaming = ref(false);
  const meta = ref<MetaPayload | null>(null);
  const stages = ref<StageState[]>(initialStages());
  /** 打字机文本：每条 `thinking` 的 `delta` 追加。降级时可能一直是空串。 */
  const thinking = ref('');
  /** 用 shallowRef：结果对象是整体替换的，不需要深响应，省掉一层递归代理。 */
  const result = shallowRef<AnalyzeResult | null>(null);
  /** 流内错误（`event: error`）或同步错误（HTTP 非 2xx）。 */
  const error = ref<{ code: string; message: string; traceId?: string } | null>(null);
  const elapsedMs = ref(0);
  const receivedDone = ref(false);

  /** 当前正在跑（或最后跑过）的阶段 —— 给进度条做「进行中」高亮。 */
  const currentStage = computed<StageName | null>(() => {
    const running = stages.value.find((s) => s.status === 'start');
    if (running) {
      return running.stage;
    }
    const lastOk = [...stages.value].reverse().find((s) => s.status !== 'pending');
    return lastOk?.stage ?? null;
  });

  let controller: AbortController | null = null;

  /** 把一次 `stage` 事件写回状态。同 stage 的 `start` → `ok` 是两条事件，后者覆盖前者。 */
  function applyStage(payload: StagePayload): void {
    const index = stages.value.findIndex((s) => s.stage === payload.stage);
    if (index === -1) {
      // 未知 stage：契约里不该出现，但不该因此炸掉整条流 —— 忽略即可
      return;
    }
    stages.value[index] = {
      stage: payload.stage,
      status: payload.status,
      elapsedMs: payload.elapsedMs,
      detail: payload.detail ?? {},
    };
  }

  function reset(): void {
    isStreaming.value = false;
    meta.value = null;
    stages.value = initialStages();
    thinking.value = '';
    result.value = null;
    error.value = null;
    elapsedMs.value = 0;
    receivedDone.value = false;
  }

  /** 主动中止（用户点「取消」/ 组件卸载）。 */
  function abort(): void {
    controller?.abort();
    controller = null;
    isStreaming.value = false;
  }

  /**
   * 发起一次流式分析。**不会抛异常** —— 所有失败都落在 `error` 上，
   * 这样组件里不用写 try/catch，模板也永远有一个确定的渲染分支。
   */
  async function start(input: AnalysisInput): Promise<void> {
    reset();
    isStreaming.value = true;

    const form = new FormData();
    if (input.file) {
      // 同时传 file 与 resumeText 时以 file 为准（spec §2.2），所以有文件就不再带文本
      form.append('file', input.file, input.file.name);
    } else if (input.resumeText) {
      form.append('resumeText', input.resumeText);
    }
    if (input.jobId) {
      form.append('jobId', input.jobId);
    }
    if (input.jdText) {
      form.append('jdText', input.jdText);
    }

    controller = new AbortController();

    let response: Response;
    try {
      response = await fetch(`${baseUrl}/api/analysis/stream`, {
        method: 'POST',
        // Accept 必须显式带上：BFF 用它决定走流式还是回退同步 JSON（AC21）
        headers: { Accept: 'text/event-stream' },
        body: form,
        signal: controller.signal,
      });
    } catch (err) {
      isStreaming.value = false;
      error.value = {
        code: 'NETWORK_ERROR',
        message: err instanceof Error && err.name === 'AbortError' ? '已取消' : '无法连接 BFF，请确认服务已启动',
      };
      return;
    }

    if (!response.ok) {
      isStreaming.value = false;
      error.value = await readSyncError(response);
      return;
    }

    if (!response.body) {
      isStreaming.value = false;
      error.value = { code: 'INTERNAL_ERROR', message: '响应没有可读的流' };
      return;
    }

    const parser = createSseFrameParser((frame) => {
      if (frame.event === null) {
        return;
      }
      let payload: unknown;
      try {
        payload = JSON.parse(frame.data) as unknown;
      } catch {
        // 单帧 JSON 坏了不该毁掉整条流：后面的帧仍然是好的
        return;
      }

      switch (frame.event) {
        case 'meta':
          meta.value = payload as MetaPayload;
          break;
        case 'stage':
          applyStage(payload as StagePayload);
          break;
        case 'thinking':
          thinking.value += (payload as { delta: string }).delta ?? '';
          break;
        case 'result':
          result.value = payload as AnalyzeResult;
          break;
        case 'error':
          error.value = payload as ErrorPayload;
          break;
        case 'done':
          elapsedMs.value = (payload as DonePayload).elapsedMs ?? 0;
          receivedDone.value = true;
          break;
        default:
          break;
      }
    });

    try {
      await pump(response.body, parser);
    } catch (err) {
      if (!(err instanceof Error) || err.name !== 'AbortError') {
        // 流中途断了：已经拿到的部分（stages / thinking）保留，只补一个错误提示
        error.value = error.value ?? { code: 'STREAM_INTERRUPTED', message: '连接中断，结果可能不完整' };
      }
    } finally {
      isStreaming.value = false;
      controller = null;
    }
  }

  return {
    // 状态
    isStreaming,
    meta,
    stages,
    currentStage,
    thinking,
    result,
    error,
    elapsedMs,
    receivedDone,
    // 动作
    start,
    abort,
    reset,
  };
}

/**
 * 把 `ReadableStream` 喂给帧解析器。
 *
 * **用 `TextDecoder({ stream: true })` 而不是 `TextDecoderStream`**：后者在
 * 测试环境（happy-dom）里不一定存在，而手工 decoder 同时解决了「中文被 chunk 边界切开」
 * 的问题 —— `stream: true` 会把不完整的多字节序列留到下一轮。
 */
async function pump(
  body: ReadableStream<Uint8Array>,
  parser: ReturnType<typeof createSseFrameParser>,
): Promise<void> {
  const reader = body.getReader();
  const decoder = new TextDecoder('utf-8');
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }
      parser.write(decoder.decode(value, { stream: true }));
    }
    parser.write(decoder.decode());
    parser.end();
  } finally {
    reader.releaseLock();
  }
}

/** 读同步错误体（`{code, message, traceId}`）；解析不了就退化成 HTTP 状态码。 */
async function readSyncError(response: Response): Promise<{ code: string; message: string; traceId?: string }> {
  try {
    const body = (await response.json()) as SyncErrorBody;
    return {
      code: body.code ?? 'INTERNAL_ERROR',
      message: body.message ?? `请求失败（HTTP ${response.status}）`,
      traceId: body.traceId,
    };
  } catch {
    return { code: 'INTERNAL_ERROR', message: `请求失败（HTTP ${response.status}）` };
  }
}
