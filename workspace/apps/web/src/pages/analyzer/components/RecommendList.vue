<script setup lang="ts">
import { IMPORTANCE_LABEL, type Recommendation } from '../../../api/analysis';

/**
 * Top-3 岗位推荐（tasks.md M7.7）。
 *
 * <h2>顺序是后端给的，前端**不许重排**</h2>
 * spec §2.7 明确：Vue 禁止自行排序。后端的排序键是 `(-score, jobId)`，
 * 用 jobId 兜底是为了**可复现**（同分时顺序稳定）。前端若按 score 再排一次，
 * 一旦并列就会用数组顺序（不稳定），AC16「两次结果一致」当场失效。
 * 所以这里直接 `v-for`，不排序、不 slice（条数也由后端 `min(3, N)` 决定）。
 *
 * <h2>卡片里只放摘要</h2>
 * 推荐内的 `matched` / `missing` 是**摘要**（不含双向证据），完整证据在
 * `match` 块 —— 这是 spec §2.3 的体积取舍。所以这里只渲染技能名 + 权重标签。
 */
const props = defineProps<{
  recommendations: Recommendation[];
}>();

function rankClass(index: number): string {
  return index === 0 ? 'rec rec--top' : 'rec';
}
</script>

<template>
  <section class="panel">
    <h2 class="panel__title">
      岗位推荐
      <el-tag class="title-tag" size="small" effect="plain">Top {{ props.recommendations.length }}</el-tag>
    </h2>

    <el-empty
      v-if="props.recommendations.length === 0"
      description="暂无推荐（候选集为空，或本次分析未走到推荐阶段）"
      :image-size="72"
    />

    <ol v-else class="rec-list">
      <li v-for="(job, index) in props.recommendations" :key="job.jobId" :class="rankClass(index)">
        <div class="rec__rank">{{ index + 1 }}</div>

        <div class="rec__body">
          <header class="rec__head">
            <h3 class="rec__title">{{ job.title }}</h3>
            <span class="rec__score">{{ job.score }}<small>分</small></span>
          </header>

          <p class="rec__meta">
            <span v-if="job.company">{{ job.company }}</span>
            <span v-if="job.level">· {{ job.level }}</span>
            <code class="rec__id mono">{{ job.jobId }}</code>
          </p>

          <p class="rec__reason">{{ job.reason }}</p>

          <div class="rec__tags">
            <el-tag
              v-for="item in job.matched"
              :key="`hit-${item.skill}`"
              type="success"
              size="small"
              effect="light"
            >
              {{ item.skill }}
            </el-tag>
            <el-tag
              v-for="item in job.missing"
              :key="`gap-${item.skill}`"
              type="info"
              size="small"
              effect="plain"
            >
              {{ item.skill }} · {{ IMPORTANCE_LABEL[item.importance] }}
            </el-tag>
          </div>
        </div>
      </li>
    </ol>
  </section>
</template>
