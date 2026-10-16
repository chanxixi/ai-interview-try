<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import type { UploadFile, UploadInstance, UploadRawFile } from 'element-plus';

import type { AnalysisDepth, AnalysisInput } from '../../../api/analysis';
import type { DeepCapability } from '../../../api/types';
import { MAX_UPLOAD_BYTES, validateResumeFile } from '../../../utils/upload';

/**
 * 上传面板（tasks.md M7.4）。
 *
 * <h2>关键取舍：`auto-upload = false`</h2>
 * `el-upload` 默认会在选中文件后立刻 POST。但本项目的请求是
 * **`POST /api/analysis/stream`（multipart + SSE）**，要同时带上 `jobId` / `jdText`，
 * 且必须由页面统一发起（否则「换文件」会触发两次分析）。
 * 所以关掉自动上传，选中只做**本地校验 + 暂存**，真正的提交交给「开始分析」按钮。
 *
 * <h2>本地校验的定位</h2>
 * 只是体验优化：不合规的文件**根本不发请求**（M7.4 的验收点），
 * 权威判据仍在 BFF。两条判据顺序与后端一致，避免「前端过了后端拦」的割裂感。
 */
const props = withDefaults(
  defineProps<{
    /** 流式进行中：禁用整块面板，避免重复提交 */
    busy: boolean;
    /**
     * 后端能力探测的三态结论（`GET /api/capabilities` → `toDeepCapability`）。
     *
     * **缺省 `unknown`** = 不限制、**不预置 deep**。刻意的 fail-open：探测失败 / 尚未回来时
     * 放行但不猜，否则一次网络抖动要么把「深度」藏起来、要么让用户白等两次 LLM 往返。
     * 真正的最后防线是后端的规则兜底（spec §2.6），不是这里的禁用。
     */
    deepCapability?: DeepCapability;
  }>(),
  { deepCapability: 'unknown' },
);

const emit = defineEmits<{
  analyze: [input: AnalysisInput];
  cancel: [];
}>();

const uploadRef = ref<UploadInstance>();
const pickedFile = ref<File | null>(null);
const localError = ref<string | null>(null);

/** 文本入口 —— 演示时没有 PDF 也能跑通全链（spec §2.2 允许 file / resumeText 二选一） */
const showTextInput = ref(false);
const resumeText = ref('');
/** 目标岗位 ID：不填 → 后端 `match` 为 null，只出推荐（part2 的关键差异） */
const jobId = ref('');

/**
 * part3：分析深度。
 *
 * **缺省必须是 `standard`** —— 它是「老行为一字不变」的可回退开关（AC25），
 * 也是整条链最省时的路径（不额外调两次 LLM）。深度分析要用户**主动选**，
 * 不能默认开启：多两次 LLM 往返是几十秒的差别，不该由系统替用户决定。
 */
const analysisDepth = ref<AnalysisDepth>('standard');

/** 用户是否**亲手**改过深度。改过之后，探测结论不得再覆盖他的选择。 */
const depthTouched = ref(false);

function onDepthChange(): void {
  depthTouched.value = true;
}

/**
 * 能力探测是**异步**的（页面挂载后才回来），所以必须处理「结论晚于用户操作」：
 *
 * | 结论 | 行为 |
 * |---|---|
 * | `unavailable` | 拨回 `standard` —— 按钮禁用却仍停在 `deep` 是**界面说不通**的状态 |
 * | `available` 且用户没选过 | 预置 `deep` ——「有 LLM 就用 LLM」 |
 * | `unknown` | **不动**：探测是优化不是前提，没结论时既不预置 deep，也不把功能藏起来 |
 *
 * ⚠️ 这是**前端预置选项**，不是改服务端缺省 —— 接口缺省仍是 `standard`（spec §2.2 / AC25）。
 */
watch(
  () => props.deepCapability,
  (capability) => {
    if (capability === 'unavailable') {
      if (analysisDepth.value === 'deep') analysisDepth.value = 'standard';
      return;
    }
    if (capability === 'available' && !depthTouched.value) {
      analysisDepth.value = 'deep';
    }
  },
  { immediate: true },
);

/**
 * part3：推荐条数上限。`null` = 不传 → 由后端落回 3（AC17 不被破坏）。
 * 用 `null` 而不是默认填 3，是为了让「缺省」这件事只由后端定义一处。
 */
const topN = ref<number | null>(null);

const hasInput = computed(() => pickedFile.value !== null || resumeText.value.trim().length > 0);

const maxMb = MAX_UPLOAD_BYTES / 1024 / 1024;

/** 选中文件：先本地校验，不通过就**清空选择**（否则用户会以为已经选上了）。 */
async function handleChange(file: UploadFile): Promise<void> {
  localError.value = null;
  const raw = file.raw as UploadRawFile | undefined;
  if (!raw) {
    return;
  }

  const verdict = await validateResumeFile(raw);
  if (!verdict.ok) {
    localError.value = verdict.message ?? '文件不合规';
    pickedFile.value = null;
    // 清掉组件内部列表，保持「界面所见 = 实际会用到的文件」
    uploadRef.value?.clearFiles();
    return;
  }

  pickedFile.value = raw;
}

function handleRemove(): void {
  pickedFile.value = null;
  localError.value = null;
}

/** 超出 1 个文件：直接替换，不弹「只能传一个」的打断式提示。 */
function handleExceed(files: File[]): void {
  uploadRef.value?.clearFiles();
  const next = files[0] as UploadRawFile;
  next.uid = Date.now();
  uploadRef.value?.handleStart(next);
}

function submit(): void {
  if (!hasInput.value || props.busy) {
    return;
  }
  emit('analyze', {
    file: pickedFile.value,
    resumeText: pickedFile.value ? undefined : resumeText.value.trim() || undefined,
    jobId: jobId.value.trim() || undefined,
    analysisDepth: analysisDepth.value,
    topN: typeof topN.value === 'number' ? topN.value : undefined,
  });
}
</script>

<template>
  <section class="panel">
    <h2 class="panel__title">① 上传简历</h2>

    <el-upload
      ref="uploadRef"
      class="analyzer-upload"
      drag
      :auto-upload="false"
      :limit="1"
      :show-file-list="false"
      accept="application/pdf,.pdf"
      :disabled="props.busy"
      :on-change="handleChange"
      :on-remove="handleRemove"
      :on-exceed="handleExceed"
    >
      <div class="upload__body">
        <p class="upload__main">把 PDF 简历拖到这里，或点击选择</p>
        <p class="upload__hint">单个文件 · ≤ {{ maxMb }} MB · 仅文本型 PDF</p>
      </div>
    </el-upload>

    <p v-if="pickedFile" class="picked">
      <span class="picked__name">{{ pickedFile.name }}</span>
      <span class="picked__size">{{ (pickedFile.size / 1024).toFixed(0) }} KB</span>
    </p>

    <el-alert
      v-if="localError"
      class="upload__error"
      type="error"
      :title="localError"
      :closable="false"
      show-icon
    />

    <div class="text-toggle">
      <el-link type="primary" :underline="false" @click="showTextInput = !showTextInput">
        {{ showTextInput ? '收起文本输入' : '没有 PDF？直接粘贴简历文本' }}
      </el-link>
    </div>

    <el-input
      v-if="showTextInput"
      v-model="resumeText"
      type="textarea"
      :rows="6"
      maxlength="20000"
      show-word-limit
      placeholder="粘贴简历正文（≤20000 字）。与 PDF 同时提供时以 PDF 为准。"
      :disabled="props.busy"
    />

    <h2 class="panel__title panel__title--gap">② 目标岗位（可选）</h2>
    <p class="panel__note">
      不填 → 只给「Top-3 推荐」；填了 → 额外产出与它的精确匹配分与双向证据。<br />
      可用岗位：<code>job-backend-01</code> · <code>job-frontend-01</code> ·
      <code>job-algorithm-01</code> · <code>job-devops-01</code> ·
      <code>job-fullstack-01</code> · <code>job-operation-01</code> · <code>job-qa-01</code>
    </p>
    <el-input
      v-model="jobId"
      placeholder="岗位 ID，例如 job-backend-01"
      clearable
      :disabled="props.busy"
    />

    <h2 class="panel__title panel__title--gap">③ 分析深度（可选）</h2>
    <p class="panel__note">
      标准 = part2 的老行为（匹配 + 推荐）；深度会额外产出**逐条判定、优化点、提升方向与六维能力画像**
      —— 代价是多两次 LLM 往返，耗时会明显变长。
    </p>
    <el-radio-group v-model="analysisDepth" :disabled="props.busy" @change="onDepthChange">
      <el-radio-button value="standard">标准</el-radio-button>
      <el-radio-button value="deep" :disabled="props.deepCapability === 'unavailable'"
        >深度</el-radio-button
      >
    </el-radio-group>
    <p
      v-if="props.deepCapability === 'available' && analysisDepth === 'deep' && !depthTouched"
      class="panel__note"
    >
      检测到可用的 LLM，已默认选中「深度」（多两次 LLM 往返，耗时更长）。嫌慢可切回「标准」。
    </p>
    <p v-if="props.deepCapability === 'unavailable'" class="panel__note panel__note--warn">
      当前未检测到可用的 LLM（或分析服务不可达），已自动切到标准分析并禁用「深度」。
      深度分析需要 LLM；未配置时后端虽仍会用规则兜底出结果，但那是降级路径，不该由「深度」入口进入。
    </p>

    <div class="depth-row">
      <span class="depth-row__label">推荐条数上限</span>
      <el-input-number
        v-model="topN"
        :min="1"
        :max="10"
        :disabled="props.busy"
        controls-position="right"
      />
      <span class="depth-row__hint">留空 = 默认 3 个</span>
    </div>

    <div class="submit-row">
      <el-button
        type="primary"
        size="large"
        :disabled="!hasInput"
        :loading="props.busy"
        @click="submit"
      >
        {{ props.busy ? '分析中…' : '开始分析' }}
      </el-button>
      <el-button v-if="props.busy" size="large" @click="emit('cancel')">取消</el-button>
    </div>
  </section>
</template>
