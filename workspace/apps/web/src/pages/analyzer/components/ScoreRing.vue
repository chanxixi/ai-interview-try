<script setup lang="ts">
import { GaugeChart } from 'echarts/charts';
import { TooltipComponent } from 'echarts/components';
import * as echarts from 'echarts/core';
import { CanvasRenderer } from 'echarts/renderers';
import { onBeforeUnmount, onMounted, ref, watch } from 'vue';

/**
 * 匹配分环（tasks.md M7.6）。
 *
 * <h2>为什么用 ECharts 而不是 CSS conic-gradient</h2>
 * 分数环要同时满足「有数值动画」「有刻度语义」「和页面其它图表同风格」。
 * conic-gradient 能做静态环，但数值动画要自己写补间，且文字居中与响应式
 * 都要手工处理；ECharts 的 `gauge` 一个配置就够，且后续要加图表时风格统一。
 *
 * <h2>按需引入，不用 `import * as echarts from 'echarts'`</h2>
 * 全量引入约 1MB（gzip 后仍 ~300KB），而这里只用到一个仪表盘。
 * 用 `echarts/core` + `echarts.use([...])` 只打进 gauge + canvas 渲染器，
 * 首屏体积小一个数量级 —— 这是「前端出身」最容易漏、但收益最直接的一点。
 */
echarts.use([GaugeChart, TooltipComponent, CanvasRenderer]);

const props = defineProps<{
  score: number;
  /** 环下方的说明文字（例如「与 job-java-01 的匹配度」） */
  caption?: string;
}>();

const host = ref<HTMLElement | null>(null);
let chart: echarts.ECharts | null = null;
let observer: ResizeObserver | null = null;

/**
 * 分数 → 颜色。
 *
 * 口径：≥80 达标（品牌青）／60–79 有差距（琥珀）／<60 差距明显（红）。
 * 阈值是**展示口径**，与后端打分公式无关（后端只给 0–100 的整数）。
 */
function colorOf(score: number): string {
  if (score >= 80) {
    return '#0d9488';
  }
  return score >= 60 ? '#d97706' : '#dc2626';
}

function option(): echarts.EChartsCoreOption {
  const color = colorOf(props.score);
  return {
    series: [
      {
        type: 'gauge',
        startAngle: 215,
        endAngle: -35,
        min: 0,
        max: 100,
        radius: '92%',
        center: ['50%', '58%'],
        // 进度条：只有它显示「已得分数」，底环是浅灰
        progress: { show: true, width: 13, roundCap: true, itemStyle: { color } },
        axisLine: { roundCap: true, lineStyle: { width: 13, color: [[1, '#eceff3']] } },
        pointer: { show: false },
        axisTick: { show: false },
        splitLine: { show: false },
        axisLabel: { show: false },
        anchor: { show: false },
        title: { show: false },
        detail: {
          valueAnimation: true,
          offsetCenter: [0, '2%'],
          fontSize: 34,
          fontWeight: 700,
          color,
          formatter: '{value}',
        },
        data: [{ value: props.score }],
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

  // 容器尺寸由父级 flex 决定，用 ResizeObserver 而不是 window.resize ——
  // 侧栏折叠、字体变化等「不触发 window.resize」的场景也能跟着重绘
  observer = new ResizeObserver(() => chart?.resize());
  observer.observe(host.value);
});

watch(() => props.score, () => chart?.setOption(option()));

onBeforeUnmount(() => {
  observer?.disconnect();
  observer = null;
  chart?.dispose();
  chart = null;
});
</script>

<template>
  <figure class="score-ring">
    <div ref="host" class="score-ring__canvas" />
    <figcaption v-if="props.caption" class="score-ring__caption">{{ props.caption }}</figcaption>
  </figure>
</template>
