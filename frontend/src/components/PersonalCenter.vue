<script setup>
import { computed, onMounted, ref } from 'vue'
import AccountTierBadge from './AccountTierBadge.vue'

const API_BASE = 'http://127.0.0.1:8003'
const sections = [
  { key: 'overview', label: '概览' },
  { key: 'profile', label: '个人资料' },
  { key: 'membership', label: '会员与 AI 豆' },
  { key: 'security', label: '账户安全' },
  { key: 'preferences', label: '偏好设置' },
]
const priceColorOptions = [
  { value: 'cn', label: '中国市场习惯（涨红跌绿）' },
  { value: 'international', label: '国际市场习惯（涨绿跌红）' },
]
const marketOptions = [
  { value: 'cn', label: '沪深 A 股' },
  { value: 'hk', label: '港股' },
  { value: 'us', label: '美股' },
  { value: 'crypto', label: '加密资产' },
]
const periodOptions = ['1分', '5分', '15分', '30分', '60分', '2小时', '4小时', '日线', '周线', '月线']
const props = defineProps({
  user: { type: Object, required: true },
  section: { type: String, default: 'overview' },
})
const emit = defineEmits(['back', 'section-change', 'logout', 'user-updated', 'preferences-updated'])

const summary = ref(null)
const summaryLoading = ref(false)
const summaryError = ref('')
const profileForm = ref({ display_name: '' })
const profileSaving = ref(false)
const profileMessage = ref('')
const profileError = ref('')
const avatarInput = ref(null)
const avatarSaving = ref(false)
const avatarMessage = ref('')
const avatarError = ref('')
const preferenceForm = ref({ price_color_mode: 'cn', default_market: 'cn', default_period: '日线' })
const preferenceSaving = ref(false)
const preferenceMessage = ref('')
const preferenceError = ref('')
const currentPassword = ref('')
const newPassword = ref('')
const confirmPassword = ref('')
const passwordSaving = ref(false)
const passwordMessage = ref('')
const passwordError = ref('')

const activeSection = computed(() => sections.some(item => item.key === props.section) ? props.section : 'overview')
const activeSectionLabel = computed(() => sections.find(item => item.key === activeSection.value)?.label || '概览')
const identity = computed(() => summary.value?.user || props.user || {})
const membership = computed(() => summary.value?.membership || null)
const aiBeans = computed(() => summary.value?.ai_beans || null)
const watchlist = computed(() => summary.value?.watchlist || null)
const avatarInitial = computed(() => {
  const name = String(identity.value.name || '').trim()
  return name ? Array.from(name)[0].toUpperCase() : '·'
})

function syncSummary(payload) {
  summary.value = payload
  profileForm.value.display_name = payload.user?.name || ''
  if (payload.preferences) preferenceForm.value = { ...preferenceForm.value, ...payload.preferences }
}

function loadSummary() {
  summaryLoading.value = true
  fetch(`${API_BASE}/api/account/summary/`, { credentials: 'include' })
    .then(async reply => {
      const payload = await reply.json()
      if (!reply.ok) throw new Error(payload.error || '账户摘要暂不可用')
      syncSummary(payload)
    })
    .catch(error => { summaryError.value = error.message || '账户摘要暂不可用' })
    .finally(() => { summaryLoading.value = false })
}

function selectSection(key) {
  emit('section-change', key)
}

function readCookie(name) {
  const prefix = `${name}=`
  const value = document.cookie.split('; ').find(item => item.startsWith(prefix))
  return value ? decodeURIComponent(value.slice(prefix.length)) : ''
}

async function csrfToken() {
  let token = readCookie('csrftoken')
  if (!token) {
    const reply = await fetch(`${API_BASE}/api/csrf/`, { credentials: 'include' })
    if (!reply.ok) throw new Error('无法取得安全令牌')
    token = readCookie('csrftoken')
  }
  if (!token) throw new Error('无法取得安全令牌')
  return token
}

async function csrfHeaders() {
  return { 'Content-Type': 'application/json', 'X-CSRFToken': await csrfToken() }
}

async function saveProfile() {
  profileMessage.value = ''; profileError.value = ''; profileSaving.value = true
  try {
    const reply = await fetch(`${API_BASE}/api/account/profile/`, {
      method: 'PATCH', credentials: 'include', headers: await csrfHeaders(),
      body: JSON.stringify({ display_name: profileForm.value.display_name }),
    })
    const payload = await reply.json()
    if (!reply.ok) throw new Error(payload.error || '资料保存失败')
    summary.value = { ...summary.value, user: payload.user }
    profileForm.value.display_name = payload.user.name
    emit('user-updated', payload.user)
    profileMessage.value = '显示名称已更新'
  } catch (error) { profileError.value = error.message || '资料保存失败' }
  finally { profileSaving.value = false }
}

function chooseAvatar() { avatarInput.value?.click() }

async function uploadAvatar(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return
  avatarMessage.value = ''; avatarError.value = ''; avatarSaving.value = true
  try {
    const formData = new FormData(); formData.append('avatar', file)
    const reply = await fetch(`${API_BASE}/api/account/avatar/`, {
      method: 'POST', credentials: 'include', headers: { 'X-CSRFToken': await csrfToken() }, body: formData,
    })
    const payload = await reply.json()
    if (!reply.ok) throw new Error(payload.error || '头像上传失败')
    const nextUser = { ...identity.value, avatar_url: payload.avatar_url }
    summary.value = { ...summary.value, user: nextUser }; emit('user-updated', nextUser)
    avatarMessage.value = '头像已更新'
  } catch (error) { avatarError.value = error.message || '头像上传失败' }
  finally { avatarSaving.value = false }
}

async function deleteAvatar() {
  if (!identity.value.avatar_url || !window.confirm('删除当前头像？')) return
  avatarMessage.value = ''; avatarError.value = ''; avatarSaving.value = true
  try {
    const reply = await fetch(`${API_BASE}/api/account/avatar/`, {
      method: 'DELETE', credentials: 'include', headers: { 'X-CSRFToken': await csrfToken() },
    })
    const payload = await reply.json()
    if (!reply.ok) throw new Error(payload.error || '头像删除失败')
    const nextUser = { ...identity.value, avatar_url: payload.avatar_url }
    summary.value = { ...summary.value, user: nextUser }; emit('user-updated', nextUser)
    avatarMessage.value = '头像已删除'
  } catch (error) { avatarError.value = error.message || '头像删除失败' }
  finally { avatarSaving.value = false }
}

async function savePreferences() {
  preferenceMessage.value = ''; preferenceError.value = ''; preferenceSaving.value = true
  try {
    const reply = await fetch(`${API_BASE}/api/account/preferences/`, {
      method: 'PATCH', credentials: 'include', headers: await csrfHeaders(), body: JSON.stringify(preferenceForm.value),
    })
    const payload = await reply.json()
    if (!reply.ok) throw new Error(payload.error || '偏好保存失败')
    summary.value = { ...summary.value, preferences: payload.preferences, user: payload.user || summary.value.user }
    preferenceForm.value = { ...preferenceForm.value, ...payload.preferences }
    emit('preferences-updated', payload.preferences)
    if (payload.user) emit('user-updated', payload.user)
    preferenceMessage.value = '偏好已保存'
  } catch (error) { preferenceError.value = error.message || '偏好保存失败' }
  finally { preferenceSaving.value = false }
}

async function changePassword() {
  passwordMessage.value = ''
  passwordError.value = ''
  passwordSaving.value = true
  try {
    const headers = await csrfHeaders()
    const reply = await fetch(`${API_BASE}/api/account/change-password/`, {
      method: 'POST', credentials: 'include', headers,
      body: JSON.stringify({ current_password: currentPassword.value, new_password: newPassword.value, confirm_password: confirmPassword.value }),
    })
    const payload = await reply.json()
    if (!reply.ok) throw new Error(payload.error || '密码修改失败')
    currentPassword.value = ''; newPassword.value = ''; confirmPassword.value = ''
    passwordMessage.value = payload.message || '密码已更新'
  } catch (error) {
    passwordError.value = error.message || '密码修改失败'
  } finally {
    passwordSaving.value = false
  }
}

onMounted(loadSummary)
</script>

<template>
  <section class="account-page">
    <header class="account-page-header">
      <div class="account-page-brand"><span class="account-page-mark"><img src="/huntalpha-wolf.svg" alt="" /></span><strong>HuntAlpha</strong><small>HUB</small></div>
      <button type="button" class="back-terminal" @click="emit('back')">返回行情</button>
    </header>

    <div class="account-layout">
      <aside class="account-nav" aria-label="个人中心导航">
        <p>ACCOUNT CENTER</p>
        <button v-for="item in sections" :key="item.key" type="button" :class="{active: activeSection === item.key}" @click="selectSection(item.key)">{{ item.label }}</button>
      </aside>

      <main class="account-content">
        <div class="account-content-heading"><p>HUNTALPHA ACCOUNT</p><h1>{{ activeSectionLabel }}</h1><span v-if="summaryLoading">正在加载账户状态…</span><span v-else-if="summaryError">{{ summaryError }}</span></div>

        <section v-if="activeSection === 'overview'" class="account-panel account-overview">
          <div class="account-hero">
            <div class="hero-avatar">
              <img v-if="identity.avatar_url" :src="identity.avatar_url" alt="" />
              <span v-else>{{ avatarInitial }}</span>
            </div>
            <div class="hero-copy"><h2>{{ identity.name || '—' }}</h2><p>{{ identity.email || '—' }}</p></div>
            <AccountTierBadge :tier="membership?.tier || user.tier" :tier-label="membership?.tier_label || user.tier_label" :watchlist-limit="watchlist?.limit || user.watchlist_limit" :user-name="identity.name" :avatar-url="identity.avatar_url" />
          </div>
          <div class="account-cards">
            <article><small>会员计划</small><strong>{{ membership?.tier_label || '—' }}</strong><span>当前真实账户状态</span></article>
            <article><small>AI 豆</small><strong>{{ aiBeans?.balance ?? '—' }}</strong><span>{{ aiBeans?.status === 'not_enabled' ? '暂未启用' : '暂不可用' }}</span></article>
            <article><small>自选</small><strong>{{ watchlist ? `${watchlist.total} / ${watchlist.limit}` : '—' }}</strong><span>{{ watchlist ? `剩余 ${watchlist.remaining}` : '暂不可用' }}</span></article>
          </div>
        </section>

        <section v-else-if="activeSection === 'profile'" class="account-panel detail-panel">
          <div class="profile-row"><div class="profile-avatar"><img v-if="identity.avatar_url" :src="identity.avatar_url" alt="" /><span v-else>{{ avatarInitial }}</span></div><div><h2>{{ identity.name || '—' }}</h2><p>{{ identity.email || '—' }}</p></div></div>
          <div class="avatar-actions"><input ref="avatarInput" class="visually-hidden" type="file" accept="image/jpeg,image/png,image/webp" @change="uploadAvatar" /><button type="button" @click="chooseAvatar" :disabled="avatarSaving">{{ avatarSaving ? '处理中…' : '上传头像' }}</button><button v-if="identity.avatar_url" type="button" class="subtle-button" @click="deleteAvatar" :disabled="avatarSaving">删除头像</button><small>支持 JPEG、PNG、WebP，最大 5 MB；服务器会统一处理为安全的圆形头像。</small></div>
          <form class="profile-form" @submit.prevent="saveProfile"><label>显示名称<input v-model="profileForm.display_name" maxlength="50" autocomplete="name" required /></label><label>邮箱<input :value="identity.email || '—'" readonly /></label><label>账户等级<input :value="membership?.tier_label || '—'" readonly /></label><button type="submit" :disabled="profileSaving">{{ profileSaving ? '保存中…' : '保存资料' }}</button></form>
          <p v-if="profileMessage" class="form-success">{{ profileMessage }}</p><p v-if="profileError" class="form-error">{{ profileError }}</p><p v-if="avatarMessage" class="form-success">{{ avatarMessage }}</p><p v-if="avatarError" class="form-error">{{ avatarError }}</p>
        </section>

        <section v-else-if="activeSection === 'membership'" class="account-panel detail-panel">
          <div class="membership-block"><small>当前计划</small><strong>{{ membership?.tier_label || '—' }}</strong><p>自选上限：{{ watchlist?.limit ?? '—' }}</p><p v-if="membership?.expires_at">会员到期：{{ membership.expires_at }}</p></div>
          <div class="beans-block"><small>AI 豆余额</small><strong>{{ aiBeans?.balance ?? '—' }}</strong><p>{{ aiBeans?.status === 'not_enabled' ? '暂未启用' : '暂不可用' }}</p><p>AI 豆充值后永久有效，使用 AI 功能时按实际消费扣减。</p></div>
        </section>

        <section v-else-if="activeSection === 'security'" class="account-panel detail-panel">
          <h2>修改密码</h2><p class="panel-note">密码只会通过安全接口提交，不会显示或记录。</p>
          <form class="password-form" @submit.prevent="changePassword"><label>当前密码<input v-model="currentPassword" type="password" autocomplete="current-password" required /></label><label>新密码<input v-model="newPassword" type="password" autocomplete="new-password" required /></label><label>确认新密码<input v-model="confirmPassword" type="password" autocomplete="new-password" required /></label><button type="submit" :disabled="passwordSaving">{{ passwordSaving ? '保存中…' : '保存' }}</button></form>
          <p v-if="passwordMessage" class="form-success">{{ passwordMessage }}</p><p v-if="passwordError" class="form-error">{{ passwordError }}</p>
        </section>

        <section v-else class="account-panel detail-panel">
          <h2>偏好设置</h2><div class="preference-grid"><label class="preference-field">涨跌颜色<select v-model="preferenceForm.price_color_mode"><option v-for="item in priceColorOptions" :key="item.value" :value="item.value">{{ item.label }}</option></select></label><label class="preference-field">默认市场<select v-model="preferenceForm.default_market"><option v-for="item in marketOptions" :key="item.value" :value="item.value">{{ item.label }}</option></select></label><label class="preference-field">默认 K 线周期<select v-model="preferenceForm.default_period"><option v-for="item in periodOptions" :key="item" :value="item">{{ item }}</option></select></label></div><button type="button" class="save-preferences" :disabled="preferenceSaving || !summary" @click="savePreferences">{{ preferenceSaving ? '保存中…' : '保存偏好' }}</button><p v-if="preferenceMessage" class="form-success">{{ preferenceMessage }}</p><p v-if="preferenceError" class="form-error">{{ preferenceError }}</p><p class="panel-note">偏好绑定当前账户，会在下次进入行情时应用默认市场和周期；当前手动选择不会被保存时强行覆盖。</p>
        </section>
      </main>
    </div>
  </section>
</template>

<style scoped>
.account-page{min-height:100vh;background:linear-gradient(135deg,#07111a,#0a1823 60%,#071019);color:#e7f1f5;animation:account-page-in 210ms ease-out}.account-page-header{display:flex;align-items:center;justify-content:space-between;min-height:70px;padding:0 clamp(18px,4vw,60px);border-bottom:1px solid #203747;background:#07131de8}.account-page-brand{display:flex;align-items:center;gap:9px}.account-page-mark{display:grid;place-items:center;width:30px;height:30px}.account-page-mark img{width:30px;height:30px}.account-page-brand strong{font-size:18px;letter-spacing:.01em}.account-page-brand small{padding-left:8px;border-left:1px solid #355064;color:#91a8b7;font:10px 'DM Mono',monospace;letter-spacing:.08em}.back-terminal{padding:8px 12px;border:1px solid #365269;border-radius:5px;background:#0e202e;color:#c2d3dc;cursor:pointer}.back-terminal:hover,.back-terminal:focus-visible{border-color:#5ad5b2;color:#fff;outline:0}.account-layout{display:grid;grid-template-columns:220px minmax(0,1fr);gap:32px;width:min(1240px,calc(100% - 40px));margin:0 auto;padding:34px 0 70px}.account-nav{align-self:start;padding:13px 9px;border:1px solid #203c4d;border-radius:9px;background:#0b1a26}.account-nav p,.account-content-heading p{margin:0;color:#5fd4b0;font:10px 'DM Mono',monospace;letter-spacing:.13em}.account-nav button{display:block;width:100%;margin-top:5px;padding:10px;border:0;border-left:2px solid transparent;border-radius:4px;background:transparent;color:#9fb3bf;text-align:left;cursor:pointer}.account-nav button:hover,.account-nav button.active{border-left-color:#59d5b1;background:#122938;color:#edf7fa}.account-content{min-width:0;max-width:1060px}.account-content-heading{display:flex;align-items:baseline;gap:13px;margin:4px 0 18px}.account-content-heading h1{margin:0;font-size:25px}.account-content-heading>span{color:#7d95a3;font-size:11px}.account-panel{border:1px solid #274456;border-radius:10px;background:#0a1925cc;box-shadow:0 12px 34px #0003;animation:panel-in 200ms ease-out}.account-hero{display:flex;align-items:center;gap:15px;padding:20px 22px;border-bottom:1px solid #213d4d}.hero-avatar,.profile-avatar{display:grid;place-items:center;flex:0 0 64px;width:64px;height:64px;border:1px solid #4f9bca;border-radius:50%;overflow:hidden;background:#102b43;color:#e5f3fc;font:700 23px/1 ui-monospace,monospace}.hero-avatar img,.profile-avatar img{width:100%;height:100%;object-fit:cover}.hero-copy{min-width:0;flex:1}.hero-copy h2{margin:0 0 5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:19px}.hero-copy p{margin:0;color:#8ea7b6;font-size:12px}.account-hero :deep(.account-tier-badge){width:50px;height:46px}.account-cards{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;padding:17px}.account-cards article{display:grid;gap:7px;min-height:100px;padding:14px;border:1px solid #294556;border-radius:7px;background:#0d202d}.account-cards small,.membership-block small,.beans-block small{color:#87a1b1;font-size:11px}.account-cards strong{color:#f0f7fa;font:700 21px 'DM Mono',monospace}.account-cards span{color:#7894a4;font-size:10px}.detail-panel{padding:22px}.profile-row{display:flex;align-items:center;gap:15px;padding-bottom:21px;border-bottom:1px solid #213d4d}.profile-row h2{margin:0 0 5px;font-size:19px}.profile-row p{margin:0;color:#8ea7b6;font-size:12px}.profile-avatar{flex-basis:58px;width:58px;height:58px;font-size:21px}.detail-panel dl{display:grid;gap:0;margin:0}.detail-panel dl div{display:flex;justify-content:space-between;gap:20px;padding:13px 0;border-bottom:1px solid #1d3747;font-size:12px}.detail-panel dt{color:#8ba4b3}.detail-panel dd{margin:0;color:#e6f0f3}.panel-note{margin:18px 0 0;color:#7894a4;font-size:11px;line-height:1.7}.membership-block,.beans-block{padding:18px;border:1px solid #294556;border-radius:7px;background:#0d202d}.beans-block{margin-top:14px}.membership-block strong,.beans-block strong{display:block;margin:8px 0;color:#f0f7fa;font:700 23px 'DM Mono',monospace}.membership-block p,.beans-block p{margin:5px 0;color:#8ca5b3;font-size:12px;line-height:1.6}.password-form{display:grid;max-width:480px;gap:13px;margin-top:18px}.password-form label,.preference-field{display:grid;gap:6px;color:#a8bbc5;font-size:12px}.password-form input,.preference-field select{padding:10px 11px;border:1px solid #355468;border-radius:5px;outline:0;background:#08131c;color:#edf6fa}.password-form input:focus,.preference-field select:focus{border-color:#5ad7b1;box-shadow:0 0 0 3px #42cda21c}.password-form button{justify-self:start;padding:10px 18px;border:0;border-radius:5px;background:#48c99f;color:#061119;font-weight:700;cursor:pointer}.password-form button:disabled{opacity:.6;cursor:wait}.form-success{color:#66d8b4;font-size:12px}.form-error{color:#ff9b8d;font-size:12px}.preference-field{max-width:320px}.preference-field select{margin-top:3px}
@keyframes account-page-in{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}@keyframes panel-in{from{opacity:0;transform:translateY(5px)}to{opacity:1;transform:none}}
@media(max-width:800px){.account-layout{grid-template-columns:1fr;gap:18px;padding-top:22px}.account-nav{display:flex;align-items:center;gap:5px;overflow-x:auto;padding:8px}.account-nav p{display:none}.account-nav button{width:auto;flex:0 0 auto;margin:0;padding:9px 12px;border-left:0;border-bottom:2px solid transparent;white-space:nowrap}.account-nav button:hover,.account-nav button.active{border-left-color:transparent;border-bottom-color:#59d5b1}.account-content-heading{margin-top:0}}
@media(max-width:520px){.account-page-header{min-height:60px;padding:0 14px}.account-page-brand strong{font-size:16px}.account-layout{width:calc(100% - 24px)}.account-content-heading{display:block}.account-content-heading h1{margin-top:6px;font-size:21px}.account-hero{padding:16px;gap:10px}.hero-avatar{flex-basis:54px;width:54px;height:54px;font-size:20px}.hero-copy h2{font-size:16px}.account-hero :deep(.account-tier-badge){width:46px;height:42px}.account-cards{grid-template-columns:1fr;padding:12px}.account-cards article{min-height:0}.detail-panel{padding:16px}}
@media(prefers-reduced-motion:reduce){.account-page,.account-panel{animation:none}}
.avatar-actions{display:flex;align-items:center;flex-wrap:wrap;gap:8px;padding:18px 0;border-bottom:1px solid #1d3747}.avatar-actions button,.profile-form button,.save-preferences{padding:8px 12px;border:1px solid #365269;border-radius:5px;background:#0e202e;color:#c2d3dc;cursor:pointer}.avatar-actions button:hover,.avatar-actions button:focus-visible,.profile-form button:hover,.profile-form button:focus-visible,.save-preferences:hover,.save-preferences:focus-visible{border-color:#5ad5b2;color:#fff;outline:0}.avatar-actions small{flex-basis:100%;color:#7894a4;font-size:11px}.subtle-button{background:transparent!important;color:#a8bbc5!important}.visually-hidden{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}.profile-form{display:grid;max-width:480px;gap:13px;margin-top:18px}.profile-form label{display:grid;gap:6px;color:#a8bbc5;font-size:12px}.profile-form input{padding:10px 11px;border:1px solid #355468;border-radius:5px;outline:0;background:#08131c;color:#edf6fa}.profile-form input:focus{border-color:#5ad7b1;box-shadow:0 0 0 3px #42cda21c}.profile-form button,.save-preferences{justify-self:start;background:#48c99f;border-color:#48c99f;color:#061119;font-weight:700}.profile-form button:disabled,.save-preferences:disabled,.avatar-actions button:disabled{opacity:.6;cursor:wait}.preference-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin-top:18px}.save-preferences{margin-top:20px}
@media(max-width:800px){.preference-grid{grid-template-columns:1fr 1fr}}
@media(max-width:520px){.preference-grid{grid-template-columns:1fr}}
</style>
