<script setup>
import { API_BASE } from '../apiBase'
import { computed, ref } from 'vue'
import { languages, locale, setLocale, t } from '../i18n'
import HuntAlphaLogo from './HuntAlphaLogo.vue'

const emit = defineEmits(['authenticated'])
const registerRequested = new URLSearchParams(window.location.search).get('register') === '1'
const mode = ref(registerRequested ? 'register' : 'login')
const email = ref('')
const password = ref('')
const name = ref('')
const confirm = ref('')
const error = ref('')
const pending = ref(false)
const streams = Array.from({ length: 27 }, (_, index) => ({
  left: `${(index * 3.9 + (index % 4) * 1.4) % 100}%`,
  delay: `${-(index * 0.37)}s`,
  duration: `${7 + (index % 6)}s`,
  code: ['SH.600519', 'HK.00700', 'US.NVDA', 'CC.BTCUSD', 'MACD  DIF  DEA', 'BOLL  MID  UPPER', 'KDJ  K  D  J', 'SZ.300750'][index % 8],
}))
const submitLabel = computed(() => pending.value ? '…' : mode.value === 'login' ? t('enter') : t('create'))
function switchMode(next) { mode.value = next; error.value = '' }
async function submit() {
  error.value = ''
  if (mode.value === 'register' && password.value !== confirm.value) { error.value = '两次输入的密码不一致'; return }
  pending.value = true
  try {
    const endpoint = mode.value === 'login' ? 'login' : 'register'
    const reply = await fetch(`${API_BASE}/api/auth/${endpoint}/`, {
      method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: email.value, password: password.value, name: name.value }),
    })
    const data = await reply.json()
    if (!reply.ok) { error.value = data.error || '暂时无法完成请求'; return }
    emit('authenticated', data.user)
  } catch { error.value = '无法连接网站服务，请稍后重试。' } finally { pending.value = false }
}
async function enterGuest() {
  error.value = ''; pending.value = true
  try {
    const reply = await fetch(`${API_BASE}/api/auth/guest/`, { method: 'POST', credentials: 'include' })
    const data = await reply.json()
    if (!reply.ok) { error.value = data.error || '暂时无法进入访客模式'; return }
    emit('authenticated', { ...data.user, visitor: true })
  } catch { error.value = '无法连接网站服务，请稍后重试。' } finally { pending.value = false }
}
</script>

<template>
  <main class="auth-shell">
    <div class="code-rain" aria-hidden="true"><i v-for="(stream, index) in streams" :key="index" :style="{ left: stream.left, animationDelay: stream.delay, animationDuration: stream.duration }">{{ stream.code }}<br>{{ stream.code }}<br>{{ stream.code }}</i></div>
    <svg class="market-flow" viewBox="0 0 1440 540" preserveAspectRatio="none" aria-hidden="true">
      <path class="grid" d="M0 110H1440M0 220H1440M0 330H1440M0 440H1440" />
      <path class="ma ma-one" d="M0 420 C120 410 145 324 260 346 S420 385 505 292 S700 330 790 242 S1015 266 1100 145 S1310 180 1440 72" />
      <path class="ma ma-two" d="M0 450 C170 440 195 405 305 380 S470 350 570 321 S720 299 825 277 S1010 258 1115 208 S1310 155 1440 120" />
      <path class="ma ma-three" d="M0 468 C170 463 285 446 400 417 S620 390 735 350 S940 330 1055 270 S1280 240 1440 186" />
      <path class="candles green" d="M42 458v-34m-12 12h24v14H30m106-25v-65m-12 29h24v22h-24m116 5v-48m-12 10h24v28h-24m126-14v-57m-12 5h24v31h-24m119-25v-68m-12 10h24v29h-24m117-8v-51m-12 1h24v27h-24m116-10v-64m-12 6h24v35h-24m121-28v-90m-12 23h24v31h-24m119-8v-78m-12 17h24v32h-24m112-14v-91m-12 24h24v35h-24m119-16v-103m-12 29h24v34h-24m120-12v-80m-12 16h24v32h-24" />
      <path class="candles red" d="M78 453v-54m-12 14h24v28H66m124-44v-79m-12 19h24v37h-24m122-19v-92m-12 41h24v25h-24m119-20v-86m-12 31h24v35h-24m117-13v-85m-12 20h24v30h-24m119-11v-73m-12 18h24v31h-24m119-18v-90m-12 23h24v31h-24m118-17v-61m-12 6h24v28h-24m119-21v-70m-12 9h24v32h-24m117-14v-70m-12 4h24v32h-24m115-16v-58m-12 7h24v25h-24m116-20v-60m-12 6h24v27h-24" />
    </svg>
    <header class="auth-header"><div class="auth-brand"><HuntAlphaLogo class="auth-logo" /><span>SiftAlpha</span><small>HUB</small></div><select class="language" :value="locale" @change="setLocale($event.target.value)"><option v-for="item in languages" :key="item.code" :value="item.code">{{ item.label }}</option></select></header>
    <section class="auth-card">
      <p class="eyebrow">PRIVATE RESEARCH ACCESS</p><h1>{{ mode === 'login' ? t('welcome') : t('createAccount') }}</h1><p class="sub">{{ t('research') }}</p>
      <div class="auth-tabs"><button :class="{ active: mode === 'login' }" @click="switchMode('login')">{{ t('login') }}</button><button :class="{ active: mode === 'register' }" @click="switchMode('register')">{{ t('register') }}</button></div>
      <form @submit.prevent="submit"><label v-if="mode === 'register'">{{ t('nickname') }}<input v-model.trim="name" autocomplete="name" /></label><label>{{ t('email') }}<input v-model.trim="email" type="email" autocomplete="email" placeholder="name@example.com" required /></label><label>{{ t('password') }}<input v-model="password" type="password" :autocomplete="mode === 'login' ? 'current-password' : 'new-password'" required /></label><label v-if="mode === 'register'">{{ t('confirm') }}<input v-model="confirm" type="password" autocomplete="new-password" required /></label><p v-if="error" class="auth-error">{{ error }}</p><button class="auth-submit" :disabled="pending">{{ submitLabel }} <span>→</span></button></form>
      <button type="button" class="guest-button" :disabled="pending" @click="enterGuest">{{ t('guest') }} <span>{{ t('guestHint') }}</span></button>
    </section>
    <section class="auth-showcase" aria-label="平台能力预览"><article class="feature visual-preview"><small>01 · 结构识别</small><h2>缠论结构</h2><img src="/login-previews/chanlun-preview.png" alt="缠论结构预览"/><p>笔、线段、中枢和确认信号</p></article><article class="markets-preview"><small>可研究市场</small><div><b>A 股</b><b>美 股</b><b>港 股</b><b>加 密</b></div><p>统一图表、周期与指标工作流</p></article><article class="feature visual-preview"><small>02 · 趋势判断</small><h2>顺势而为</h2><img src="/login-previews/trend-preview.png" alt="顺势而为指标预览"/><p>趋势色带、通道与风险边界</p></article></section>
  </main>
</template>

<style scoped>
.auth-shell{isolation:isolate;position:relative;min-height:100vh;overflow:hidden;color:#e8f1f8;background:radial-gradient(circle at 50% 38%,#15324a 0,transparent 32%),linear-gradient(135deg,#05090f,#0a1824 55%,#061016)}.auth-header{position:relative;z-index:2;display:flex;align-items:center;justify-content:space-between;padding:25px clamp(22px,5vw,74px);color:#8fa8b9;font-size:12px;letter-spacing:.08em}.auth-brand{display:flex;align-items:center;gap:9px;color:#f4f8fb;font-size:18px;font-weight:700;letter-spacing:0}.auth-brand b{display:grid;place-items:center;width:29px;height:29px;background:#57d6ae;color:#061119;clip-path:polygon(50% 0,100% 24%,100% 76%,50% 100%,0 76%,0 24%)}.auth-brand small{padding-left:8px;border-left:1px solid #365064;color:#90a7b5;font-size:10px;font-weight:500}.code-rain{position:absolute;inset:0;z-index:-1;overflow:hidden;mask-image:linear-gradient(to bottom,transparent,black 14%,black 76%,transparent)}.code-rain i{position:absolute;top:-110px;color:#46d5ae;opacity:.18;font:11px/2 'DM Mono',monospace;letter-spacing:.16em;white-space:nowrap;animation:fall linear infinite}.market-flow{position:absolute;z-index:-1;left:0;right:0;bottom:132px;width:100%;height:540px;opacity:.9}.grid{stroke:#2a4a5c;stroke-width:1}.ma{fill:none;stroke-width:2}.ma-one{stroke:#54d9b2}.ma-two{stroke:#e7bd55;opacity:.85}.ma-three{stroke:#e4eef7;opacity:.8}.candles{fill:none;stroke:#4ed4ad;stroke-width:2;opacity:.48}.auth-card{position:relative;z-index:2;width:min(408px,calc(100vw - 36px));margin:48px auto 118px;padding:31px;border:1px solid #3a5869;border-radius:14px;background:linear-gradient(145deg,#102230ed,#09131ded);box-shadow:0 24px 80px #0009;backdrop-filter:blur(14px)}.eyebrow{margin:0;color:#5cd5b2;font:10px 'DM Mono',monospace;letter-spacing:.14em}.auth-card h1{margin:11px 0 6px;font-size:27px}.sub,.privacy{color:#91a8b8;font-size:12px;line-height:1.7}.sub{margin:0}.auth-tabs{display:grid;grid-template-columns:1fr 1fr;margin:23px 0 18px;border-bottom:1px solid #304859}.auth-tabs button{padding:10px;border:0;border-bottom:2px solid transparent;background:transparent;color:#8da3b2}.auth-tabs button.active{border-color:#58d5af;color:#fff}.auth-card form{display:grid;gap:14px}.auth-card label{display:grid;gap:6px;color:#b3c3ce;font-size:12px}.auth-card input{width:100%;padding:11px 12px;border:1px solid #395566;border-radius:5px;outline:0;background:#08131c;color:#edf6fa}.auth-card input:focus{border-color:#5ad7b1;box-shadow:0 0 0 3px #42cda21c}.auth-error{margin:0;color:#ff8891;font-size:12px}.auth-submit{display:flex;justify-content:space-between;align-items:center;margin-top:4px;padding:12px 15px;border:0;border-radius:5px;background:linear-gradient(90deg,#48c99f,#70e2c0);color:#061119;font-weight:700}.auth-submit:disabled{opacity:.6}.auth-submit span{font-size:18px}.privacy{margin:17px 0 0;font-size:10px}.auth-showcase{position:relative;z-index:2;display:grid;grid-template-columns:repeat(3,minmax(0,260px));justify-content:center;gap:14px;padding:0 20px 42px}.feature,.markets-preview{min-height:140px;padding:16px;border:1px solid #304c5d;background:#0a1821cc;backdrop-filter:blur(8px)}.feature small,.markets-preview small{color:#78a1af;font:10px 'DM Mono'}.feature h2{margin:8px 0 5px;font-size:17px}.feature svg{width:100%;height:53px;overflow:visible}.feature svg path{fill:none;stroke:#48d2ad;stroke-width:2}.feature svg .dash{stroke:#7a91a1;stroke-dasharray:4}.feature.dragon svg .band{fill:#1aaab0;opacity:.45;stroke:none}.feature.dragon svg .white{stroke:#f0f4f5}.feature p,.markets-preview p{margin:2px 0;color:#90a6b3;font-size:11px}.markets-preview{display:flex;flex-direction:column;justify-content:center}.markets-preview div{display:grid;grid-template-columns:1fr 1fr;gap:7px;margin:13px 0}.markets-preview b{padding:7px;border:1px solid #315164;background:#102433;color:#d8e9f0;text-align:center;font-size:12px}.markets-preview b:last-child{border-color:#47715e;color:#62d6ad}@keyframes fall{to{transform:translateY(105vh)}}@media(max-width:780px){.auth-header>span{display:none}.auth-card{margin-top:20px;margin-bottom:55px}.auth-showcase{grid-template-columns:1fr;max-width:430px;margin:auto}.market-flow{bottom:390px}.feature,.markets-preview{min-height:120px}}
.guest-button{width:100%;margin-top:10px;padding:9px;border:1px solid #3a5969;border-radius:5px;background:transparent;color:#bed1dc;font-size:12px}.guest-button span{color:#63d8b5;margin-left:4px}.guest-button:disabled{opacity:.6}.candles{stroke-dasharray:2200;stroke-dashoffset:2200;animation:candle-trace 8s ease-in-out infinite}.candles.red{stroke:#f2636c}.candles.green{stroke:#44d6ab}.visual-preview{position:relative;overflow:hidden}.visual-preview img{display:block;width:100%;height:63px;object-fit:cover;object-position:center;margin:7px 0 4px;border:1px solid #2c495d;opacity:.9}.visual-preview p{position:relative}@keyframes candle-trace{0%{stroke-dashoffset:2200;opacity:.15}46%,75%{stroke-dashoffset:0;opacity:.7}100%{stroke-dashoffset:-2200;opacity:.15}}
.auth-brand .auth-logo{width:29px;height:29px}.language{border:1px solid #405a68;border-radius:4px;background:#0d1a24;color:#d8e6ed;padding:6px 8px;font-size:11px;outline:0}
</style>
