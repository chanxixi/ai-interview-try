<script setup lang="ts">
import { RadarChart } from 'echarts/charts';
import { TooltipComponent } from 'echarts/components';
import * as echarts from 'echarts/core';
import { CanvasRenderer } from 'echarts/renderers';
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';

import type { AbilityDimension, AbilityProfile } from '../../../api/analysis';

/**
 * 六维能力画像（part3 N5.2）。
 *
 * <h2>为什么必须按需引入 ECharts</h2>
 * 与 {@link ScoreRing} 同一个理由：全量 `import * as echarts from 'echarts'` 约 1MB
 * （gzip 后仍 ~300KB），而这里只用到一个雷达图。`echarts/core` + `use([RadarChart, …])`
 * 只打进雷达 + canvas 渲染器。
 *
 * <h2>★ 本组件最重要的行为：`score === null` **绝不画成 0**</h2>
 * spec §2.5.2 ① 把这条写成硬性克制：`协作沟通` / `成长性` 在简历里常常**真的没有证据**，
 * 落 `L0` 是常态而不是缺点。如果把它画成 0，用户会看到「协作沟通 0 分」并去优化一个
 * 本来就不该有证据的地方 —— 那是**编分的另一种形态**（用 0 冒充「没有结论」）。
 *
 * 所以：
 * - 雷达图上该顶点用 `null` —— ECharts 会**断开**这一角（不连成 0），形状本身就说明「缺」；
 * - 图下方的清单里显示「无依据」，并给出 `rubricRef` 与原文证据，让用户知道怎么补。
 *
 * <h2>前端不重排、不算分</h2>
 * 维度顺序、分数、`overall` 全部来自后端（唯一公式在 `ability_profile.py`）。
 * 这里连求和都不做 —— 一旦前端自己算一遍 `overall`，就会出现第二个公式。
 */
echarts.use([RadarChart, TooltipComponent, CanvasRenderer]);

const props = defineProps<{
  profile: AbilityProfile;
}>();

const dimensions = computed<AbilityDimension[]>(() => props.profile.dimensions ?? []);

/** 有没有任何一维是「无依据」—— 用来决定要不要显示那句解释。 */
const hasMissing = computed(() => dimensions.value.some((item) => item.score === null));

const host = ref<HTMLElement | null>(null);
let chart: echarts.ECharts | null = null;
let observer: ResizeObserver | null = null;

function option(): echarts.EChartsCoreOption {
  const data = dimensions.value.map((item) => item.score);
  return {
    tooltip: {
      trigger: 'item',
      formatter: () => {
        const lines = dimensions.value.map((item) =>
          item.score === null
            ? `${item.name}：无依据`
            : `${item.name}：${item.score}（${item.rubricRef}）`,
        );
        const overall =
          props.profile.overall === null ? '无依据' : String(props.profile.overall);
        return [`综合分：${overall}`, '---', ...lines].join('<br/>');
      },
    },
    radar: {
      indicator: dimensions.value.map((item) => ({ name: item.name, max: 100 })),
      radius: '66%',
      center: ['50%', '52%'],
      splitNumber: 4,
      axisName: { color: '#475569', fontSize: 12 },
      splitLine: { lineStyle: { color: '#e2e8f0' } },
      splitArea: { areaStyle: { color: ['#ffffff', '#f8fafc'] } },
      axisLine: { lineStyle: { color: '#e2e8f0' } },
    },
    series: [
      {
        type: 'radar',
        symbolSize: 5,
        lineStyle: { color: '#0d9488', width: 2 },
        itemStyle: { color: '#0d9488' },
        areaStyle: { color: 'rgba(13, 148, 136, 0.16)' },
        // `null` 会让折线在这一角**断开**（不连到 0）—— 这正是我们要的表达
        data: [{ value: data, name: '能力画像' }],
      },
    ],
  };
}

onMounted(() => {
  if (!host.value) {
    return;
  }
  chart = echarts.init(host.value);
  chart.setOption(option());

  observer = new ResizeObserver(() => chart?.resize());
  observer.observe(host.value);
});

watch(() => props.profile, () => chart?.setOption(option()), { deep: true });

onBeforeUnmount(() => {
  observer?.disconnect();
  observer = null;
  chart?.dispose();
  chart = null;
});
</script>

<template>
  <section class="panel ability-panel">
    <h2 class="panel__title">
      能力画像
      <el-tag class="title-tag" size="small" effect="plain">
        综合 {{ props.profile.overall === null ? '无依据' : props.profile.overall }}
      </el-tag>
      <span class="verdict-panel__hint">AI 判定，仅供参考</span>
    </h2>

    <div class="ability-panel__body">
      <div ref="host" class="ability-panel__canvas" />

      <ul class="ability-list">
        <li v-for="item in dimensions" :key="item.name" class="ability">
          <div class="ability__head">
            <span class="ability__name">{{ item.name }}</span>
            <!-- ★ score === null → 「无依据」，绝不显示 0 -->
            <span v-if="item.score === null" class="ability__score ability__score--none">
              无依据
            </span>
            <span v-else class="ability__score">{{ item.score }}</span>
          </div>
          <p v-if="item.evidence" class="ability__evidence">{{ item.evidence }}</p>
          <p v-else class="ability__evidence ability__evidence--none">
            简历中找不到可引用的证据
          </p>
          <code class="ability__ref">{{ item.rubricRef }}</code>
        </li>
      </ul>
    </div>

    <p v-if="hasMissing" class="panel__note">
      「无依据」表示该维度在简历里找不到可引用的证据 —— 这是**结论，不是 0 分**。
      图上对应的角会断开，而不是画到圆心。
    </p>
  </section>
</template>
