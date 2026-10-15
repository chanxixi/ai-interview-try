/**
 * SSE 分帧 —— 前端**唯一**把字节流还原成事件的地方（tasks.md M7.3）。
 *
 * <h2>为什么必须带行缓冲</h2>
 * SSE 是「按空行分块」的协议，而 TCP / `ReadableStream` 是字节流：
 * 一个 chunk 的边界**不会**正好落在帧边界上。一个 `data: {...}` 完全可能被切成
 * 「前半段在这个 chunk、后半段在下一个 chunk」。少了 buffer 就会解析出两个残缺帧，
 * 而本地测试（一次读完）永远复现不出来 —— 只在真实网络下偶发。
 *
 * 规则与后端逐字对齐（`bff/src/util/sse.ts`、`analyzer/app/util/sse.py`）：
 * 按 `\n\n` 分帧 → 丢掉以 `:` 开头的注释帧（心跳 `: ping`）→ 取 `event:` / `data:` 行。
 *
 * <h2>为什么不直接用 `EventSource`</h2>
 * `EventSource` 只支持 GET、不能带 multipart body，也拿不到自定义请求头。
 * 本项目的入口是 `POST multipart/form-data`，所以只能 `fetch` + `ReadableStream` 手解
 * （ADR-104，写进 plan.md §2）。
 */

export interface SseFrame {
  /** `event:` 行的值；心跳帧没有 event，返回 null（调用方应丢弃）。 */
  event: string | null;
  /** `data:` 行的原始内容（尚未 JSON.parse）。多行 data 会按 `\n` 拼起来。 */
  data: string;
}

/** 解析单个 SSE 块（不含结尾空行）。以 `:` 开头的注释块返回 null。 */
export function parseSseBlock(block: string): SseFrame | null {
  if (!block) {
    return null;
  }
  // 心跳注释：`: ping`。规范里以冒号开头，绝不能当成一个事件。
  if (block.startsWith(':')) {
    return null;
  }

  let event: string | null = null;
  const dataLines: string[] = [];

  for (const line of block.split('\n')) {
    if (line.startsWith('event:')) {
      event = line.slice('event:'.length).trim();
    } else if (line.startsWith('data:')) {
      // 只吃掉冒号后的**一个**空格，不 trim —— JSON 字符串内部的空白是有意义的
      dataLines.push(line.slice('data:'.length).replace(/^ /, ''));
    }
  }

  return { event, data: dataLines.join('\n') };
}

/**
 * 增量式帧解析器：喂任意切分的 chunk，凑齐一帧就回调一次。
 *
 * @param onFrame 每解析出一个完整帧回调一次（心跳帧不回调）
 */
export function createSseFrameParser(onFrame: (frame: SseFrame) => void) {
  let buffer = '';

  return {
    write(chunk: string): void {
      buffer += chunk;
      let index = buffer.indexOf('\n\n');
      while (index !== -1) {
        const block = buffer.slice(0, index);
        buffer = buffer.slice(index + 2);
        const frame = parseSseBlock(block);
        if (frame) {
          onFrame(frame);
        }
        index = buffer.indexOf('\n\n');
      }
    },

    /** 流结束时调用：容忍服务端最后一帧没有补空行。 */
    end(): void {
      const frame = parseSseBlock(buffer.trim());
      if (frame) {
        onFrame(frame);
      }
      buffer = '';
    },
  };
}

/** 一次性解析整段 SSE 文本（单测 / 调试用）。 */
export function parseSseFrames(raw: string): Array<{ event: string; data: string }> {
  const frames: Array<{ event: string; data: string }> = [];
  const parser = createSseFrameParser((frame) => {
    if (frame.event !== null) {
      frames.push({ event: frame.event, data: frame.data });
    }
  });
  parser.write(raw);
  parser.end();
  return frames;
}
