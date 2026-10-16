<script setup lang="ts">
import {
  IMPORTANCE_LABEL,
  VERDICT_LABEL,
  VERDICT_TAG_TYPE,
  type Verdict,
} from '../../../api/analysis';

/**
 * 逐条判定面板（part3 N5.1）。
 *
 * <h2>它和「简历诊断」是两件事</h2>
 * | 面板 | 粒度 | 回答 |
 * |---|---|---|
 * | 简历诊断（`issues`） | **逐句** | 这一句哪里要改 |
 * | 逐条判定（`verdicts`） | **逐条要求** | 这个岗位这条要求满足了没 |
 *
 * 两者是「同一件事的两个粒度」（part3 spec §2.5.1），所以**不合并** ——
 * 合并会让用户把同一句话读两遍，也看不出「哪条要求没满足」。
 *
 * <h2>为什么每条都能展开出双向原文</h2>
 * spec §1.1 的真痛点是「判断不可复用」。一条「Redis 缺失」如果点不开看依据，
 * 用户只能选择信或不信；展开双向证据（JD 原文 + 简历原文）之后，
 * 判断才变成可复核的 —— 这正是 AC27 强调「无出处的结论不允许出现」的原因。
 *
 * <h2>重要：这里不重排、不改档</h2>
 * 顺序与档位全部由后端给出（`verdicts` 的顺序 = `match` 的骨架顺序）。
 * 前端连排序都不做（spec §2.7：Vue 只呈现不判断）。
 */
const props = defineProps<{
  verdicts: Verdict[];
}>();

/** 概要：满足 / 部分 / 缺失 各几条。**只是计数**，不改变顺序。 */
function countOf(kind: Verdict['verdict']): number {
  return props.verdicts.filter((item) => item.verdict === kind).length;
}
</script>

<template>
  <section class="panel verdict-panel">
    <h2 class="panel__title">
      逐条判定
      <el-tag class="title-tag" size="small" effect="plain">
        {{ props.verdicts.length }} 条要求
      </el-tag>
      <span class="verdict-panel__hint">AI 判定，仅供参考</span>
    </h2>

    <!-- 计数条：一眼看出「这个岗位我差多少」，而不是先展开 10 条去看 -->
    <div class="verdict-panel__counts">
      <el-tag type="success" size="small" effect="light">满足 {{ countOf('satisfied') }}</el-tag>
      <el-tag type="warning" size="small" effect="light">部分 {{ countOf('partial') }}</el-tag>
      <el-tag type="danger" size="small" effect="light">缺失 {{ countOf('missing') }}</el-tag>
    </div>

    <el-empty
      v-if="props.verdicts.length === 0"
      description="未指定目标岗位，没有可逐条判定的要求"
      :image-size="72"
    />

    <ul v-else class="verdict-list">
      <li v-for="(item, index) in props.verdicts" :key="`${item.skill}-${index}`" class="verdict">
        <header class="verdict__head">
          <el-tag :type="VERDICT_TAG_TYPE[item.verdict]" size="small" effect="dark">
            {{ VERDICT_LABEL[item.verdict] }}
          </el-tag>
          <span class="verdict__skill">{{ item.skill }}</span>
          <el-tag size="small" effect="plain">{{ IMPORTANCE_LABEL[item.importance] }}</el-tag>
        </header>

        <p class="verdict__reason">{{ item.reason }}</p>

        <!-- 出处展开：判断可复核的唯一途径（AC27） -->
        <el-collapse v-if="item.jdEvidence || item.resumeEvidence" class="verdict__evidence">
          <el-collapse-item name="evidence" title="查看依据（JD 原文 / 简历原文）">
            <dl class="evidence-pairs">
              <template v-if="item.jdEvidence">
                <dt>JD 要求</dt>
                <dd>{{ item.jdEvidence }}</dd>
              </template>
              <template v-if="item.resumeEvidence">
                <dt>简历原文</dt>
                <dd>{{ item.resumeEvidence }}</dd>
              </template>
              <template v-else>
                <dt>简历原文</dt>
                <dd class="evidence-pairs__none">（简历中没有对应片段）</dd>
              </template>
            </dl>
          </el-collapse-item>
        </el-collapse>
      </li>
    </ul>
  </section>
</template>
