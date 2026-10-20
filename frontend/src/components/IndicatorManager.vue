<script setup>
import { API_BASE } from '../apiBase'
import { computed, onMounted, onBeforeUnmount, ref } from 'vue'
import { t } from '../i18n'

const props = defineProps({ main: { type: Array, default: () => [] }, sub: { type: Array, default: () => [] }, visitor: Boolean })
const emit = defineEmits(['add', 'remove'])
const visible = ref(false); const items = ref([]); const message = ref('')
const commonItems = computed(() => items.value.filter(item => item.common))
const installedItems = computed(() => items.value.filter(item => !item.common))
const mainItems = computed(() => installedItems.value.filter(item => item.placement === 'main'))
const subItems = computed(() => installedItems.value.filter(item => item.placement === 'sub'))
async function load() { try { const reply = await fetch(`${API_BASE}/api/indicators/`, { credentials: 'include', cache: 'no-store' }); const data = await reply.json(); if (reply.ok) items.value = data.items; else message.value = data.error || '指标库暂不可用。' } catch { message.value = '指标库暂不可用。' } }
function selected(item) { return (item.placement === 'main' ? props.main : props.sub).some(current => current.code === item.code) }
function blocked(item) { return item.allowed === false || (props.visitor && !item.visitor_available) }
function toggle(item) { if (blocked(item)) { message.value = props.visitor ? '访客仅可使用六个基础指标。' : '当前会员等级没有此指标的使用权限。'; return }; if (selected(item)) return emit('remove', item); if (item.placement === 'sub' && props.sub.length >= 3) { message.value = '副图最多同时展示 3 个指标，请先移除一个。'; return } message.value = ''; emit('add', item) }
function closeOnEscape(event) { if (event.key === 'Escape') visible.value = false }
defineExpose({ open: () => { visible.value = true; message.value = ''; load() } })
onMounted(() => { load(); document.addEventListener('keydown', closeOnEscape) })
onBeforeUnmount(() => document.removeEventListener('keydown', closeOnEscape))
</script>
<template>
  <Transition name="indicator-panel"><div v-if="visible" class="drawer-mask" @click.self="visible=false"><aside class="drawer" role="dialog" aria-modal="true" :aria-label="t('indicators')"><header><div><small>INDICATORS</small><b>{{ t('indicators') }}</b><span>{{ visitor ? `${t('visitor')} · ${t('guestAvailable')}` : t('installed') }}</span></div><button type="button" class="drawer-close" aria-label="关闭指标管理" @click="visible=false">×</button></header><p v-if="message" class="message">{{message}}</p><div class="drawer-body"><section><h3>{{ t('common') }} <em>{{ t('guestAvailable') }}</em></h3><div class="quick-grid"><button v-for="item in commonItems" :key="item.code" :class="{selected:selected(item)}" @click="toggle(item)"><b>{{item.code}}</b><small>{{item.name}}</small><span>{{selected(item)?t('remove'):t('add')}}</span></button></div></section><section><h3>{{ t('installedMain') }}</h3><button v-for="item in mainItems" :key="item.code" class="formula-item" :class="{locked:blocked(item),selected:selected(item)}" @click="toggle(item)"><span><b>{{item.name}}</b><small>{{item.code}} · {{ item.engine === 'python' ? '固定公式' : t('privateFormula') }}</small></span><em>{{blocked(item)?t('member'):selected(item)?t('remove'):t('add')}}</em></button><p v-if="!mainItems.length" class="empty">{{ t('noMain') }}</p></section><section><h3>{{ t('installedSub') }} <em>{{sub.length}} / 3</em></h3><button v-for="item in subItems" :key="item.code" class="formula-item" :class="{locked:blocked(item),selected:selected(item)}" @click="toggle(item)"><span><b>{{item.name}}</b><small>{{item.code}} · {{ item.engine === 'python' ? '固定公式' : t('privateFormula') }}</small></span><em>{{blocked(item)?t('member'):selected(item)?t('remove'):t('add')}}</em></button><p v-if="!subItems.length" class="empty">{{ t('noSub') }}</p></section></div><footer>{{ t('protected') }}</footer></aside></div></Transition>
</template>
<style scoped>
.drawer-mask{position:fixed;inset:0;z-index:20;display:flex;justify-content:flex-end;align-items:flex-start;padding:clamp(12px,6vh,62px) clamp(12px,2vw,30px);background:#02060b8c}
.drawer{width:min(360px,100%);max-height:min(80vh,700px);min-height:0;display:flex;flex-direction:column;overflow:hidden;border:1px solid #38546a;border-radius:14px;background:#101d2a;box-shadow:0 24px 70px #000a;color:#e5eff5;transform-origin:top right}
.drawer header{display:flex;justify-content:space-between;align-items:flex-start;padding:18px 19px 14px;border-bottom:1px solid #2a4052}
.drawer header small,.drawer header span{display:block;color:#86a0b3;font:10px 'DM Mono',monospace;letter-spacing:.07em}
.drawer header b{display:block;margin:4px 0;font-size:18px}
.drawer-close{width:31px;height:31px;border:1px solid #365064;border-radius:8px;background:#172a3a;color:#b9cdd9;font-size:22px;cursor:pointer}
.drawer-body{overflow-y:auto;min-height:0;padding:6px 17px 16px;scrollbar-width:thin}
.drawer h3{display:flex;justify-content:space-between;align-items:center;margin:16px 0 10px;color:#e0eaf1;font-size:12px}
.drawer h3 em{font-size:10px;color:#75d8b7;font-style:normal;font-weight:400}
.quick-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}
.quick-grid button,.formula-item{border:1px solid #31495e;border-radius:9px;background:#0b1824;color:#e4edf2;text-align:left;cursor:pointer;transition:border-color 180ms ease,background 180ms ease,transform 180ms ease}
.quick-grid button{min-height:68px;padding:10px 9px}
.quick-grid b,.quick-grid small,.quick-grid span{display:block}.quick-grid b{font:600 12px 'DM Mono',monospace;color:#67d7b5}
.quick-grid small{margin-top:3px;font-size:10px;color:#a6bdca}.quick-grid span{margin-top:6px;color:#7da5be;font-size:10px}
.quick-grid button:hover,.formula-item:hover{border-color:#5f998e;background:#132a34;transform:translateY(-1px)}
.quick-grid button.selected,.formula-item.selected{border-color:#3ca986;background:#112f32}
.formula-item{width:100%;display:flex;justify-content:space-between;align-items:center;gap:12px;margin:7px 0;padding:11px}
.formula-item b,.formula-item small{display:block}.formula-item b{font-size:12px}
.formula-item small{margin-top:3px;color:#8ba5b7;font-size:10px}.formula-item em{flex-shrink:0;color:#76bff2;font-size:10px;font-style:normal}
.formula-item.locked{opacity:.65}.formula-item.locked em{color:#e4b164}.empty,.message{color:#93aabb;font-size:11px}.message{margin:12px 17px 0;color:#ffd27a}
footer{flex:none;padding:11px 17px;border-top:1px solid #293c4e;color:#788fa3;font-size:10px}
.indicator-panel-enter-active,.indicator-panel-leave-active{transition:opacity 200ms ease}
.indicator-panel-enter-active .drawer,.indicator-panel-leave-active .drawer{transition:transform 200ms ease,opacity 200ms ease}
.indicator-panel-enter-from,.indicator-panel-leave-to{opacity:0}
.indicator-panel-enter-from .drawer,.indicator-panel-leave-to .drawer{opacity:0;transform:translateX(14px) scale(.98)}
@media(max-width:520px){.drawer-mask{align-items:flex-end;padding:10px}.drawer{width:100%;max-height:80vh}.quick-grid{gap:6px}}
@media(prefers-reduced-motion:reduce){.indicator-panel-enter-active,.indicator-panel-leave-active,.indicator-panel-enter-active .drawer,.indicator-panel-leave-active .drawer,.quick-grid button,.formula-item{transition:none}}
</style>
