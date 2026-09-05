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
    viewBox="0 0 54 42"
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
        <circle cx="27" cy="20" r="8.4" />
      </clipPath>
    </defs>
    <path class="ornament ornament-left" d="M12 18 7 16l2 4-4 2 7-1" />
    <path class="ornament ornament-right" d="m42 18 5-2-2 4 4 2-7-1" />
    <path class="crown" d="M16 10 18 3l7 5 2-7 2 7 7-5 2 7-4 2H20l-4-2Z" />
    <circle class="avatar-ring" cx="27" cy="20" r="10.8" />
    <circle class="avatar-bg" cx="27" cy="20" r="8.4" />
    <image v-if="avatarUrl" :href="avatarUrl" x="18.6" y="11.6" width="16.8" height="16.8" preserveAspectRatio="xMidYMid slice" clip-path="url(#account-tier-avatar-clip)" />
    <text v-else-if="avatarInitial" class="avatar-initial" x="27" y="23.3" text-anchor="middle">{{ avatarInitial }}</text>
    <path v-else class="avatar-fallback" d="M23.5 22.2c.8-2.2 1.9-3.2 3.5-3.2s2.7 1 3.5 3.2M25.2 16.9a1.8 1.8 0 1 0 3.6 0 1.8 1.8 0 0 0-3.6 0Z" />
    <path class="ribbon-fold ribbon-fold-left" d="M10 29H5l5 5Z" />
    <path class="ribbon-fold ribbon-fold-right" d="M44 29h5l-5 5Z" />
    <path class="ribbon" d="M10 29h34l-3 11H13L10 29Z" />
    <text class="ribbon-label" x="27" y="37" text-anchor="middle">{{ displayLabel }}</text>
  </svg>
</template>

<style scoped>
.account-tier-badge{display:block;width:50px;height:40px;flex:0 0 auto;overflow:visible}
.crown{stroke-width:.8;stroke-linejoin:round}
.ornament{fill:none;stroke-width:.8;stroke-linecap:round;stroke-linejoin:round;opacity:.38}
.avatar-ring{stroke-width:1.3}
.avatar-bg{stroke-width:.6}
.avatar-initial{font:700 7px ui-monospace,monospace}
.avatar-fallback{fill:none;stroke-width:.8;stroke-linecap:round}
.ribbon{stroke-width:.7;stroke-linejoin:round}
.ribbon-fold{stroke-width:.6;stroke-linejoin:round}
.ribbon-label{font:700 7px ui-monospace,monospace;letter-spacing:.08em}
.tier-free .crown{fill:url(#account-tier-free-crown);stroke:#75a9d1}
.tier-free .ornament{stroke:#78a9d0}
.tier-free .avatar-ring{fill:#163b64;stroke:#5b9cd0}
.tier-free .avatar-bg{fill:#0c2039;stroke:#376d9d}
.tier-free .avatar-initial,.tier-free .avatar-fallback{fill:#e7f3ff;stroke:#e7f3ff}
.tier-free .ribbon{fill:url(#account-tier-free-ribbon);stroke:#6e9fca}
.tier-free .ribbon-fold{fill:#14385f;stroke:#4d82ae}
.tier-free .ribbon-label{fill:#eff8ff}
.tier-pro .crown{fill:url(#account-tier-pro-crown);stroke:#f0d58e}
.tier-pro .ornament{stroke:#d2aa5a}
.tier-pro .avatar-ring{fill:#5d431d;stroke:#d7b35f}
.tier-pro .avatar-bg{fill:#2c2417;stroke:#94702f}
.tier-pro .avatar-initial,.tier-pro .avatar-fallback{fill:#fff5d9;stroke:#fff5d9}
.tier-pro .ribbon{fill:url(#account-tier-pro-ribbon);stroke:#e0b966}
.tier-pro .ribbon-fold{fill:#62431b;stroke:#b4863a}
.tier-pro .ribbon-label{fill:#fff7df}
</style>
