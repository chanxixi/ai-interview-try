<script setup lang="ts">
import { computed, ref } from 'vue';

import { ApiRequestError, fetchPingChain } from '../../api/client';
import ChainPanel from '../../components/ChainPanel.vue';
import { buildChain, type ChainHop } from '../../utils/chain';

/**
 * 全链连通性自检 —— **part1 的页面原样迁入**（tasks.md M7.2：「功能不丢」）。
 *
 * 迁移时只改了两件事：① 路径从根 `/` 变为 `/connectivity`；
 * ② 外层不再有 `main.page` 的顶栏（顶栏已提到 `App.vue`）。逻辑一行没动。
 *
 * 它的价值在于：当分析页出问题时，这一页能 30 秒内告诉你
 * 「是四层里哪一层挂了」还是「traceId 没贯穿」。
 */
type Phase = 'idle' | 'loading' | 'done' | 'failed';

interface FailureView {
  code: string;
  message: string;
  traceId?: string;
}

const phase = ref<Phase>('idle');
const hops = ref<ChainHop[]>([]);
const traceId = ref('');
const failure = ref<FailureView | null>(null);
const raw = ref('');

const allReachable = computed(
  () => hops.value.length > 0 && hops.value.every((hop) => hop.status === 'ok'),
);

/**
 * 运行全链连通性检查。
 *
 * traceId 由**前端生成**：能原样出现在每一跳的响应里，就说明
 * Vue → BFF → job-service → analyzer 的透传链是通的（spec.md §2.8）。
 */
async function runCheck(): Promise<void> {
  phase.value = 'loading';
  failure.value = null;
  raw.value = '';

  const clientTraceId = crypto.randomUUID();

  try {
    const result = await fetchPingChain(clientTraceId);
    hops.value = buildChain(result.data, clientTraceId);
    traceId.value = result.traceId;
    raw.value = JSON.stringify(result.data, null, 2);
    phase.value = 'done';
  } catch (error) {
    hops.value = [];
    phase.value = 'failed';

    if (error instanceof ApiRequestError) {
      failure.value = { code: error.code, message: error.message, traceId: error.traceId };
      traceId.value = error.traceId ?? clientTraceId;
    } else {
      // 连 BFF 都没连上：这不是业务错误，是环境问题，单独提示
      failure.value = { code: 'NETWORK_ERROR', message: '无法连接 BFF，请确认服务已启动' };
      traceId.value = clientTraceId;
    }
  }
}
</script>

<template>
  <main class="page">
    <header class="page__head">
      <p class="page__eyebrow">诊断工具</p>
      <h1 class="page__title">全链连通性自检</h1>
      <p class="page__desc">
        验证 <strong>Vue → BFF → job-service → analyzer</strong> 四层是否可达、traceId 是否全链贯穿。
        分析页出现异常时，先跑一次这里，能直接定位是哪一层的问题。
      </p>
    </header>

    <section class="actions">
      <el-button type="primary" :loading="phase === 'loading'" @click="runCheck">
        {{ phase === 'loading' ? '检测中…' : '运行连通性检查' }}
      </el-button>
      <span
        v-if="phase === 'done'"
        class="actions__hint"
        :class="allReachable ? 'is-ok' : 'is-warn'"
      >
        {{ allReachable ? '四层全部可达' : '存在不可达的跳，见下方详情' }}
      </span>
    </section>

    <el-alert
      v-if="phase === 'failed' && failure"
      class="alert"
      type="error"
      :closable="false"
      show-icon
    >
      <template #title>
        <code class="mono">{{ failure.code }}</code>
        <span>{{ failure.message }}</span>
      </template>
    </el-alert>

    <ChainPanel v-if="hops.length" :hops="hops" :trace-id="traceId" />

    <details v-if="raw" class="raw">
      <summary>原始响应</summary>
      <pre class="mono">{{ raw }}</pre>
    </details>
  </main>
</template>
