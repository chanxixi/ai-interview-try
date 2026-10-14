<script setup lang="ts">
import { computed, ref } from 'vue';

import { ApiRequestError, fetchPingChain } from './api/client';
import ChainPanel from './components/ChainPanel.vue';
import { buildChain, type ChainHop } from './utils/chain';

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
      <p class="page__eyebrow">CareerLens · 骨架阶段</p>
      <h1 class="page__title">全链连通性自检</h1>
      <p class="page__desc">
        验证 <strong>Vue → BFF → job-service → analyzer</strong> 四层是否可达、traceId 是否全链贯穿。
        本页只做连通性诊断，简历分析界面在后续阶段接入。
      </p>
    </header>

    <section class="actions">
      <button type="button" class="btn" :disabled="phase === 'loading'" @click="runCheck">
        {{ phase === 'loading' ? '检测中…' : '运行连通性检查' }}
      </button>
      <span
        v-if="phase === 'done'"
        class="actions__hint"
        :class="allReachable ? 'is-ok' : 'is-warn'"
      >
        {{ allReachable ? '四层全部可达' : '存在不可达的跳，见下方详情' }}
      </span>
    </section>

    <p v-if="phase === 'failed' && failure" class="alert">
      <strong>{{ failure.code }}</strong>
      <span>{{ failure.message }}</span>
    </p>

    <ChainPanel v-if="hops.length" :hops="hops" :trace-id="traceId" />

    <details v-if="raw" class="raw">
      <summary>原始响应</summary>
      <pre class="mono">{{ raw }}</pre>
    </details>
  </main>
</template>
