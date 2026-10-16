<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";

import { fetchCapabilities } from "../../api/client";
import type { AnalysisInput } from "../../api/analysis";
import { toDeepCapability, type CapabilitiesResult } from "../../api/types";
import ResultPanel from "./components/ResultPanel.vue";
import StageProgress from "./components/StageProgress.vue";
import ThinkingConsole from "./components/ThinkingConsole.vue";
import UploadPanel from "./components/UploadPanel.vue";
import { useAnalysisStream } from "./composables/useAnalysisStream";

/**
 * 简历分析页（tasks.md M7.8）。
 *
 * <h2>两栏布局</h2>
 * 左栏 = 输入（上传 + 可选岗位），右栏 = 过程与结果。
 * 把「输入」固定在左、让右栏随流式增长，用户改参数时不用来回滚动 ——
 * 这是流式页面比「提交后跳转」更值得做的理由之一（AC20：全程无白屏）。
 *
 * <h2>状态全部来自一个组合式函数</h2>
 * 页面本身不持有 `fetch` / 分帧逻辑，只做三件事：接事件、传 props、管中止。
 * 好处是 `useAnalysisStream` 可以脱离组件单测（M8.4 的 web 检查项）。
 */
const stream = useAnalysisStream();

/**
 * part3：能力探测结果。`null` = **尚未回来或探测失败**（详情见下方 `deepAvailable`）。
 *
 * 为什么在页面层而不是在 `UploadPanel` 里探测：能力是**页面级事实**（还可能被右栏复用），
 * 组件只管拿到结论后怎么表现。
 */
const capabilities = ref<CapabilitiesResult | null>(null);

onMounted(async () => {
  try {
    capabilities.value = await fetchCapabilities();
  } catch {
    // 探测失败**不阻断**分析页：把它当作「能力未知」而不是「不可用」。
    // 理由：一次网络抖动不该把功能藏起来 —— 真正不可用时后端仍有规则兜底。
    capabilities.value = null;
  }
});

/**
 * 「深度」入口三态（`available` / `unknown` / `unavailable`）—— 见 `api/types.ts`。
 *
 * | 探测结论 | 能否选「深度」 | 默认选中 |
 * |---|---|---|
 * | `available` | ✅ | **`deep`**（有 LLM 就用 LLM） |
 * | `unknown`（未回来 / 探测失败） | ✅（fail-open） | `standard`（不猜） |
 * | `unavailable` | ❌ | `standard` |
 *
 * ⚠️ **接口缺省仍是 `standard`**（spec §2.2 / AC25）。「默认 deep」只发生在这个组件树里 ——
 * 是前端把选项**预置**为 deep，不是改服务端缺省；后端 deep 的规则兜底也一字未动（§2.6 / AC29）。
 */
const deepCapability = computed(() => toDeepCapability(capabilities.value));

const hasOutput = computed(
  () =>
    stream.result.value !== null ||
    stream.error.value !== null ||
    stream.thinking.value !== ""
);

function handleAnalyze(input: AnalysisInput): void {
  void stream.start(input);
}

onBeforeUnmount(() => {
  // 离开页面必须掐掉上游：否则后端会一直跑到 LLM 超时，
  // 白占一个 Java 线程 + 一次 LLM 调用（AC19 关注的正是这类泄漏）
  stream.abort();
});
</script>

<template>
  <main class="analyzer">
    <header class="analyzer__head">
      <p class="page__eyebrow">简历诊断 · 岗位匹配</p>
      <h1 class="page__title">上传简历，实时看它怎么被读、被算、被推荐</h1>
    </header>

    <div class="analyzer__grid">
      <UploadPanel
        :busy="stream.isStreaming.value"
        :deep-capability="deepCapability"
        @analyze="handleAnalyze"
        @cancel="stream.abort()"
      />

      <div class="analyzer__right">
        <StageProgress
          :stages="stream.stages.value"
          :streaming="stream.isStreaming.value"
        />

        <el-alert
          v-if="stream.error.value"
          class="analyzer__error"
          type="error"
          :closable="false"
          show-icon
        >
          <template #title>
            <code class="mono">{{ stream.error.value.code }}</code>
            <span>{{ stream.error.value.message }}</span>
          </template>
          <template v-if="stream.error.value.traceId" #default>
            <span class="mono">traceId: {{ stream.error.value.traceId }}</span>
          </template>
        </el-alert>

        <ThinkingConsole
          v-if="stream.thinking.value || stream.isStreaming.value"
          :text="stream.thinking.value"
          :streaming="stream.isStreaming.value"
        />

        <ResultPanel v-if="stream.result.value" :result="stream.result.value" />

        <el-empty
          v-if="!hasOutput && !stream.isStreaming.value"
          class="analyzer__empty"
          description="提交后：左侧阶段条会逐格推进，这里会实时打出 AI 评审文本，最后给出诊断、匹配与推荐。"
          :image-size="88"
        />
      </div>
    </div>
  </main>
</template>
