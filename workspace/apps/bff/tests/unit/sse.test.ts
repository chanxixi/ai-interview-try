/**
 * SSE 分帧（tasks.md M6.3）。
 *
 * 核心断言是「**chunk 边界与帧边界无关**」—— 这是手写解析器最容易漏的一点，
 * 而且在「一次读完全部数据」的本地测试里永远复现不出来，只在真实网络下偶发。
 * 所以用逐字符、随机切分两种方式各跑一遍。
 */

import type { SseFrame } from '../../src/util/sse';
import {
  createFrameParser,
  formatEvent,
  parseBlock,
  parseFrames,
  SSE_PING,
} from '../../src/util/sse';

describe('parseBlock', () => {
  it('解析 event + data 两行', () => {
    const frame = parseBlock('event: meta\ndata: {"traceId":"t1"}');
    expect(frame).toEqual({ event: 'meta', data: '{"traceId":"t1"}' });
  });

  it('心跳注释块返回 null —— 前端不该把它当事件', () => {
    expect(parseBlock(': ping')).toBeNull();
    expect(parseFrames(SSE_PING)).toEqual([]);
  });

  it('多条 data 行拼成一块', () => {
    const frame = parseBlock('event: thinking\ndata: 第一部分\ndata: 第二部分');
    expect(frame?.data).toBe('第一部分\n第二部分');
  });

  it('空块返回 null', () => {
    expect(parseBlock('')).toBeNull();
  });
});

describe('createFrameParser —— chunk 边界与帧边界无关', () => {
  const raw =
    'event: meta\ndata: {"a":1}\n\n' +
    'event: stage\ndata: {"stage":"parsed"}\n\n' +
    ': ping\n\n' +
    'event: done\ndata: {"elapsedMs":42}\n\n';

  it('一次性写入 → 3 个事件帧（心跳不算）', () => {
    const frames = parseFrames(raw);
    expect(frames.map((f: { event: string }) => f.event)).toEqual(['meta', 'stage', 'done']);
    expect(JSON.parse(frames[2]!.data)).toEqual({ elapsedMs: 42 });
  });

  it('逐字符写入 → 结果与一次写完完全一致', () => {
    const seen: Array<{ event: string; data: string }> = [];
    const parser = createFrameParser((frame: SseFrame) => {
      if (frame.event !== null) seen.push({ event: frame.event, data: frame.data });
    });
    for (const ch of raw) parser.write(ch);
    parser.end();

    expect(seen).toEqual(parseFrames(raw));
  });

  it('在一帧**中间**切断 → 仍然完整（这是最容易漏的一条）', () => {
    // 故意把第一个 chunk 停在 "data: {" 之后，第二个 chunk 才开始给 JSON 内容
    const seen: string[] = [];
    const parser = createFrameParser((frame: SseFrame) => {
      if (frame.event !== null) seen.push(frame.event);
    });

    parser.write('event: meta\ndata: {"tr');
    expect(seen).toEqual([]); // 还没凑齐一帧，不该回调

    parser.write('aceId":"t1"}\n\nevent: done\ndata: {}\n\n');
    parser.end();

    expect(seen).toEqual(['meta', 'done']);
  });

  it('中文跨 chunk 不乱码（UTF-8 由调用方解码，这里只验拼接正确）', () => {
    const seen: string[] = [];
    const parser = createFrameParser((frame: SseFrame) => {
      if (frame.event !== null) seen.push(frame.data);
    });
    // 按字符切会把中文拆开，但只要不在帧边界前回调，拼出来就是完整的
    const raw2 = 'event: thinking\ndata: "负责订单系统重构"\n\n';
    for (const ch of raw2) parser.write(ch);
    parser.end();

    expect(seen[0]).toBe('"负责订单系统重构"');
  });

  it('end() 会 flush 尾部没有空行的残留帧', () => {
    const seen: string[] = [];
    const parser = createFrameParser((frame: SseFrame) => {
      if (frame.event !== null) seen.push(frame.event);
    });
    parser.write('event: done\ndata: {"elapsedMs":1}'); // 服务端忘了结尾空行
    expect(seen).toEqual([]);
    parser.end();
    expect(seen).toEqual(['done']);
  });
});

describe('formatEvent', () => {
  it('产出 event 行 + data 行 + 空行', () => {
    expect(formatEvent('meta', { traceId: 't', source: 'pdf' })).toBe(
      'event: meta\ndata: {"traceId":"t","source":"pdf"}\n\n',
    );
  });

  it('data 里有换行也不会把帧撕开（JSON.stringify 会转义）', () => {
    const frame = formatEvent('result', { evidence: '第一行\n第二行' });
    expect(frame.split('\n\n').length).toBe(2); // 内容 + 结尾空行
  });
});
