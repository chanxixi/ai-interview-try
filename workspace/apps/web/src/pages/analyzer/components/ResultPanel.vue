<script setup lang="ts">
import { computed } from 'vue';

import type { AnalyzeResult } from '../../../api/analysis';
import AbilityRadar from './AbilityRadar.vue';
import AdvicePanel from './AdvicePanel.vue';
import IssueList from './IssueList.vue';
import MatchList from './MatchList.vue';
import RecommendList from './RecommendList.vue';
import ScoreRing from './ScoreRing.vue';
import VerdictList from './VerdictList.vue';

/**
 * 结果面板（tasks.md M7.6 / M7.8 + part3 N5）—— 把 `result` 事件的各块摆到一页上。
 *
 * <h2>它只做布局，不做判断</h2>
 * 分数高低、推荐排序、缺口建议全部来自后端。这里唯一「计算」的是
 * `degraded` / `truncated` 的**提示文案** —— 那是把契约字段翻译成人话，
 * 不是业务规则（spec §2.7 的边界）。
 *
 * <h2>part3 的三个新面板怎么「按需出现」</h2>
 * `standard` 模式下后端的响应里**根本没有那四个键**（AC25）。
 * 所以判定依据是 `result.verdicts !== undefined`，而不是「数组是不是空」——
 * 用长度判会把 `deep` 下「真的没有缺口」误判成「没开深分析」。
 *
 * ⚠️ 这也是 N5.3 的验收点：`standard` 响应进来时这些组件**不渲染且不报错**。
 *
 * <h2>为什么降级提示要放在最显眼处</h2>
 * `meta.degraded = true` 意味着「AI 评审这一段是规则模板生成的」。
 * 如果不提示，用户会把模板输出当成 LLM 的判断，对「AI 能力」产生错误印象 ——
 * 这类**静默降级**比报错更危险（AC15 要求 degraded 必须为 true 且结果完整）。
 */
const props = defineProps<{
  result: AnalyzeResult;
}>();

const skills = computed(() => props.result.resume.skills);
const hasSections = computed(() => {
  const s = props.result.resume.sections;
  return s.education.length + s.experience.length + s.projects.length + s.skills.length > 0;
});

/**
 * 本次是不是深分析。
 *
 * 判据是**键存在与否**（契约里 `deep` 必定带这四个键、`standard` 必定不带），
 * 所以这里读 `meta.analysisDepth` 只是补充显示，真正的结构判据是 `verdicts` 有没有。
 */
const isDeep = computed(() => props.result.verdicts !== undefined);
</script>

<template>
  <div class="result">
    <!-- 元信息条：来源 / 降级 / 截断 / 耗时 / traceId —— 一眼看清这次结果的"成色" -->
    <div class="meta-bar">
      <el-tag size="small" effect="plain">
        来源：{{ props.result.meta.source === 'pdf' ? 'PDF' : '文本' }}
      </el-tag>
      <el-tag size="small" effect="plain">耗时 {{ props.result.meta.elapsedMs }} ms</el-tag>
      <el-tag
        v-if="isDeep"
        size="small"
        type="primary"
        effect="plain"
      >
        深度分析 · 判定 {{ props.result.meta.verdictCount ?? 0 }} 条 · 方向
        {{ props.result.meta.directionCount ?? 0 }} 个
      </el-tag>
      <el-tag
        size="small"
        :type="props.result.meta.llmUsed ? 'success' : 'info'"
        effect="plain"
      >
        {{ props.result.meta.llmUsed ? 'LLM 已参与' : 'LLM 未参与（规则模板）' }}
      </el-tag>
      <code class="meta-bar__trace mono">{{ props.result.meta.traceId }}</code>
    </div>

    <el-alert
      v-if="props.result.meta.degraded"
      class="meta-alert"
      type="warning"
      :closable="false"
      show-icon
      title="本次为降级结果"
      description="LLM 不可用，简历诊断由规则模板生成；匹配分与推荐仍为正常计算，不受影响。"
    />

    <el-alert
      v-if="props.result.meta.truncated"
      class="meta-alert"
      type="warning"
      :closable="false"
      show-icon
      title="简历文本过长已截断"
      description="仅分析了前 20000 字，后面的内容未参与匹配。"
    />

    <section class="panel">
      <h2 class="panel__title">简历速览</h2>
      <p v-if="!hasSections" class="panel__note">
        未能切出结构化章节（可能是排版特殊或扫描件）—— 匹配仍按全文技能词进行。
      </p>
      <template v-else>
        <p class="panel__note">归一化技能 {{ skills.length }} 项</p>
        <div class="skill-cloud">
          <el-tag v-for="skill in skills" :key="skill.canonical" size="small" effect="light">
            {{ skill.canonical }}
          </el-tag>
        </div>
      </template>
    </section>

    <!-- 左：分数环（仅当指定了岗位）；右：匹配明细 -->
    <div class="result__match">
      <ScoreRing
        v-if="props.result.match"
        :score="props.result.match.score"
        caption="目标岗位匹配度"
      />
      <MatchList :match="props.result.match" />
    </div>

    <IssueList :issues="props.result.issues" />
    <RecommendList :recommendations="props.result.recommendations" />

    <!-- part3（仅 deep）。三块都是**键存在才渲染** —— standard 下连挂载都不会发生 -->
    <template v-if="isDeep">
      <VerdictList :verdicts="props.result.verdicts ?? []" />
      <AbilityRadar v-if="props.result.abilityProfile" :profile="props.result.abilityProfile" />
      <AdvicePanel
        :improvements="props.result.improvements"
        :directions="props.result.growthDirections"
      />
    </template>
  </div>
</template>
