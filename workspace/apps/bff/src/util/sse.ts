/**
 * SSE 分帧 —— **服务端写帧**与**客户端（前端）/测试解帧**共用同一套规则。
 *
 * 为什么要收口在一个文件：SSE 是「按空行分块」的协议，而 TCP 是字节流 ——
 * 一个 chunk 的边界**不会**正好落在帧的边界上。所以解帧必须带行缓冲：
 * 读到的数据先攒起来，只在出现 `\n\n` 时才切出一个完整帧。
 *
 * 这里同时提供：
 *   - `createFrameParser()`：消费任意切分的上游字节流（用于 BFF 透传 Java 的流）
 *   - `parseFrames()`：一次性解析（用于测试与断言）
 *   - `formatEvent()`：BFF 自己发帧时用（meta / error / done）
 *
 * 与 Python 侧 `app/util/sse.py` 的规则逐字对齐 —— 两边各写一遍迟早会对不上。
 */

/** 心跳注释行。前端看到 `: ` 开头直接丢弃（`SseFrame` 不产出 event 类型）。 */
export const SSE_PING = ': ping\n\n';

export interface SseFrame {
  /** `event:` 行的值。心跳帧没有 event，为 null。 */
  event: string | null;
  /** `data:` 行的原始内容（未解析）。多条 data 行会拼成一块。 */
  data: string;
}

/**
 * 把上游字节流切成 SSE 帧。
 *
 * **关键**：chunk 边界与帧边界无关，所以必须维护 `buffer`。
 * 少了它，「一帧被 TCP 切成两半」时就会解析出两个残缺帧 ——
 * 而这在本地测试（一次读完）里永远复现不出来，只在真实网络下偶发。
 *
 * @param onFrame 每解析出一个完整帧回调一次
 * @returns `write(chunk)` / `end()` —— end 会 flush 尾部残留
 */
export function createFrameParser(onFrame: (frame: SseFrame) => void) {
  let buffer = '';

  return {
    write(chunk: string): void {
      buffer += chunk;
      let separatorIndex = buffer.indexOf('\n\n');
      while (separatorIndex !== -1) {
        const block = buffer.slice(0, separatorIndex);
        buffer = buffer.slice(separatorIndex + 2);
        const frame = parseBlock(block);
        if (frame) {
          onFrame(frame);
        }
        separatorIndex = buffer.indexOf('\n\n');
      }
    },

    /** 流结束时调用：把没凑齐一帧的残留也处理掉（容忍服务端最后没有空行）。 */
    end(): void {
      const frame = parseBlock(buffer.trim());
      if (frame) {
        onFrame(frame);
      }
      buffer = '';
    },
  };
}

/** 解析单个 SSE 块（不含结尾空行）。以 `:` 开头的注释块返回 null。 */
export function parseBlock(block: string): SseFrame | null {
  if (!block) {
    return null;
  }
  // 注释行（心跳）。规范里以冒号开头，前端/测试都不该把它当事件。
  if (block.startsWith(':')) {
    return null;
  }

  let event: string | null = null;
  const dataLines: string[] = [];

  for (const line of block.split('\n')) {
    if (line.startsWith('event:')) {
      event = line.slice('event:'.length).trim();
    } else if (line.startsWith('data:')) {
      // 注意只去掉**第一个**冒号后的一个空格，不 trim 掉 JSON 里有意义的空白
      dataLines.push(line.slice('data:'.length).replace(/^ /, ''));
    }
  }

  return { event, data: dataLines.join('\n') };
}

/** 一次性解析整段 SSE 文本（测试与断言用）。 */
export function parseFrames(raw: string): Array<{ event: string; data: string }> {
  const frames: Array<{ event: string; data: string }> = [];
  const parser = createFrameParser((frame) => {
    if (frame.event !== null) {
      frames.push({ event: frame.event, data: frame.data });
    }
  });
  parser.write(raw);
  parser.end();
  return frames;
}

/**
 * 拼一个 SSE 帧 —— BFF 自己发 meta / error / done 时用。
 *
 * `data` 必须是**单行** JSON：`JSON.stringify` 会把换行转义成 `\n`，
 * 所以直接拼是安全的；但绝不能传已经格式化的多行 JSON（会把一帧撕成两帧）。
 */
export function formatEvent(event: string, payload: unknown): string {
  return `event: ${event}\ndata: ${JSON.stringify(payload)}\n\n`;
}

/** SSE 响应头三件套 —— 少了任何一个都会在真实环境出问题。 */
export const SSE_HEADERS: Record<string, string> = {
  'Content-Type': 'text/event-stream; charset=utf-8',
  // 代理层不许缓存整条流
  'Cache-Control': 'no-cache',
  // Nginx 默认会缓冲 SSE，导致事件被攒批（最阴的一个）
  'X-Accel-Buffering': 'no',
};
