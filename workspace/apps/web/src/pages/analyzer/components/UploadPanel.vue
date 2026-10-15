<script setup lang="ts">
import { computed, ref } from 'vue';
import type { UploadFile, UploadInstance, UploadRawFile } from 'element-plus';

import type { AnalysisInput } from '../../../api/analysis';
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
const props = defineProps<{
  /** 流式进行中：禁用整块面板，避免重复提交 */
  busy: boolean;
}>();

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
      不填 → 只给「Top-3 推荐」；填了 → 额外产出与它的精确匹配分与双向证据。
    </p>
    <el-input
      v-model="jobId"
      placeholder="岗位 ID，例如 job-java-01"
      clearable
      :disabled="props.busy"
    />

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
