<script setup lang="ts">
import { ISSUE_TYPE_LABEL, SEVERITY_LABEL, type Issue } from '../../../api/analysis';

/**
 * 简历问题清单（tasks.md M7.6）。
 *
 * <h2>数据的来路要说清</h2>
 * `issues` 是**唯一由 LLM 生成**的内容（其余全部是确定性计算）。
 * LLM 不可用时后端会降级成规则模板产出，此时 `meta.degraded = true` ——
 * 所以这里不需要为「AI 挂了」单独做一个空状态，只要照常渲染即可。
 *
 * <h2>为什么按 severity 排色而不是按类型</h2>
 * 用户关心的是「先改哪个」，不是「属于哪一类」。类型（NO_STAR 等）作为标签展示，
 * 排序与配色交给 severity（后端已按 severity 降序返回）。
 */
const props = defineProps<{
  issues: Issue[];
}>();

function tagType(severity: Issue['severity']): 'danger' | 'warning' | 'info' {
  if (severity === 'high') {
    return 'danger';
  }
  return severity === 'medium' ? 'warning' : 'info';
}
</script>

<template>
  <section class="panel">
    <h2 class="panel__title">
      简历诊断
      <el-tag class="title-tag" size="small" effect="plain">{{ props.issues.length }} 条</el-tag>
    </h2>

    <el-empty v-if="props.issues.length === 0" description="没有发现结构性问题" :image-size="72" />

    <ul v-else class="issue-list">
      <li v-for="(issue, index) in props.issues" :key="`${issue.type}-${index}`" class="issue">
        <header class="issue__head">
          <el-tag :type="tagType(issue.severity)" size="small" effect="dark">
            {{ SEVERITY_LABEL[issue.severity] }}
          </el-tag>
          <span class="issue__type">{{ ISSUE_TYPE_LABEL[issue.type] }}</span>
        </header>
        <blockquote class="issue__evidence">{{ issue.evidence }}</blockquote>
        <p class="issue__suggestion">建议：{{ issue.suggestion }}</p>
      </li>
    </ul>
  </section>
</template>
