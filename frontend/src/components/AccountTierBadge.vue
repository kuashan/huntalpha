<script setup>
import { computed } from 'vue'

const props = defineProps({
  tier: { type: String, default: null },
  tierLabel: { type: String, default: null },
  watchlistLimit: { type: [Number, String], default: null },
})

const normalizedTier = computed(() => ['free', 'pro'].includes(props.tier) ? props.tier : null)
const displayLabel = computed(() => ['FREE', 'PRO'].includes(props.tierLabel)
  ? props.tierLabel
  : normalizedTier.value?.toUpperCase() || '')
const title = computed(() => normalizedTier.value
  ? `${displayLabel.value} 计划 · 自选上限：${props.watchlistLimit ?? '—'}`
  : '')
</script>

<template>
  <svg
    v-if="normalizedTier"
    class="account-tier-badge"
    :class="`tier-${normalizedTier}`"
    viewBox="0 0 88 28"
    role="img"
    :aria-label="title"
  >
    <title>{{ title }}</title>
    <defs>
      <linearGradient id="account-tier-free-gradient" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stop-color="#1f568e" />
        <stop offset="1" stop-color="#347fc2" />
      </linearGradient>
      <linearGradient id="account-tier-pro-gradient" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stop-color="#9a6c25" />
        <stop offset="1" stop-color="#d6aa50" />
      </linearGradient>
    </defs>
    <path class="crown" d="M2 5 14 10 24 3l10 7 10-6 10 6 10-7 10 7 12-5-5 18c-18 4-42 4-60 0L2 5Z" />
    <path class="crown-edge" d="m7 20 4 1c19 3 46 3 66 0l4-1" />
    <text x="44" y="19" text-anchor="middle">{{ displayLabel }}</text>
  </svg>
</template>

<style scoped>
.account-tier-badge{display:block;width:68px;height:22px;flex:0 0 auto;overflow:visible}
.crown{stroke-width:1;stroke-linejoin:round}
.crown-edge{fill:none;stroke-width:.8;opacity:.58}
.account-tier-badge text{font:700 9px ui-monospace,monospace;letter-spacing:.08em}
.tier-free .crown{fill:url(#account-tier-free-gradient);stroke:#72a9d6}
.tier-free .crown-edge{stroke:#b7d8f2}
.tier-free text{fill:#f1f8ff}
.tier-pro .crown{fill:url(#account-tier-pro-gradient);stroke:#f0cf83}
.tier-pro .crown-edge{stroke:#fff0bd}
.tier-pro text{fill:#fff8e6}
</style>
