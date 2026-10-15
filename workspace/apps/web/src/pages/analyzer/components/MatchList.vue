<script setup lang="ts">
import { computed } from 'vue';

import { IMPORTANCE_LABEL, type MatchResult } from '../../../api/analysis';

/**
 * 匹配明细（tasks.md M7.6）。
 *
 * <h2>`match` 为 null 是**正常**分支，不是错误</h2>
 * part2 起 `match` 可空（spec §2.3）：用户没指定 `jobId` / `jdText` 时后端返回 `null`，
 * 此时只产出推荐。所以这里必须先判空再渲染 —— 直接 `match.matched` 会白屏。
 * 「不报错」是 M7.6 的硬要求。
 *
 * <h2>为什么要展开「双向证据」</h2>
 * 后端给每条命中项都带了 `jdEvidence`（JD 原文）与 `resumeEvidence`（简历原文），
 * 这是「可解释」的全部依据（AC5）。折起来默认收起，是因为一次可能有十几条，
 * 全展开会把页面撑得很长；但**必须能展开**，否则和「黑盒打分」没区别。
 */
const props = defineProps<{
  match: MatchResult | null;
}>();

const caption = computed(() =>
  props.match ? `共 ${props.match.matched.length + props.match.missing.length} 项要求` : '',
);

function scoreType(score: number): 'success' | 'warning' | 'danger' {
  if (score >= 80) {
    return 'success';
  }
  return score >= 60 ? 'warning' : 'danger';
}
</script>

<template>
  <section class="panel">
    <h2 class="panel__title">
      岗位匹配
      <el-tag v-if="props.match" class="title-tag" :type="scoreType(props.match.score)" size="small">
        {{ props.match.score }} 分
      </el-tag>
    </h2>

    <el-empty
      v-if="!props.match"
      description="未指定目标岗位 —— 只产出下方推荐（这是预期行为，不是错误）"
      :image-size="72"
    />

    <template v-else>
      <p class="panel__note">{{ caption }}</p>

      <h3 class="sub-title">
        命中 <span class="sub-title__count">{{ props.match.matched.length }}</span>
      </h3>
      <p v-if="props.match.matched.length === 0" class="panel__note">没有命中项。</p>
      <el-collapse v-else>
        <el-collapse-item
          v-for="item in props.match.matched"
          :key="item.skill"
          :name="item.skill"
        >
          <template #title>
            <span class="skill-line">
              <span class="skill-line__name">{{ item.skill }}</span>
              <el-tag
                :type="item.importance === 'required' ? 'danger' : 'info'"
                size="small"
                effect="plain"
              >
                {{ IMPORTANCE_LABEL[item.importance] }}
              </el-tag>
              <span class="skill-line__weight">权重 {{ item.weight }}</span>
            </span>
          </template>
          <div class="evidence">
            <p class="evidence__label">JD 原文</p>
            <blockquote class="evidence__quote">{{ item.jdEvidence }}</blockquote>
            <p class="evidence__label">简历原文</p>
            <blockquote class="evidence__quote">{{ item.resumeEvidence }}</blockquote>
          </div>
        </el-collapse-item>
      </el-collapse>

      <h3 class="sub-title">
        缺口 <span class="sub-title__count">{{ props.match.missing.length }}</span>
      </h3>
      <p v-if="props.match.missing.length === 0" class="panel__note">全部命中，无缺口。</p>
      <ul v-else class="gap-list">
        <li v-for="item in props.match.missing" :key="item.skill" class="gap-list__item">
          <span class="gap-list__skill">{{ item.skill }}</span>
          <el-tag
            :type="item.importance === 'required' ? 'danger' : 'info'"
            size="small"
            effect="plain"
          >
            {{ IMPORTANCE_LABEL[item.importance] }}
          </el-tag>
          <span class="gap-list__tip">{{ item.suggestion }}</span>
        </li>
      </ul>
    </template>
  </section>
</template>
