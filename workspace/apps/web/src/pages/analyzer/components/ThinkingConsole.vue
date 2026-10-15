<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue';

/**
 * LLM 思考控制台（tasks.md M7.5：「打字机追加 delta」）。
 *
 * <h2>为什么要「打字机」而不是直接 `{{ text }}`</h2>
 * 后端确实会逐条推 `thinking` 增量，但**增量的大小不受我们控制**：
 * LLM 一次吐 40 个字，界面上就是一次性蹦出 40 个字，观感是「卡顿 + 闪现」。
 * 这里把收到的文本放进缓冲，按固定节奏逐字揭示 —— 视觉上连贯，
 * 而且**收到得比显示得快时也不会丢**（`shown` 始终是 `text` 的前缀）。
 *
 * <h2>收尾必须 flush</h2>
 * 流结束时若还在慢慢打字，用户会以为「还没完」。所以 `streaming` 转 false 时
 * 一次性补齐到全文（`flush()`），宁可少一点动效，也不要留下「没写完」的错觉。
 */
const props = defineProps<{
  text: string;
  streaming: boolean;
}>();

/** 已经揭示出来的前缀（永远是 props.text 的前缀）。 */
const shown = ref('');
const scroller = ref<HTMLElement | null>(null);
let timer: ReturnType<typeof setInterval> | null = null;

/** 每 tick 揭示的字符数：剩余越多揭示越快，避免长文要打半分钟。 */
function stepSize(): number {
  const remaining = props.text.length - shown.value.length;
  return Math.max(1, Math.ceil(remaining / 20));
}

function tick(): void {
  if (shown.value.length >= props.text.length) {
    stop();
    return;
  }
  shown.value = props.text.slice(0, shown.value.length + stepSize());
  void scrollToBottom();
}

function start(): void {
  if (timer === null) {
    timer = setInterval(tick, 28);
  }
}

function stop(): void {
  if (timer !== null) {
    clearInterval(timer);
    timer = null;
  }
}

/** 收尾：一次性补齐，并停表。 */
function flush(): void {
  shown.value = props.text;
  stop();
  void scrollToBottom();
}

async function scrollToBottom(): Promise<void> {
  await nextTick();
  const el = scroller.value;
  if (el) {
    el.scrollTop = el.scrollHeight;
  }
}

watch(
  () => props.text,
  (next) => {
    // 重置（新一次分析）时 text 会变短甚至为空 —— 此时不能用前缀假设
    if (!next.startsWith(shown.value)) {
      shown.value = '';
    }
    if (next.length > shown.value.length) {
      start();
    } else {
      flush();
    }
  },
);

watch(
  () => props.streaming,
  (busy) => {
    if (!busy) {
      flush();
    }
  },
);

onBeforeUnmount(stop);
</script>

<template>
  <section class="panel">
    <h2 class="panel__title">
      AI 评审
      <el-tag v-if="props.streaming" class="title-tag" type="primary" size="small" effect="plain">
        生成中
      </el-tag>
    </h2>

    <div ref="scroller" class="console">
      <p v-if="!shown" class="console__empty">
        等待 AI 评审输出…（LLM 不可用时会跳过这一段，但结果照常产出）
      </p>
      <span v-else class="thinking-console">{{ shown }}</span>
      <span v-if="props.streaming && shown" class="console__caret" aria-hidden="true">▌</span>
    </div>
  </section>
</template>
