<script setup lang="ts">
import type { ChainHop } from '../utils/chain';

defineProps<{ hop: ChainHop }>();
</script>

<template>
  <article class="hop" :class="`hop--${hop.status}`">
    <header class="hop__head">
      <span class="hop__index">{{ hop.index }}</span>
      <span class="hop__service">{{ hop.service }}</span>
      <span class="hop__badge" :class="`hop__badge--${hop.status}`">
        {{ hop.status === 'ok' ? '可达' : '不可达' }}
      </span>
    </header>

    <dl class="hop__meta">
      <div v-if="hop.runtime" class="hop__row">
        <dt>运行时</dt>
        <dd>{{ hop.runtime }}</dd>
      </div>
      <div v-if="hop.version" class="hop__row">
        <dt>版本</dt>
        <dd>{{ hop.version }}</dd>
      </div>
      <div v-if="hop.traceId" class="hop__row">
        <dt>traceId</dt>
        <dd class="mono hop__trace">{{ hop.traceId }}</dd>
      </div>
      <div v-if="hop.error" class="hop__row">
        <dt>错误</dt>
        <dd class="mono">{{ hop.error }}</dd>
      </div>
    </dl>
  </article>
</template>
