<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import AccountTierBadge from './AccountTierBadge.vue'

const API_BASE = 'http://127.0.0.1:8003'
const props = defineProps({
  user: { type: Object, required: true },
  watchlistTotal: { type: Number, default: null },
  watchlistLimit: { type: Number, default: null },
  watchlistRemaining: { type: Number, default: null },
})
const emit = defineEmits(['navigate', 'logout'])

const open = ref(false)
const pinned = ref(false)
const summary = ref(null)
const loading = ref(false)
const summaryLoaded = ref(false)
const summaryError = ref('')
let openTimer
let closeTimer

const identity = computed(() => summary.value?.user || props.user || {})
const membership = computed(() => summary.value?.membership || null)
const aiBeans = computed(() => summary.value?.ai_beans || null)
const watchlist = computed(() => {
  if (props.watchlistTotal !== null && props.watchlistLimit !== null) {
    return {
      total: props.watchlistTotal,
      limit: props.watchlistLimit,
      remaining: props.watchlistRemaining ?? Math.max(props.watchlistLimit - props.watchlistTotal, 0),
    }
  }
  return summary.value?.watchlist || null
})
const avatarInitial = computed(() => {
  const name = String(identity.value.name || '').trim()
  return name ? Array.from(name)[0].toUpperCase() : '·'
})

function clearTimers() {
  window.clearTimeout(openTimer)
  window.clearTimeout(closeTimer)
}

function loadSummary() {
  if (summaryLoaded.value || loading.value) return
  loading.value = true
  summaryError.value = ''
  fetch(`${API_BASE}/api/account/summary/`, { credentials: 'include' })
    .then(async reply => {
      const payload = await reply.json()
      if (!reply.ok) throw new Error(payload.error || '账户摘要暂不可用')
      summary.value = payload
    })
    .catch(error => { summaryError.value = error.message || '账户摘要暂不可用' })
    .finally(() => { loading.value = false; summaryLoaded.value = true })
}

function showPreview() {
  clearTimers()
  if (open.value) return
  openTimer = window.setTimeout(() => { open.value = true; loadSummary() }, 140)
}

function hidePreview() {
  clearTimers()
  if (pinned.value) return
  closeTimer = window.setTimeout(() => { open.value = false }, 180)
}

function toggle() {
  clearTimers()
  if (open.value) {
    pinned.value = !pinned.value
    if (!pinned.value) open.value = false
    return
  }
  pinned.value = true
  open.value = true
  loadSummary()
}

function handleFocus() {
  clearTimers()
  open.value = true
  loadSummary()
}

function close() {
  clearTimers()
  pinned.value = false
  open.value = false
}

function handleOutside(event) {
  if (!event.target.closest('.account-entry')) close()
}

function handleKeydown(event) {
  if (event.key === 'Escape') close()
}

function navigate(section) {
  close()
  emit('navigate', section)
}

function logout() {
  close()
  emit('logout')
}

onMounted(() => {
  document.addEventListener('pointerdown', handleOutside)
  document.addEventListener('keydown', handleKeydown)
})

onBeforeUnmount(() => {
  clearTimers()
  document.removeEventListener('pointerdown', handleOutside)
  document.removeEventListener('keydown', handleKeydown)
})
</script>

<template>
  <div class="account-entry" @mouseenter="showPreview" @mouseleave="hidePreview">
    <button
      type="button"
      class="account-trigger"
      aria-haspopup="dialog"
      :aria-expanded="open"
      aria-label="账户菜单"
      @click="toggle"
      @focus="handleFocus"
    >
      <AccountTierBadge
        :tier="user.tier"
        :tier-label="user.tier_label"
        :watchlist-limit="user.watchlist_limit"
        :user-name="user.name"
        :avatar-url="user.avatar_url"
      />
    </button>

    <Transition name="account-popover">
      <section v-if="open" class="account-popover" role="dialog" aria-label="账户信息" @mouseenter="showPreview" @mouseleave="hidePreview">
        <div class="account-identity">
          <div class="account-avatar" aria-hidden="true">
            <img v-if="identity.avatar_url" :src="identity.avatar_url" alt="" />
            <span v-else>{{ avatarInitial }}</span>
          </div>
          <div class="account-identity-copy">
            <strong>{{ identity.name || '—' }}</strong>
            <small>{{ identity.email || '—' }}</small>
            <span>{{ membership?.tier_label || '—' }}</span>
          </div>
        </div>

        <div class="account-section">
          <div class="account-row"><span>会员计划</span><b>{{ membership?.tier_label || '—' }}</b></div>
          <div v-if="membership?.expires_at" class="account-row"><span>会员到期</span><b>{{ membership.expires_at }}</b></div>
        </div>

        <div class="account-section">
          <div class="account-row"><span>AI 豆余额</span><b>{{ aiBeans?.balance ?? '—' }}</b></div>
          <small class="account-muted">{{ aiBeans?.status === 'not_enabled' ? '暂未启用' : summaryError ? '暂不可用' : '—' }}</small>
          <small class="account-hint">充值后永久有效</small>
        </div>

        <div class="account-section">
          <div class="account-row"><span>自选</span><b>{{ watchlist ? `${watchlist.total} / ${watchlist.limit}` : '—' }}</b></div>
          <small v-if="watchlist" class="account-muted">剩余 {{ watchlist.remaining }}</small>
          <small v-else class="account-muted">{{ summaryError ? '暂不可用' : '—' }}</small>
        </div>

        <small v-if="loading" class="account-loading">正在加载账户状态…</small>
        <small v-if="summaryError" class="account-error">{{ summaryError }}</small>

        <nav class="account-links" aria-label="账户快捷入口">
          <button type="button" @click="navigate('overview')">个人中心 <span>›</span></button>
          <button type="button" @click="navigate('membership')">会员与 AI 豆 <span>›</span></button>
          <button type="button" @click="navigate('security')">账户安全 <span>›</span></button>
          <button type="button" @click="navigate('preferences')">偏好设置 <span>›</span></button>
        </nav>

        <div class="account-logout"><button type="button" @click="logout">退出登录</button></div>
      </section>
    </Transition>
  </div>
</template>

<style scoped>
.account-entry{position:relative;display:flex;align-items:center;flex:0 0 auto}
.account-trigger{display:grid;place-items:center;min-width:56px;min-height:48px;padding:1px 3px;border:1px solid transparent;border-radius:8px;background:transparent;cursor:pointer}
.account-trigger:hover,.account-trigger:focus-visible{border-color:#36546a;background:#102331}.account-trigger:focus-visible{outline:2px solid #59d5b1;outline-offset:2px}
.account-trigger :deep(.account-tier-badge){width:50px;height:46px}
.account-popover{position:absolute;z-index:20;top:calc(100% + 9px);right:0;width:min(340px,calc(100vw - 24px));padding:14px;border:1px solid #30495c;border-radius:10px;background:#0b1824f5;box-shadow:0 18px 48px #0009;color:#e7f0f5;transform-origin:top right;backdrop-filter:blur(12px)}
.account-identity{display:flex;align-items:center;gap:11px;padding-bottom:13px}.account-avatar{display:grid;place-items:center;flex:0 0 42px;width:42px;height:42px;border:1px solid #4d93c6;border-radius:50%;overflow:hidden;background:#102b43;color:#e5f3fc;font:700 16px/1 ui-monospace,monospace}.account-avatar img{width:100%;height:100%;object-fit:cover}.account-identity-copy{display:grid;min-width:0;gap:3px}.account-identity-copy strong{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:14px}.account-identity-copy small{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#8ca4b5;font-size:11px}.account-identity-copy span{color:#65d7b5;font:700 10px/1 'DM Mono',monospace;letter-spacing:.08em}
.account-section{padding:11px 0;border-top:1px solid #233b4e}.account-row{display:flex;align-items:center;justify-content:space-between;gap:12px;font-size:12px}.account-row span{color:#92a8b7}.account-row b{color:#e9f3f7;font:600 12px 'DM Mono',monospace;text-align:right}.account-muted,.account-hint,.account-loading,.account-error{display:block;margin-top:5px;color:#71899b;font-size:10px;line-height:1.5}.account-hint{color:#7fa99f}.account-loading{color:#8db0c0}.account-error{color:#ff9b8d}
.account-links{display:grid;gap:2px;margin:3px -4px 0;padding-top:9px;border-top:1px solid #233b4e}.account-links button,.account-logout button{display:flex;align-items:center;justify-content:space-between;width:100%;padding:8px 7px;border:0;border-radius:5px;background:transparent;color:#c5d6df;text-align:left;font-size:12px;cursor:pointer}.account-links button:hover,.account-links button:focus-visible{background:#142a3a;color:#fff;outline:0}.account-links button span{color:#6b899a;font-size:18px;line-height:12px}.account-logout{margin:8px -4px -4px;padding-top:8px;border-top:1px solid #233b4e}.account-logout button{color:#e39b91}.account-logout button:hover,.account-logout button:focus-visible{background:#321f26;color:#ffb0a6;outline:0}
.account-popover-enter-active,.account-popover-leave-active{transition:opacity 150ms ease,transform 150ms ease}.account-popover-enter-from,.account-popover-leave-to{opacity:0;transform:translateY(-4px) scale(.98)}
@media(max-width:520px){.account-trigger{min-width:50px;min-height:44px}.account-trigger :deep(.account-tier-badge){width:46px;height:42px}.account-popover{position:fixed;top:68px;right:12px;width:min(340px,calc(100vw - 24px));max-height:calc(100vh - 80px);overflow:auto}}
@media(prefers-reduced-motion:reduce){.account-popover-enter-active,.account-popover-leave-active{transition:none}}
</style>
