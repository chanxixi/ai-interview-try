<script setup lang="ts">
import { computed } from 'vue';

import { STAGE_LABEL, type StageName } from '../../../api/analysis';
import type { StageState } from '../composables/useAnalysisStream';

/**
 * 阶段进度条（tasks.md M7.5）。
 *
 * <h2>为什么用 `el-steps` 而不是自己画</h2>
 * 「7 个阶段 + 当前进行中 + 失败标记」是 Steps 组件的标准语义，
 * 自己画反而要处理窄屏换行、对齐、状态色 —— 3 小时里不划算。
 * 这里只做**状态映射**：把 SSE 的 `stage` 事件翻译成 Element 的 `status`。
 *
 * <h2>映射规则（与 spec §2.4 的三种 status 一一对应）</h2>
 * | SSE `status` | 步骤状态 | 含义 |
 * |---|---|---|
 * | `start` | `process` | 正在跑（高亮 + 转圈） |
 * | `ok` | `finish` | 完成（打勾） |
 * | `fail` | `error` | 这一阶段没做成（**不终止流**，后面照走） |
 *
 * 未收到的阶段是 `wait`。因为每个 stage 都会发 start + ok 一对，
 * 所以「最后一个非 pending 的 stage」天然就是当前进度。
 */
const props = defineProps<{
  stages: StageState[];
  streaming: boolean;
}>();

/**
 * 当前进行到第几步：最后一个「已出现」的阶段的序号。
 *
 * ⚠️ 用 `props.stages.length` 而不是全局 `STAGE_ORDER.length` —— 阶段数取决于
 * **本次请求的深度**（`standard` 7 格 / `deep` 8 格），而 `stages` 已经按深度建好了。
 */
const activeIndex = computed(() => {
  const index = props.stages.findIndex((s) => s.status === 'pending');
  return index === -1 ? props.stages.length : index;
});

function statusOf(stage: StageName): 'wait' | 'process' | 'finish' | 'error' {
  const state = props.stages.find((s) => s.stage === stage);
  if (!state || state.status === 'pending') {
    return 'wait';
  }
  if (state.status === 'start') {
    return 'process';
  }
  return state.status === 'ok' ? 'finish' : 'error';
}

/** 阶段副标题：优先展示该阶段的事实（页数 / 技能数 / 耗时）。 */
function detailOf(stage: StageName): string {
  const state = props.stages.find((s) => s.stage === stage);
  if (!state || state.status === 'pending') {
    return '';
  }
  const detail = state.detail ?? {};
  const bits: string[] = [];
  if (typeof detail.pages === 'number') {
    bits.push(`${detail.pages} 页`);
  }
  if (typeof detail.textLength === 'number') {
    bits.push(`${detail.textLength} 字`);
  }
  if (typeof detail.skillCount === 'number') {
    bits.push(`${detail.skillCount} 项技能`);
  }
  if (typeof detail.recommendationCount === 'number') {
    bits.push(`${detail.recommendationCount} 个岗位`);
  }
  if (typeof detail.issueCount === 'number') {
    bits.push(`${detail.issueCount} 条建议`);
  }
  // part3：`reviewed` 阶段的事实 —— 判了几条要求、给了几个提方向
  if (typeof detail.verdictCount === 'number') {
    bits.push(`${detail.verdictCount} 条判定`);
  }
  if (typeof detail.directionCount === 'number') {
    bits.push(`${detail.directionCount} 个方向`);
  }
  if (bits.length === 0 && state.elapsedMs > 0) {
    bits.push(`${state.elapsedMs} ms`);
  }
  return bits.join(' · ');
}
</script>

<template>
  <section class="panel analyzer-stages">
    <h2 class="panel__title">处理进度</h2>

    <el-steps :active="activeIndex" align-center finish-status="success">
      <el-step
        v-for="item in props.stages"
        :key="item.stage"
        :title="STAGE_LABEL[item.stage]"
        :description="detailOf(item.stage)"
        :status="statusOf(item.stage)"
      />
    </el-steps>

    <p v-if="!props.streaming && activeIndex === 0" class="panel__note">
      尚未开始 —— 提交后这里会逐阶段推进。
    </p>
  </section>
</template>
