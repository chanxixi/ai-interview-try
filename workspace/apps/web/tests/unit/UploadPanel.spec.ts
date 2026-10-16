import ElementPlus from 'element-plus';
import { describe, expect, it } from 'vitest';
import { mount } from '@vue/test-utils';

import type { DeepCapability } from '../../src/api/types';
import UploadPanel from '../../src/pages/analyzer/components/UploadPanel.vue';

/**
 * 「自动决定深度」的前端侧（part3，C8 / §2.6.1）。
 *
 * 守的是**三态各自的默认值**——这是本功能唯一容易悄悄写错的地方：
 *
 * | 探测结论 | 能否选「深度」 | 默认选中 |
 * |---|---|---|
 * | `available` | ✅ | **`deep`** |
 * | `unknown`（未回来 / 探测失败） | ✅ | `standard` |
 * | `unavailable` | ❌ | `standard` |
 *
 * 用**布尔**表达会丢掉「未知」，进而必然错一边：默认 deep 会在探测失败时白等两次 LLM；
 * 默认 standard 则违背「有 LLM 就用 LLM」。这两条都有对应用例。
 *
 * ⚠️ 这里只测**前端预置选项**；接口缺省 (`analysisDepth`) 仍是 `standard`（AC25），
 * 那条由 analyzer 的快照断言守（`tests/api/test_contract_shape.py`）。
 */
function mountPanel(props: { busy?: boolean; deepCapability?: DeepCapability } = {}) {
  return mount(UploadPanel, {
    props: { busy: false, ...props },
    global: { plugins: [ElementPlus] },
  });
}

/** Element Plus 的 `el-radio-button` 渲染成 label + 内部 `input[type=radio]`。 */
const depths = (wrapper: ReturnType<typeof mountPanel>) => wrapper.findAll('input[type="radio"]');

/** 第 0 个是「标准」，第 1 个是「深度」。 */
const isChecked = (wrapper: ReturnType<typeof mountPanel>, index: number) =>
  (depths(wrapper)[index].element as HTMLInputElement).checked;

const isDeepDisabled = (wrapper: ReturnType<typeof mountPanel>) =>
  wrapper.findAll('.el-radio-button')[1].classes().includes('is-disabled');

describe('UploadPanel —— 「深度」与能力探测的三态联动', () => {
  it('available：默认选中「深度」，可切回「标准」', async () => {
    const wrapper = mountPanel({ deepCapability: 'available' });

    expect(isChecked(wrapper, 1)).toBe(true);
    expect(isChecked(wrapper, 0)).toBe(false);
    expect(isDeepDisabled(wrapper)).toBe(false);
    expect(wrapper.find('.panel__note--warn').exists()).toBe(false);
    // 预置 deep 时必须说明理由，否则用户不知道为什么这次变慢了
    expect(wrapper.text()).toContain('检测到可用的 LLM');

    await depths(wrapper)[0].setValue();
    expect(isChecked(wrapper, 0)).toBe(true);
  });

  it('★ unknown（探测失败 / 尚未回来）：放行但**不预置** deep', () => {
    const wrapper = mountPanel(); // 缺省即 unknown

    expect(isChecked(wrapper, 0)).toBe(true);
    expect(isDeepDisabled(wrapper)).toBe(false);
    expect(wrapper.find('.panel__note--warn').exists()).toBe(false);
  });

  it('unavailable：禁用「深度」+ 常驻提示，且默认「标准」', () => {
    const wrapper = mountPanel({ deepCapability: 'unavailable' });

    expect(isDeepDisabled(wrapper)).toBe(true);
    expect(wrapper.find('.panel__note--warn').exists()).toBe(true);
    expect(isChecked(wrapper, 0)).toBe(true);
  });

  it('★ available → unavailable：已预置的「深度」被拨回「标准」', async () => {
    const wrapper = mountPanel({ deepCapability: 'available' });
    expect(isChecked(wrapper, 1)).toBe(true);

    // 探测结论异步到达，且是「LLM 不可用」
    await wrapper.setProps({ deepCapability: 'unavailable' });

    expect(isChecked(wrapper, 0)).toBe(true);
    expect(isChecked(wrapper, 1)).toBe(false);
  });

  it('★ 用户亲手选过之后，探测结论不再覆盖他的选择', async () => {
    const wrapper = mountPanel({ deepCapability: 'available' });
    expect(isChecked(wrapper, 1)).toBe(true);

    await depths(wrapper)[0].setValue(); // 用户主动切成「标准」
    expect(isChecked(wrapper, 0)).toBe(true);

    // 探测结论来回抖动，都不该把用户的选择顶掉
    await wrapper.setProps({ deepCapability: 'unknown' });
    await wrapper.setProps({ deepCapability: 'available' });

    expect(isChecked(wrapper, 0)).toBe(true);
  });
});
