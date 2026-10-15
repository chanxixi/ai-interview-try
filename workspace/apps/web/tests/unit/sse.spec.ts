import { describe, expect, it } from 'vitest';

import { createSseFrameParser, parseSseBlock, parseSseFrames } from '../../src/utils/sse';

/**
 * 分帧器单测（tasks.md M7.3 / M8.4）。
 *
 * 重点不是「正常能解」，而是**跨 chunk 截断**：真实网络下
 * 一帧被 TCP 切成两半是常态，而在本地「一次读完」的测试里永远复现不出来。
 */

const FRAME_A = 'event: meta\ndata: {"traceId":"t-1","source":"pdf"}\n\n';
const FRAME_B = 'event: stage\ndata: {"stage":"parsed","status":"ok","elapsedMs":12,"detail":{"pages":2}}\n\n';

describe('parseSseBlock', () => {
  it('解析 event + data 两行', () => {
    expect(parseSseBlock('event: meta\ndata: {"a":1}')).toEqual({ event: 'meta', data: '{"a":1}' });
  });

  it('心跳注释块返回 null（不能被当成事件）', () => {
    expect(parseSseBlock(': ping')).toBeNull();
  });

  it('只吃掉 data 冒号后的一个空格，保留 JSON 内部空白', () => {
    expect(parseSseBlock('event: thinking\ndata: {"delta":" 保留 "}')?.data).toBe('{"delta":" 保留 "}');
  });
});

describe('createSseFrameParser', () => {
  it('一帧一次性到达', () => {
    const events: string[] = [];
    const parser = createSseFrameParser((f) => events.push(f.event ?? ''));
    parser.write(FRAME_A);
    parser.end();
    expect(events).toEqual(['meta']);
  });

  it('★ 一帧被切成两半（跨 chunk 截断）', () => {
    const frames: Array<{ event: string | null; data: string }> = [];
    const parser = createSseFrameParser((f) => frames.push(f));

    // 在 `data:` 的 JSON 中间切开
    const cut = FRAME_A.indexOf('source') + 3;
    parser.write(FRAME_A.slice(0, cut));
    // 此时还没有空行，一帧都不该产出
    expect(frames).toHaveLength(0);

    parser.write(FRAME_A.slice(cut));
    parser.end();

    expect(frames).toHaveLength(1);
    expect(frames[0].event).toBe('meta');
    expect(JSON.parse(frames[0].data)).toEqual({ traceId: 't-1', source: 'pdf' });
  });

  it('★ 一次 chunk 里含多帧 + 半帧尾巴', () => {
    const frames: Array<{ event: string | null; data: string }> = [];
    const parser = createSseFrameParser((f) => frames.push(f));

    parser.write(FRAME_A + FRAME_B + 'event: done\ndata: {"elap');
    expect(frames.map((f) => f.event)).toEqual(['meta', 'stage']);

    parser.write('sedMs":7}\n\n');
    parser.end();
    expect(frames.map((f) => f.event)).toEqual(['meta', 'stage', 'done']);
  });

  it('字节级切分（每 1 个字符喂一次）也能还原出完整序列', () => {
    const frames: Array<{ event: string | null; data: string }> = [];
    const parser = createSseFrameParser((f) => frames.push(f));
    for (const ch of FRAME_A + FRAME_B) {
      parser.write(ch);
    }
    parser.end();
    expect(frames.map((f) => f.event)).toEqual(['meta', 'stage']);
  });

  it('心跳帧被丢弃，不打乱事件顺序', () => {
    const frames: Array<{ event: string | null; data: string }> = [];
    const parser = createSseFrameParser((f) => frames.push(f));
    parser.write(FRAME_A + ': ping\n\n' + FRAME_B);
    parser.end();
    expect(frames.map((f) => f.event)).toEqual(['meta', 'stage']);
  });

  it('end() 容忍最后一帧缺空行', () => {
    const frames: Array<{ event: string | null; data: string }> = [];
    const parser = createSseFrameParser((f) => frames.push(f));
    parser.write('event: done\ndata: {"elapsedMs":9}');
    parser.end();
    expect(frames).toHaveLength(1);
    expect(frames[0].event).toBe('done');
  });
});

describe('parseSseFrames', () => {
  it('只返回带 event 的帧（心跳不计）', () => {
    const frames = parseSseFrames(FRAME_A + ': ping\n\n' + FRAME_B);
    expect(frames.map((f) => f.event)).toEqual(['meta', 'stage']);
  });
});
