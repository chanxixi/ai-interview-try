import ElementPlus from 'element-plus';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { mount } from '@vue/test-utils';

import {
  STAGE_ORDER,
  STANDARD_STAGE_ORDER,
  stageOrderFor,
  type AnalyzeResult,
} from '../../src/api/analysis';
import ResultPanel from '../../src/pages/analyzer/components/ResultPanel.vue';

/**
 * 结果面板与阶段表的 part3 边界（N4.2 / N5.3）。
 *
 * 这一批用例守的是**同一件事的两种失败形态**：
 *
 * | 用例 | 守什么 | 不守的后果 |
 * |---|---|---|
 * | `standard 响应` | 三个新面板**不渲染且不报错** | 老前端在一次普通分析后白屏 |
 * | `stageOrderFor` | `standard` 只有 7 格、`deep` 才 8 格 | 进度条多一格永远转不动（spec §2.4 禁止） |
 *
 * 「不报错」是显式断言的：模板里一句 `result.verdicts.length` 在 `standard` 下
 * 就是 `Cannot read properties of undefined` —— 而这种崩溃在构建期发现不了
 * （TS 的可选链写漏了没人拦得住）。
 */

/**
 * 打桩 `echarts/core`：**只替换 init/use，不改被测组件的逻辑**。
 *
 * happy-dom 没有真 canvas，`echarts.init()` 会直接抛。这里要验的是「面板渲染边界」
 * 与「score=null 显示成无依据」，不是图表像素 —— 所以让图表变成空实现即可，
 * 组件内部的 option 组装、`null` 的用法仍然全部真实执行。
 */
vi.mock('echarts/core', () => ({
  init: () => ({ setOption: () => undefined, resize: () => undefined, dispose: () => undefined }),
  use: () => undefined,
}));

/** `AbilityRadar` 用 `ResizeObserver` 跟随容器尺寸；happy-dom 不保证提供它。 */
class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

beforeAll(() => {
  vi.stubGlobal('ResizeObserver', ResizeObserverStub);
});

const STANDARD_RESULT: AnalyzeResult = {
  resume: {
    sections: { education: ['某大学'], experience: [], projects: [], skills: ['Java'] },
    skills: [{ raw: 'Java', canonical: 'Java' }],
  },
  issues: [],
  match: null,
  recommendations: [],
  meta: {
    traceId: 't-std',
    llmUsed: true,
    degraded: false,
    elapsedMs: 1200,
    source: 'text',
    truncated: false,
    recommendationCount: 0,
  },
};

const DEEP_RESULT: AnalyzeResult = {
  ...STANDARD_RESULT,
  verdicts: [
    {
      skill: 'Kafka',
      importance: 'required',
      verdict: 'missing',
      reason: '简历未出现 Kafka 的任何使用证据',
      jdEvidence: '熟悉 Kafka',
      resumeEvidence: null,
    },
  ],
  improvements: [
    { area: '缺失能力', action: '补一条用到 Kafka 的实践', evidence: '负责订单系统重构', targets: ['Kafka'] },
  ],
  growthDirections: [
    { direction: '消息队列', why: '目标岗位硬性要求，简历零证据', firstStep: '在一个项目里引入 Kafka', priority: 1 },
  ],
  abilityProfile: {
    dimensions: [
      { name: '技术深度', score: 65, rubricRef: 'tech_depth.L2', evidence: '有实现' },
      { name: '协作沟通', score: null, rubricRef: 'collaboration.L0', evidence: '' },
    ],
    overall: 65,
  },
  meta: {
    ...STANDARD_RESULT.meta,
    traceId: 't-deep',
    analysisDepth: 'deep',
    verdictCount: 1,
    directionCount: 1,
  },
};

function mountPanel(result: AnalyzeResult) {
  return mount(ResultPanel, {
    props: { result },
    global: { plugins: [ElementPlus] },
  });
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe('ResultPanel —— part3 的渲染边界', () => {
  it('N5.3：standard 响应不渲染三个新面板，且不报错', () => {
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => undefined);

    const wrapper = mountPanel(STANDARD_RESULT);

    expect(wrapper.find('.verdict-panel').exists()).toBe(false);
    expect(wrapper.find('.ability-panel').exists()).toBe(false);
    expect(wrapper.find('.advice-panel').exists()).toBe(false);
    // 老面板一个不少（回归：改了 ResultPanel 不能把 part2 的东西弄丢）
    expect(wrapper.text()).toContain('简历诊断');
    // 渲染期零报错、零告警 —— 少一个可选链就会在这里炸
    expect(errorSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it('deep 响应渲染三块，且判定、优化点、方向都可见', () => {
    const wrapper = mountPanel(DEEP_RESULT);

    expect(wrapper.find('.verdict-panel').exists()).toBe(true);
    expect(wrapper.find('.advice-panel').exists()).toBe(true);
    expect(wrapper.find('.ability-panel').exists()).toBe(true);

    expect(wrapper.text()).toContain('Kafka');
    expect(wrapper.text()).toContain('缺失');
    expect(wrapper.text()).toContain('消息队列');
    expect(wrapper.text()).toContain('补一条用到 Kafka 的实践');
  });

  it('deep 的元信息条带出判定条数与方向数', () => {
    const wrapper = mountPanel(DEEP_RESULT);

    expect(wrapper.text()).toContain('深度分析');
    expect(wrapper.text()).toContain('判定 1 条');
  });

  it('★ score = null 的维度显示「无依据」，不显示 0 分', () => {
    const wrapper = mountPanel(DEEP_RESULT);

    const missing = wrapper.find('.ability__score--none');
    expect(missing.exists()).toBe(true);
    expect(missing.text()).toBe('无依据');
    // 该维仍然出现在清单里（不是被删掉）—— 删掉会让用户以为漏画了一维
    expect(wrapper.text()).toContain('协作沟通');
    // 有分的那一维照常显示分数
    expect(wrapper.find('.ability__score').text()).toBe('65');
  });

  it('两个面板都标注「AI 判定，仅供参考」', () => {
    const wrapper = mountPanel(DEEP_RESULT);

    expect(wrapper.findAll('.verdict-panel__hint').length).toBeGreaterThanOrEqual(2);
  });
});

describe('stageOrderFor —— 进度条的格数由深度决定', () => {
  it('standard 是 part2 的 7 格，不含 reviewed', () => {
    expect(stageOrderFor('standard')).toEqual(STANDARD_STAGE_ORDER);
    expect(stageOrderFor('standard')).toHaveLength(7);
    expect(stageOrderFor('standard')).not.toContain('reviewed');
  });

  it('deep 是 8 格，且 reviewed 在最后（C5 的位置约定）', () => {
    expect(stageOrderFor('deep')).toEqual(STAGE_ORDER);
    expect(stageOrderFor('deep')).toHaveLength(8);
    expect(stageOrderFor('deep')[7]).toBe('reviewed');
  });
});
