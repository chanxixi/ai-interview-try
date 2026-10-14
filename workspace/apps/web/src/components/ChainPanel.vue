<script setup lang="ts">
import type { ChainHop } from '../utils/chain';
import HopCard from './HopCard.vue';

const props = defineProps<{
  hops: ChainHop[];
  traceId: string;
}>();
</script>

<template>
  <section class="chain">
    <ol class="chain__hops">
      <li v-for="(hop, index) in props.hops" :key="`${hop.service}-${index}`" class="chain__item">
        <HopCard :hop="hop" />
        <span v-if="index < props.hops.length - 1" class="chain__arrow" aria-hidden="true">→</span>
      </li>
    </ol>

    <p class="chain__trace">
      全链 traceId：<code class="mono">{{ props.traceId }}</code>
    </p>
  </section>
</template>
