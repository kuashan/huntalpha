<script setup>
import { computed } from 'vue'

const props = defineProps({
  tier: { type: String, default: null },
  tierLabel: { type: String, default: null },
  watchlistLimit: { type: [Number, String], default: null },
  userName: { type: String, default: '' },
  avatarUrl: { type: String, default: '' },
})

const normalizedTier = computed(() => ['free', 'pro'].includes(props.tier) ? props.tier : null)
const displayLabel = computed(() => ['FREE', 'PRO'].includes(props.tierLabel)
  ? props.tierLabel
  : normalizedTier.value?.toUpperCase() || '')
const avatarInitial = computed(() => {
  const name = String(props.userName || '').trim()
  return name ? Array.from(name)[0].toUpperCase() : ''
})
const title = computed(() => normalizedTier.value
  ? `${displayLabel.value} 计划 · 自选上限：${props.watchlistLimit ?? '—'}`
  : '')
</script>

<template>
  <svg
    v-if="normalizedTier"
    class="account-tier-badge"
    :class="`tier-${normalizedTier}`"
    viewBox="0 0 54 48"
    role="img"
    :aria-label="title"
  >
    <title>{{ title }}</title>
    <defs>
      <linearGradient id="account-tier-free-crown" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stop-color="#367db9" />
        <stop offset="1" stop-color="#1d4f86" />
      </linearGradient>
      <linearGradient id="account-tier-free-ribbon" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stop-color="#285f99" />
        <stop offset="1" stop-color="#173e6d" />
      </linearGradient>
      <linearGradient id="account-tier-pro-crown" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stop-color="#d5ad5a" />
        <stop offset="1" stop-color="#8f6424" />
      </linearGradient>
      <linearGradient id="account-tier-pro-ribbon" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stop-color="#b88637" />
        <stop offset="1" stop-color="#73501e" />
      </linearGradient>
      <clipPath id="account-tier-avatar-clip">
        <circle cx="27" cy="24" r="13.5" />
      </clipPath>
    </defs>
    <path class="crown" d="M16 10 18 3l7 5 2-7 2 7 7-5 2 7-4 2H20l-4-2Z" />
    <circle class="avatar-circle" cx="27" cy="24" r="13.5" />
    <image v-if="avatarUrl" :href="avatarUrl" x="13.5" y="10.5" width="27" height="27" preserveAspectRatio="xMidYMid slice" clip-path="url(#account-tier-avatar-clip)" />
    <text v-else-if="avatarInitial" class="avatar-initial" x="27" y="28" text-anchor="middle">{{ avatarInitial }}</text>
    <path v-else class="avatar-fallback" d="M22.4 28.2c1-3 2.5-4.5 4.6-4.5s3.6 1.5 4.6 4.5M24.8 20.8a2.4 2.4 0 1 0 4.4 0 2.4 2.4 0 0 0-4.4 0Z" />
    <path class="ribbon-fold ribbon-fold-left" d="M10 36H5l5 5Z" />
    <path class="ribbon-fold ribbon-fold-right" d="M44 36h5l-5 5Z" />
    <path class="ribbon" d="M10 36h34l-3 11H13l-3-11Z" />
    <text class="ribbon-label" x="27" y="44.3" text-anchor="middle">{{ displayLabel }}</text>
  </svg>
</template>

<style scoped>
.account-tier-badge{display:block;width:50px;height:46px;flex:0 0 auto;overflow:visible}
.crown{stroke-width:.8;stroke-linejoin:round}
.avatar-circle{stroke-width:1.2}
.avatar-initial{font:700 11px ui-monospace,monospace}
.avatar-fallback{fill:none;stroke-width:1;stroke-linecap:round}
.ribbon{stroke-width:.7;stroke-linejoin:round}
.ribbon-fold{stroke-width:.6;stroke-linejoin:round}
.ribbon-label{font:700 7px ui-monospace,monospace;letter-spacing:.08em}
.tier-free .crown{fill:url(#account-tier-free-crown);stroke:#75a9d1}
.tier-free .avatar-circle{fill:#0c2039;stroke:#5b9cd0}
.tier-free .avatar-initial,.tier-free .avatar-fallback{fill:#e7f3ff;stroke:#e7f3ff}
.tier-free .ribbon{fill:url(#account-tier-free-ribbon);stroke:#6e9fca}
.tier-free .ribbon-fold{fill:#14385f;stroke:#4d82ae}
.tier-free .ribbon-label{fill:#eff8ff}
.tier-pro .crown{fill:url(#account-tier-pro-crown);stroke:#f0d58e}
.tier-pro .avatar-circle{fill:#2c2417;stroke:#d7b35f}
.tier-pro .avatar-initial,.tier-pro .avatar-fallback{fill:#fff5d9;stroke:#fff5d9}
.tier-pro .ribbon{fill:url(#account-tier-pro-ribbon);stroke:#e0b966}
.tier-pro .ribbon-fold{fill:#62431b;stroke:#b4863a}
.tier-pro .ribbon-label{fill:#fff7df}
</style>
