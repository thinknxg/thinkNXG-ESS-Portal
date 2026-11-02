<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { Roster } from "@/services/endpoints";
import { fmtDate, t } from "@/i18n";
import { useUi } from "@/stores/ui";
import { initials } from "@/utils/format";
import PageHeader from "@/components/ui/PageHeader.vue";
import StatusBadge from "@/components/ui/StatusBadge.vue";
import ShiftChip from "@/components/hr/ShiftChip.vue";
import AccessibleDialog from "@/components/ui/AccessibleDialog.vue";
import SegmentTabs from "@/components/ui/SegmentTabs.vue";
import SkeletonLoader from "@/components/ui/SkeletonLoader.vue";
import ErrorState from "@/components/ui/ErrorState.vue";

const route = useRoute();
const router = useRouter();
const ui = useUi();
const name = String(route.params.name);
const g = ref<any>(null);
const loading = ref(true);
const error = ref<any>(null);
const brush = ref<{ kind: "shift" | "rest" | "clear"; shift?: string }>({ kind: "shift" });
const brushLoc = ref("");
const saveState = ref<"idle" | "saving" | "saved" | "error">("idle");
const pending = new Map<string, any>();
let timer: number | undefined;
let painting = false;
const lastClick = ref<{ e: string; i: number } | null>(null);
const active = ref({ r: 0, c: 0 });
const selectedRows = ref<string[]>([]);
const issueTab = ref("rules");
const fDept = ref((route.query.department as string) || "");
const fBranch = ref((route.query.branch as string) || "");
const fText = ref("");
const pastMode = ref(false);
watch([fDept, fBranch], () => router.replace({ query: { ...route.query, department: fDept.value || undefined, branch: fBranch.value || undefined } }));

async function load() {
  loading.value = true;
  try {
    g.value = await Roster.get(name);
    if (!brush.value.shift) brush.value = { kind: "shift", shift: g.value.used_shift_types[0] || g.value.shift_types[0]?.name };
  } catch (e: any) { error.value = e; } finally { loading.value = false; }
}
onMounted(() => { load(); window.addEventListener("pointerup", stopPaint); });
onBeforeUnmount(() => { window.removeEventListener("pointerup", stopPaint); if (pending.size) flush(); });

const types = computed<Record<string, any>>(() => Object.fromEntries((g.value?.shift_types || []).map((x: any) => [x.name, x])));
const dates = computed<string[]>(() => g.value?.dates || []);
const allEmps = computed<any[]>(() => g.value?.employees || []);
const depts = computed(() => [...new Set(allEmps.value.map((e) => e.department).filter(Boolean))].sort() as string[]);
const branches = computed(() => [...new Set(allEmps.value.map((e) => e.branch).filter(Boolean))].sort() as string[]);
const filtered = computed(() => !!(fDept.value || fBranch.value || fText.value.trim()));
const emps = computed<any[]>(() => {
  const q = fText.value.trim().toLowerCase();
  return allEmps.value.filter((e) => (!fDept.value || e.department === fDept.value) && (!fBranch.value || e.branch === fBranch.value)
    && (!q || `${e.employee_name} ${e.name} ${e.designation || ""}`.toLowerCase().includes(q)));
});
const archived = computed(() => g.value?.roster.status === "Archived");
const pastEditable = (d: string) => !!g.value?.can_backdate && pastMode.value && !!g.value.backdate_from && d >= g.value.backdate_from;
const locked = (d: string) => archived.value || (g.value?.roster.status === "Published" && d < g.value.today && !pastEditable(d));
const isWO = (e: string, d: string) => !!g.value?.holidays?.[e]?.[d]?.weekly_off;
const hasPastWindow = computed(() => !!g.value?.can_backdate && !!g.value.backdate_from && g.value.roster.from_date < g.value.today && g.value.roster.to_date >= g.value.backdate_from);
const weekend = (d: string) => (g.value?.weekend_days || []).includes(new Date(`${d}T00:00:00`).toLocaleDateString("en-GB", { weekday: "long" }));
const cell = (e: string, d: string) => g.value?.cells?.[e]?.[d] || null;

function apply(e: string, d: string) {
  if (locked(d)) return;
  const b = brush.value;
  const next = b.kind === "shift" ? { s: b.shift, l: brushLoc.value || null, r: 0, w: 0 } : b.kind === "rest" ? { s: null, l: null, r: 1, w: isWO(e, d) ? 1 : 0 } : { s: null, l: null, r: 0, w: 0 };
  const cur = cell(e, d);
  if (cur && (cur.s || null) === next.s && (cur.r || 0) === next.r && (cur.l || null) === next.l) return;
  if (!g.value.cells[e]) g.value.cells[e] = {};
  g.value.cells[e][d] = { ...(cur || {}), ...next };
  pending.set(`${e}|${d}`, { employee: e, date: d, shift_type: next.s, shift_location: next.l, rest: next.r, note: cur?.n || null });
  saveState.value = "saving";
  window.clearTimeout(timer);
  timer = window.setTimeout(flush, 700);
}
async function flush() {
  if (!pending.size) return;
  const cells = [...pending.values()];
  pending.clear();
  try {
    const r: any = await Roster.saveCells(name, cells);
    g.value.validation = r.validation;
    if (r.saved && g.value.roster.status === "Published") g.value.roster.has_unpublished_changes = 1;
    if (r.locked) ui.toast(`${r.locked} past day(s) can't be changed${g.value.can_backdate ? " outside the allowed window" : " after publishing"}.`, "info");
    saveState.value = pending.size ? "saving" : "saved";
  } catch (e: any) { saveState.value = "error"; ui.toast(e.message, "error"); load(); }
}
function down(e: string, i: number, ev: PointerEvent) {
  active.value = { r: emps.value.findIndex((x) => x.name === e), c: i };
  if (ev.shiftKey && lastClick.value?.e === e) {
    const [a, b] = [Math.min(lastClick.value.i, i), Math.max(lastClick.value.i, i)];
    for (let k = a; k <= b; k++) apply(e, dates.value[k]);
  } else { apply(e, dates.value[i]); painting = ev.pointerType === "mouse"; }
  lastClick.value = { e, i };
}
function enter(e: string, i: number) { if (painting) apply(e, dates.value[i]); }
function stopPaint() { painting = false; }

function focusCell(r: number, c: number) {
  active.value = { r: Math.max(0, Math.min(r, emps.value.length - 1)), c: Math.max(0, Math.min(c, dates.value.length - 1)) };
  nextTick(() => document.getElementById(`c-${active.value.r}-${active.value.c}`)?.focus());
}
function key(ev: KeyboardEvent) {
  const { r, c } = active.value;
  const e = emps.value[r]?.name;
  const d = dates.value[c];
  const moves: Record<string, [number, number]> = { ArrowRight: [0, 1], ArrowLeft: [0, -1], ArrowDown: [1, 0], ArrowUp: [-1, 0] };
  if (moves[ev.key]) {
    ev.preventDefault();
    const rtl = document.documentElement.dir === "rtl" && ev.key.startsWith("Arrow") && ["ArrowRight", "ArrowLeft"].includes(ev.key) ? -1 : 1;
    focusCell(r + moves[ev.key][0], c + moves[ev.key][1] * rtl);
    return;
  }
  if (!e || !d) return;
  if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); apply(e, d); focusCell(r, c + 1); return; }
  if (ev.key === "Delete" || ev.key === "Backspace") { ev.preventDefault(); const keep = brush.value; brush.value = { kind: "clear" }; apply(e, d); brush.value = keep; return; }
  const k = ev.key.toUpperCase();
  const st = (g.value.shift_types as any[]).find((x) => x.code.toUpperCase().startsWith(k));
  if (st && k.length === 1) { ev.preventDefault(); brush.value = { kind: "shift", shift: st.name }; apply(e, d); focusCell(r, c + 1); }
  else if (k === "R" || k === "-") { ev.preventDefault(); brush.value = { kind: "rest" }; apply(e, d); focusCell(r, c + 1); }
}

const issueAt = computed(() => {
  const m: Record<string, string[]> = {};
  for (const v of g.value?.validation?.violations || []) (m[`${v.employee}|${v.date}`] ||= []).push(v.message);
  for (const v of g.value?.validation?.conflicts || []) if (v.employee && v.date) (m[`${v.employee}|${v.date}`] ||= []).push(v.message);
  return m;
});
const gapAt = computed(() => new Set(filtered.value ? [] : (g.value?.validation?.gaps || []).map((x: any) => `${x.shift_type}|${x.date}`)));
const shownTypes = computed(() => {
  const used = new Set<string>([...(g.value?.used_shift_types || [])]);
  for (const e of emps.value) for (const d of dates.value) { const c = cell(e.name, d); if (c?.s) used.add(c.s); }
  return (g.value?.shift_types || []).filter((x: any) => used.has(x.name));
});
function countFor(st: string, d: string) { return emps.value.reduce((n, e) => n + (cell(e.name, d)?.s === st ? 1 : 0), 0); }
function hoursFor(e: string) { let h = 0, n = 0; for (const d of dates.value) { const c = cell(e, d); if (c?.s) { n++; h += types.value[c.s]?.hours || 0; } } return { n, h: Math.round(h) }; }
function cellLabel(e: any, d: string) {
  const c = cell(e.name, d); const lv = g.value.leaves[e.name]?.[d]; const hol = g.value.holidays[e.name]?.[d];
  return `${e.employee_name}, ${fmtDate(d, { weekday: "long", day: "numeric", month: "short" })}: ${c?.s ? c.s : c?.r ? (c.w ? "weekly off" : "rest day") : isWO(e.name, d) ? "not planned, weekly off" : "not planned"}${lv ? `, ${lv.leave_type} ${lv.status}` : ""}${hol && !hol.weekly_off ? `, ${hol.description}` : ""}`;
}
const leaveAbbr = (lt: string) => initials(lt).slice(0, 2);

// ---- dialogs
const pubOpen = ref(false); const trim = ref(false); const backfill = ref(false); const report = ref<any>(null); const busy = ref(false);
async function publish() {
  busy.value = true;
  try { await flush(); report.value = await Roster.publish(name, trim.value ? 1 : 0, backfill.value ? 1 : 0); ui.toast("Roster published"); await load(); }
  catch (e: any) { ui.toast(e.message, "error"); } finally { busy.value = false; }
}
const blockers = computed(() => (g.value?.validation?.conflicts || []).filter((c: any) => c.severity === "blocker"));

const patOpen = ref(false);
const pat = ref<any>({ pattern: "", start: "", end: "", stagger: 0, employees: [] as string[], newName: "", steps: [] as (string | null)[], location: "", keepWO: true });
function openPattern() {
  pat.value = { pattern: g.value.patterns[0]?.name || "", start: g.value.roster.status === "Published" && g.value.today > dates.value[0] ? g.value.today : dates.value[0], end: dates.value[dates.value.length - 1],
    stagger: 0, employees: selectedRows.value.length ? [...selectedRows.value] : emps.value.map((e) => e.name), newName: "", steps: [], location: "", keepWO: g.value.auto_weekly_off };
  patOpen.value = true;
}
async function savePattern() {
  if (!pat.value.newName || !pat.value.steps.length) return;
  await Roster.savePattern({ pattern_name: pat.value.newName, steps: pat.value.steps });
  await load(); pat.value.pattern = pat.value.newName; pat.value.newName = ""; pat.value.steps = [];
}
async function applyPattern() {
  busy.value = true;
  try { await flush(); g.value = await Roster.applyPattern({ name, pattern: pat.value.pattern, employees: pat.value.employees, start_date: pat.value.start, end_date: pat.value.end, stagger: pat.value.stagger, shift_location: pat.value.location || null, keep_weekly_offs: pat.value.keepWO ? 1 : 0 }); patOpen.value = false; }
  catch (e: any) { ui.toast(e.message, "error"); } finally { busy.value = false; }
}
const patSteps = computed(() => g.value?.patterns.find((p: any) => p.name === pat.value.pattern)?.steps || []);

const copyOpen = ref(false); const sources = ref<any[]>([]); const source = ref(""); const copyKeepWO = ref(true);
async function openCopy() { sources.value = (await Roster.list()).filter((r: any) => r.name !== name); source.value = sources.value[0]?.name || ""; copyOpen.value = true; }
async function doCopy() { busy.value = true; try { await flush(); g.value = await Roster.copyFrom(name, source.value, copyKeepWO.value ? 1 : 0); copyOpen.value = false; } catch (e: any) { ui.toast(e.message, "error"); } finally { busy.value = false; } }

const reqOpen = ref(false); const reqs = ref<any[]>([]);
function openReqs() { reqs.value = (g.value.requirements || []).map((r: any) => ({ ...r })); if (!reqs.value.length) reqs.value.push({ shift_type: shownTypes.value[0]?.name || "", weekday: "All days", min_staff: 1 }); reqOpen.value = true; }
async function saveReqs() { busy.value = true; try { g.value = await Roster.setRequirements(name, reqs.value); reqOpen.value = false; } catch (e: any) { ui.toast(e.message, "error"); } finally { busy.value = false; } }

const addOpen = ref(false); const team = ref<any[]>([]); const toAdd = ref<string[]>([]); const addDept = ref(""); const addBranch = ref("");
async function openAdd() { const all = await Roster.teamMembers(); const have = new Set(allEmps.value.map((e) => e.name)); team.value = all.filter((x: any) => !have.has(x.name)); toAdd.value = []; addDept.value = fDept.value; addBranch.value = fBranch.value; addOpen.value = true; }
const teamShown = computed(() => team.value.filter((x) => (!addDept.value || x.department === addDept.value) && (!addBranch.value || x.branch === addBranch.value)));
const teamDepts = computed(() => [...new Set(team.value.map((x) => x.department).filter(Boolean))].sort() as string[]);
const teamBranches = computed(() => [...new Set(team.value.map((x) => x.branch).filter(Boolean))].sort() as string[]);

// weekly offs
const woOpen = ref(false); const woScope = ref("shown"); const woOverwrite = ref(false); const woResult = ref<any>(null);
async function applyWeeklyOffs() {
  busy.value = true;
  try {
    await flush();
    const employees = woScope.value === "all" ? null : woScope.value === "selected" ? selectedRows.value : emps.value.map((e) => e.name);
    const r: any = await Roster.markWeeklyOffs(name, employees, woOverwrite.value ? 1 : 0);
    g.value = r.grid; woResult.value = r; woOpen.value = false;
    ui.toast(`${r.saved} weekly off(s) marked${r.kept_shifts ? `, ${r.kept_shifts} planned shift(s) kept` : ""}${r.locked ? `, ${r.locked} locked past day(s) skipped` : ""}`);
  } catch (e: any) { ui.toast(e.message, "error"); } finally { busy.value = false; }
}
async function doAdd() { busy.value = true; try { await Roster.addEmployees(name, toAdd.value); addOpen.value = false; await load(); } catch (e: any) { ui.toast(e.message, "error"); } finally { busy.value = false; } }
async function removeRow(e: any) { if (!confirm(`Remove ${e.employee_name} from this roster?`)) return; await Roster.removeEmployee(name, e.name); await load(); }
async function archive() { if (!confirm("Archive this roster? Published shift assignments stay in thinkNXG HR.")) return; await Roster.archive(name); await load(); }
const WEEKDAYS = ["All days", "Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
function goTo(emp?: string, d?: string) { if (!emp || !d) return; const r = emps.value.findIndex((x) => x.name === emp); const c = dates.value.indexOf(d); if (r >= 0 && c >= 0) focusCell(r, c); }
</script>

<template>
  <div class="page wide">
    <ErrorState :error="error" @retry="load" />
    <SkeletonLoader v-if="loading && !g" :lines="10" :height="28" />
    <template v-if="g">
      <PageHeader :title="g.roster.title" :subtitle="`${fmtDate(g.roster.from_date, { day: 'numeric', month: 'short' })} – ${fmtDate(g.roster.to_date)} · ${emps.length} people`" back="/team/roster">
        <StatusBadge :tone="g.roster.status === 'Published' ? 'ok' : g.roster.status === 'Draft' ? 'warn' : 'muted'" :label="g.roster.status + (g.roster.version ? ` v${g.roster.version}` : '')" />
        <StatusBadge v-if="g.roster.has_unpublished_changes" tone="warn" label="Unpublished changes" />
        <button v-if="!archived" class="btn primary" @click="report = null; trim = false; pubOpen = true">{{ g.roster.status === "Published" ? "Republish" : "Publish" }}</button>
      </PageHeader>

      <div class="filters">
        <select class="select" v-model="fDept" aria-label="Department"><option value="">All departments</option><option v-for="d in depts" :key="d" :value="d">{{ d }}</option></select>
        <select class="select" v-model="fBranch" aria-label="Branch"><option value="">All branches</option><option v-for="b in branches" :key="b" :value="b">{{ b }}</option></select>
        <input class="input" v-model="fText" placeholder="Find a person" aria-label="Find a person" />
        <span class="small muted shown">{{ emps.length }} of {{ allEmps.length }} people</span>
        <label v-if="hasPastWindow && !archived" class="check past-toggle" :class="{ on: pastMode }"><input type="checkbox" v-model="pastMode" />Edit past days from {{ fmtDate(g.backdate_from > g.roster.from_date ? g.backdate_from : g.roster.from_date, { day: "numeric", month: "short" }) }}</label>
      </div>

      <div class="toolbar" v-if="!archived">
        <div class="brushes" role="radiogroup" aria-label="Paint with">
          <button v-for="st in g.shift_types" :key="st.name" role="radio" :aria-checked="brush.kind === 'shift' && brush.shift === st.name" class="brush"
                  :class="{ on: brush.kind === 'shift' && brush.shift === st.name }" @click="brush = { kind: 'shift', shift: st.name }" :title="`${st.name} ${st.start}–${st.end} (key ${st.code})`">
            <ShiftChip :code="st.code" :color="st.color" size="sm" /><span class="bn">{{ st.name }}</span><span class="bt num">{{ st.start }}–{{ st.end }}</span></button>
          <button role="radio" :aria-checked="brush.kind === 'rest'" class="brush" :class="{ on: brush.kind === 'rest' }" @click="brush = { kind: 'rest' }"><ShiftChip rest size="sm" /><span class="bn">Rest day</span></button>
          <button role="radio" :aria-checked="brush.kind === 'clear'" class="brush" :class="{ on: brush.kind === 'clear' }" @click="brush = { kind: 'clear' }"><span class="eraser">×</span><span class="bn">Clear</span></button>
        </div>
        <div class="tools">
          <select v-if="g.locations.length && brush.kind === 'shift'" class="select sm-sel" v-model="brushLoc" aria-label="Shift location"><option value="">Location from Shift Type</option><option v-for="l in g.locations" :key="l.name" :value="l.name">{{ l.location_name || l.name }}</option></select>
          <button class="btn sm" @click="openPattern">Apply pattern</button>
          <button class="btn sm" @click="openCopy">Copy roster</button>
          <button class="btn sm" @click="openReqs">Coverage needs</button>
          <button class="btn sm" @click="woResult = null; woOpen = true">Weekly offs</button>
          <button class="btn sm" @click="openAdd">Add people</button>
          <span class="save small" :class="saveState" role="status">{{ saveState === "saving" ? "Saving…" : saveState === "saved" ? "Saved" : saveState === "error" ? "Not saved" : "" }}</span>
        </div>
        <p class="small muted hint">Click or drag across cells to paint. Shift-click fills a range. Keyboard: arrows move, a shift's code paints it, R for rest, Delete clears. Rest on a holiday-list weekly off shows as W.</p>
      </div>

      <div class="grid-wrap" @keydown="key">
        <table class="grid" role="grid" :aria-label="`${g.roster.title} roster`">
          <thead>
            <tr>
              <th class="sticky corner" scope="col">Employee</th>
              <th v-for="d in dates" :key="d" scope="col" :class="{ wk: weekend(d), today: d === g.today, past: locked(d), pastedit: d < g.today && pastEditable(d) }">
                <span class="wd">{{ fmtDate(d, { weekday: "narrow" }) }}</span><span class="dn num">{{ +d.slice(8) }}</span>
                <span v-if="d.slice(8) === '01' || d === dates[0]" class="mo">{{ fmtDate(d, { month: "short" }) }}</span></th>
              <th scope="col" class="tot">Shifts · h</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(e, r) in emps" :key="e.name">
              <th class="sticky emp" scope="row">
                <label class="sel"><input type="checkbox" :value="e.name" v-model="selectedRows" :aria-label="`Select ${e.employee_name}`" /></label>
                <span class="en"><span class="title">{{ e.employee_name }}</span><span class="small muted">{{ e.designation || e.name }}</span></span>
                <button v-if="!archived" class="rm" @click="removeRow(e)" :aria-label="`Remove ${e.employee_name}`">×</button>
              </th>
              <td v-for="(d, i) in dates" :key="d" :class="{ wk: weekend(d), today: d === g.today }">
                <button :id="`c-${r}-${i}`" class="cell" :tabindex="active.r === r && active.c === i ? 0 : -1" :disabled="locked(d) && !cell(e.name, d)"
                        :class="{ locked: locked(d), pastedit: d < g.today && pastEditable(d), issue: issueAt[`${e.name}|${d}`], leave: g.leaves[e.name]?.[d], hol: g.holidays[e.name]?.[d] && !g.holidays[e.name][d].weekly_off }"
                        :aria-label="cellLabel(e, d)" :title="issueAt[`${e.name}|${d}`]?.join('\n')"
                        @pointerdown.prevent="down(e.name, i, $event)" @pointerenter="enter(e.name, i)" @focus="active = { r, c: i }">
                  <ShiftChip v-if="cell(e.name, d)?.s" :code="types[cell(e.name, d).s]?.code" :color="types[cell(e.name, d).s]?.color" size="sm" />
                  <ShiftChip v-else-if="cell(e.name, d)?.r" rest :code="cell(e.name, d).w ? 'W' : ''" size="sm" :class="{ wo: cell(e.name, d).w }" />
                  <span v-else class="empty" :class="{ wohint: isWO(e.name, d) }">{{ isWO(e.name, d) ? "w" : "·" }}</span>
                  <i v-if="g.leaves[e.name]?.[d]" class="lv">{{ leaveAbbr(g.leaves[e.name][d].leave_type) }}</i>
                </button>
              </td>
              <td class="tot num">{{ hoursFor(e.name).n }} · {{ hoursFor(e.name).h }}</td>
            </tr>
          </tbody>
          <tfoot>
            <tr v-for="st in shownTypes" :key="st.name">
              <th class="sticky emp cov" scope="row"><ShiftChip :code="st.code" :color="st.color" size="sm" :label="st.name" /></th>
              <td v-for="d in dates" :key="d" class="num c" :class="{ short: gapAt.has(`${st.name}|${d}`), wk: weekend(d) }">{{ countFor(st.name, d) || "" }}</td>
              <td />
            </tr>
          </tfoot>
        </table>
      </div>
      <p v-if="filtered" class="small muted">Coverage counts include only the {{ emps.length }} people shown. Clear the filters to check coverage needs.</p>
      <p class="legend small muted"><span><ShiftChip rest code="W" size="sm" /> Weekly off</span><span><i class="k lvk" />On leave</span><span><i class="k holk" />Public holiday</span><span><i class="k isk" />Rule issue</span><span><i class="k shk" />Coverage below need</span></p>

      <section class="panel">
        <header><h2>Checks</h2>
          <span class="small muted">{{ g.validation.summary.errors }} blocking · {{ g.validation.summary.warnings }} warnings · {{ g.validation.summary.gaps }} coverage gaps</span></header>
        <SegmentTabs v-model="issueTab" :tabs="[{ value: 'rules', label: 'Working-time rules', count: g.validation.violations.length }, { value: 'gaps', label: 'Coverage', count: g.validation.gaps.length }, { value: 'conflicts', label: 'Conflicts', count: g.validation.conflicts.length }]" />
        <ul class="list issues">
          <template v-if="issueTab === 'rules'"><li v-for="(v, i) in g.validation.violations" :key="i"><StatusBadge :tone="v.severity === 'error' ? 'bad' : 'warn'" :label="v.rule.replace('_', ' ')" /><button class="link grow" @click="goTo(v.employee, v.date)">{{ v.message }}</button></li></template>
          <template v-if="issueTab === 'gaps'"><li v-for="(v, i) in g.validation.gaps" :key="i"><StatusBadge tone="bad" :label="`${v.have}/${v.need}`" /><span class="grow">{{ v.shift_type }} on {{ fmtDate(v.date, { weekday: "short", day: "numeric", month: "short" }) }}</span></li></template>
          <template v-if="issueTab === 'conflicts'"><li v-for="(v, i) in g.validation.conflicts" :key="i"><StatusBadge :tone="v.severity === 'blocker' ? 'bad' : v.severity === 'warning' ? 'warn' : 'muted'" :label="v.kind.replace('_', ' ')" /><button class="link grow" @click="goTo(v.employee, v.date)">{{ v.message }}</button></li></template>
        </ul>
        <p class="small muted" v-if="issueTab === 'rules' && !g.validation.violations.length">No working-time issues.</p>
        <p class="small muted" v-if="issueTab === 'gaps' && !g.requirements.length">Set coverage needs to check minimum staffing per shift.</p>
        <div class="row" v-if="!archived && g.roster.status === 'Published'"><button class="btn ghost sm" @click="archive">Archive roster</button></div>
      </section>

      <AccessibleDialog :open="pubOpen" :title="g.roster.status === 'Published' ? 'Republish roster' : 'Publish roster'" wide @close="pubOpen = false">
        <div class="stack" v-if="!report">
          <p>Publishing writes thinkNXG HR Shift Assignments for <strong>{{ fmtDate(g.today > g.roster.from_date ? g.today : g.roster.from_date) }}</strong> to <strong>{{ fmtDate(g.roster.to_date) }}</strong>. Past days are never changed. Rest days get no assignment.</p>
          <p class="small muted">{{ g.validation.summary.warnings }} warning(s) and {{ g.validation.summary.gaps }} coverage gap(s) won't stop publishing.</p>
          <div v-if="blockers.length" class="block">
            <p><strong>{{ blockers.length }} manual shift assignment(s) overlap this roster.</strong> Those people are skipped unless HR trims the manual assignments.</p>
            <ul class="small"><li v-for="b in blockers" :key="b.assignment">{{ b.message }}</li></ul>
            <label v-if="g.can_trim_manual" class="check"><input type="checkbox" v-model="trim" />End or deactivate these manual assignments (recorded on each assignment)</label>
          </div>
          <div v-if="hasPastWindow" class="pastbox">
            <label class="check"><input type="checkbox" v-model="backfill" />Also apply past days from {{ fmtDate(g.backdate_from > g.roster.from_date ? g.backdate_from : g.roster.from_date) }} to yesterday</label>
            <p class="small muted">Fills missing shift assignments and corrects roster-made ones. Days with submitted attendance and manual shift assignments are never changed. Re-run auto attendance on the Shift Type afterwards if those days still need attendance.</p>
          </div>
          <p class="small muted">People whose shifts change are notified.</p>
        </div>
        <div v-else class="stack">
          <dl class="rep"><div><dt>Assignments created</dt><dd>{{ report.created }}</dd></div><div><dt>Ended</dt><dd>{{ report.ended }}</dd></div><div><dt>Replaced</dt><dd>{{ report.cancelled }}</dd></div><div><dt>People notified</dt><dd>{{ report.notified }}</dd></div></dl>
          <p v-if="report.conflicts.length" class="warn small">{{ report.conflicts.length }} person(s) skipped because of manual shift assignments.</p>
          <ul v-if="report.errors.length" class="small bad"><li v-for="er in report.errors" :key="er.employee">{{ er.employee }}: {{ er.error }}</li></ul>
          <template v-if="report.past && report.past.from">
            <h3>Past days ({{ fmtDate(report.past.from, { day: "numeric", month: "short" }) }} – {{ fmtDate(report.past.to, { day: "numeric", month: "short" }) }})</h3>
            <dl class="rep"><div><dt>Assignments created</dt><dd>{{ report.past.created }}</dd></div><div><dt>Already correct</dt><dd>{{ report.past.unchanged }}</dd></div>
              <div><dt>Days with attendance (kept)</dt><dd>{{ report.past.skipped_attendance }}</dd></div><div><dt>Blocked by manual assignments</dt><dd>{{ report.past.skipped_manual.length }}</dd></div></dl>
            <ul v-if="report.past.errors.length" class="small bad"><li v-for="er in report.past.errors" :key="er.employee + er.from">{{ er.employee }} ({{ er.from }}): {{ er.error }}</li></ul>
          </template>
        </div>
        <template #footer>
          <button class="btn" @click="pubOpen = false">{{ report ? t("Close") : t("Cancel") }}</button>
          <button v-if="!report" class="btn primary" :disabled="busy" @click="publish">{{ busy ? "Publishing…" : "Publish" }}</button>
        </template>
      </AccessibleDialog>

      <AccessibleDialog :open="patOpen" title="Apply a shift pattern" wide @close="patOpen = false">
        <div class="stack">
          <div class="field"><label for="pp">Pattern</label><select id="pp" class="select" v-model="pat.pattern"><option v-for="p in g.patterns" :key="p.name" :value="p.name">{{ p.name }} ({{ p.steps.length }}-day cycle)</option></select></div>
          <div class="steps" v-if="patSteps.length"><ShiftChip v-for="(s, i) in patSteps" :key="i" :rest="!s" :code="s ? types[s]?.code : ''" :color="s ? types[s]?.color : ''" size="sm" /></div>
          <details><summary class="small">Create a new pattern</summary>
            <div class="stack" style="margin-top: 10px">
              <input class="input" v-model="pat.newName" placeholder="Pattern name, e.g. 4 on 4 off" aria-label="New pattern name" />
              <div class="row wrap"><button v-for="st in g.shift_types" :key="st.name" type="button" class="btn sm" @click="pat.steps.push(st.name)">+ {{ st.code }}</button><button type="button" class="btn sm" @click="pat.steps.push(null)">+ Rest</button><button type="button" class="btn ghost sm" @click="pat.steps.pop()">Undo</button></div>
              <div class="steps"><ShiftChip v-for="(s, i) in pat.steps" :key="i" :rest="!s" :code="s ? types[s]?.code : ''" :color="s ? types[s]?.color : ''" size="sm" /></div>
              <div><button type="button" class="btn sm" :disabled="!pat.newName || !pat.steps.length" @click="savePattern">Save pattern</button></div>
            </div></details>
          <div class="form-grid">
            <div class="field"><label for="ps">{{ t("From") }}</label><input id="ps" type="date" class="input" v-model="pat.start" :min="dates[0]" :max="dates[dates.length - 1]" /></div>
            <div class="field"><label for="pe">{{ t("To") }}</label><input id="pe" type="date" class="input" v-model="pat.end" :min="pat.start" :max="dates[dates.length - 1]" /></div>
            <label class="check" style="align-self: end"><input type="checkbox" v-model="pat.keepWO" />Keep weekly offs</label>
            <div class="field"><label for="pg">Stagger (days per person)</label><input id="pg" type="number" min="0" max="27" class="input" v-model.number="pat.stagger" /><span class="hint">1 starts each person one step later, so the team covers every day.</span></div>
          </div>
          <div class="field"><label>People ({{ pat.employees.length }})</label>
            <div class="people"><label v-for="e in allEmps" :key="e.name" class="check"><input type="checkbox" :value="e.name" v-model="pat.employees" />{{ e.employee_name }}</label></div></div>
        </div>
        <template #footer><button class="btn" @click="patOpen = false">{{ t("Cancel") }}</button><button class="btn primary" :disabled="busy || !pat.pattern || !pat.employees.length" @click="applyPattern">Apply</button></template>
      </AccessibleDialog>

      <AccessibleDialog :open="copyOpen" title="Copy another roster" @close="copyOpen = false">
        <div class="stack">
          <div class="field"><label for="cs">Source roster</label><select id="cs" class="select" v-model="source"><option v-for="r in sources" :key="r.name" :value="r.name">{{ r.title }} ({{ fmtDate(r.from_date, { day: "numeric", month: "short" }) }} – {{ fmtDate(r.to_date, { day: "numeric", month: "short" }) }})</option></select></div>
          <p class="small muted">Whole weeks of the source repeat across this roster so weekdays line up. Only people on both rosters are copied; past published days stay as they are.</p>
          <label class="check"><input type="checkbox" v-model="copyKeepWO" />Keep each person's weekly offs as rest days</label>
        </div>
        <template #footer><button class="btn" @click="copyOpen = false">{{ t("Cancel") }}</button><button class="btn primary" :disabled="busy || !source" @click="doCopy">Copy</button></template>
      </AccessibleDialog>

      <AccessibleDialog :open="reqOpen" title="Coverage needs" wide @close="reqOpen = false">
        <div class="stack">
          <p class="small muted">Minimum people per shift. A weekday row overrides "All days" for that shift.</p>
          <div v-for="(r, i) in reqs" :key="i" class="req">
            <select class="select" v-model="r.shift_type" aria-label="Shift"><option v-for="st in g.shift_types" :key="st.name" :value="st.name">{{ st.name }}</option></select>
            <select class="select" v-model="r.weekday" aria-label="Day"><option v-for="wd in WEEKDAYS" :key="wd">{{ wd }}</option></select>
            <input class="input num" type="number" min="1" v-model.number="r.min_staff" aria-label="Minimum people" />
            <button class="btn ghost sm" @click="reqs.splice(i, 1)" aria-label="Remove row">×</button>
          </div>
          <div><button class="btn sm" @click="reqs.push({ shift_type: g.shift_types[0]?.name, weekday: 'All days', min_staff: 1 })">Add row</button></div>
        </div>
        <template #footer><button class="btn" @click="reqOpen = false">{{ t("Cancel") }}</button><button class="btn primary" :disabled="busy" @click="saveReqs">{{ t("Save") }}</button></template>
      </AccessibleDialog>

      <AccessibleDialog :open="woOpen" title="Mark weekly offs" @close="woOpen = false">
        <div class="stack">
          <p>Sets each person's weekly off days from their holiday list as rest days (shown as W).</p>
          <div class="field"><label for="ws">Apply to</label><select id="ws" class="select" v-model="woScope">
            <option value="shown">People shown ({{ emps.length }})</option><option value="selected" :disabled="!selectedRows.length">Selected people ({{ selectedRows.length }})</option><option value="all">Everyone on this roster ({{ allEmps.length }})</option></select></div>
          <label class="check"><input type="checkbox" v-model="woOverwrite" />Replace shifts already planned on weekly offs</label>
          <p class="small muted">Leave this off to keep people you've deliberately scheduled on their day off; they can claim compensatory leave once attendance is marked.</p>
        </div>
        <template #footer><button class="btn" @click="woOpen = false">{{ t("Cancel") }}</button><button class="btn primary" :disabled="busy" @click="applyWeeklyOffs">Mark weekly offs</button></template>
      </AccessibleDialog>

      <AccessibleDialog :open="addOpen" title="Add people" @close="addOpen = false">
        <div class="filters add">
          <select class="select" v-model="addDept" aria-label="Department"><option value="">All departments</option><option v-for="d in teamDepts" :key="d" :value="d">{{ d }}</option></select>
          <select class="select" v-model="addBranch" aria-label="Branch"><option value="">All branches</option><option v-for="b in teamBranches" :key="b" :value="b">{{ b }}</option></select>
          <button class="btn sm ghost" @click="toAdd = [...new Set([...toAdd, ...teamShown.map((x) => x.name)])]">Select all {{ teamShown.length }}</button>
        </div>
        <div class="people tall"><label v-for="e in teamShown" :key="e.name" class="check"><input type="checkbox" :value="e.name" v-model="toAdd" />{{ e.employee_name }} <span class="small muted">{{ e.department }}</span></label>
          <p v-if="!team.length" class="muted small">Everyone in your team is already on this roster.</p>
          <p v-else-if="!teamShown.length" class="muted small">No one matches these filters.</p></div>
        <template #footer><button class="btn" @click="addOpen = false">{{ t("Cancel") }}</button><button class="btn primary" :disabled="busy || !toAdd.length" @click="doAdd">Add {{ toAdd.length || "" }}</button></template>
      </AccessibleDialog>
    </template>
  </div>
</template>

<style scoped>
.wide { max-width: none; }
.filters { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.filters .select, .filters .input { width: auto; min-width: 180px; min-height: 36px; padding: 6px 10px; }
.filters.add { margin-bottom: 10px; }
.shown { margin-inline-start: 4px; }
.past-toggle { margin-inline-start: auto; padding: 4px 10px; border: 1px solid var(--line); border-radius: 10px; background: var(--surface); }
.past-toggle.on { border-color: var(--saffron); background: var(--saffron-soft); color: var(--saffron-ink); }
.pastbox { padding: 12px 14px; border-radius: 10px; background: var(--saffron-soft); }
.grid thead th.pastedit { background: var(--saffron-soft); opacity: 1; }
.cell.pastedit { background: color-mix(in srgb, var(--saffron-soft) 60%, transparent); }
.empty.wohint { color: var(--ink-3); font-size: 11px; font-weight: 600; }
:deep(.wo b) { background: var(--surface-2); color: var(--ink-2); border-style: dashed; }
.toolbar { display: flex; flex-direction: column; gap: 10px; padding: 12px 14px; background: var(--surface); border: 1px solid var(--line); border-radius: var(--r-lg); position: sticky; top: calc(var(--header) + 6px); z-index: 6; }
.brushes { display: flex; gap: 6px; flex-wrap: wrap; }
.brush { display: inline-flex; align-items: center; gap: 8px; height: 36px; padding: 0 10px; border-radius: 10px; border: 1px solid var(--line); background: var(--surface); cursor: pointer; font-size: var(--fs-sm); }
.brush.on { border-color: var(--brand); background: var(--brand-soft); box-shadow: inset 0 0 0 1px var(--brand); }
.bn { font-weight: 500; } .bt { color: var(--ink-3); font-size: var(--fs-xs); }
.eraser { display: inline-grid; place-items: center; width: 22px; height: 20px; border-radius: 6px; border: 1px dashed var(--line-strong); color: var(--ink-3); }
.tools { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
.sm-sel { width: auto; min-height: 32px; padding: 4px 8px; font-size: var(--fs-sm); }
.save { margin-inline-start: auto; color: var(--ink-3); } .save.saved { color: var(--ok); } .save.error { color: var(--pom); }
.hint { margin: 0; }
.grid-wrap { overflow: auto; max-height: calc(100vh - 290px); border: 1px solid var(--line); border-radius: var(--r-lg); background: var(--surface); }
.grid { border-collapse: separate; border-spacing: 0; font-size: var(--fs-sm); }
.grid th, .grid td { border-bottom: 1px solid var(--line); border-inline-end: 1px solid var(--line); padding: 0; }
.grid thead th { position: sticky; top: 0; z-index: 3; background: var(--surface); padding: 6px 2px; min-width: 40px; text-align: center; font-weight: 500; }
.grid thead th .wd { display: block; font-size: 11px; color: var(--ink-3); }
.grid thead th .dn { display: block; font-weight: 600; }
.grid thead th .mo { display: block; font-size: 10px; color: var(--brand); font-weight: 600; }
.grid thead th.today .dn { color: #fff; background: var(--brand); border-radius: 10px; margin: 0 6px; }
.grid thead th.past { opacity: .5; }
.sticky { position: sticky; inset-inline-start: 0; z-index: 2; background: var(--surface); }
.corner { z-index: 4 !important; text-align: start !important; padding: 6px 12px !important; min-width: 210px; }
.emp { min-width: 210px; max-width: 240px; padding: 4px 8px !important; text-align: start; font-weight: 400; }
.emp { display: flex; align-items: center; gap: 8px; }
.en { display: flex; flex-direction: column; min-width: 0; flex: 1; line-height: 1.25; }
.en .title { font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.en .small { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.sel input { width: 16px; height: 16px; accent-color: var(--brand); }
.rm { border: 0; background: none; color: var(--ink-3); cursor: pointer; font-size: 16px; opacity: 0; }
tr:hover .rm, .rm:focus { opacity: 1; }
td.wk, th.wk { background: color-mix(in srgb, var(--surface-2) 70%, var(--surface)); }
.cell { position: relative; width: 40px; height: 38px; border: 0; background: transparent; cursor: cell; display: grid; place-items: center; touch-action: manipulation; user-select: none; }
.cell:hover { background: var(--brand-soft); }
.cell:focus-visible { outline: 2px solid var(--focus); outline-offset: -2px; border-radius: 4px; }
.cell.locked { cursor: not-allowed; opacity: .55; }
.cell.leave { background: repeating-linear-gradient(-45deg, transparent 0 5px, color-mix(in srgb, var(--info) 14%, transparent) 5px 9px); }
.cell.hol::after { content: ""; position: absolute; top: 3px; inset-inline-start: 3px; width: 6px; height: 6px; border-radius: 50%; background: var(--saffron); }
.cell.issue::before { content: ""; position: absolute; top: 0; inset-inline-end: 0; border-style: solid; border-width: 0 9px 9px 0; border-color: transparent var(--pom) transparent transparent; }
[dir="rtl"] .cell.issue::before { border-width: 0 0 9px 9px; border-color: transparent transparent transparent var(--pom); }
.empty { color: var(--line-strong); }
.lv { position: absolute; bottom: 1px; inset-inline-end: 2px; font-style: normal; font-size: 9px; font-weight: 700; color: var(--info); }
.tot { padding: 0 10px !important; white-space: nowrap; color: var(--ink-2); text-align: end; }
tfoot th, tfoot td { background: var(--surface-2); }
tfoot .c { text-align: center; height: 28px; font-weight: 600; color: var(--ink-2); }
tfoot .c.short { background: var(--pom-soft); color: var(--pom); }
.cov { font-weight: 500; }
.legend { display: flex; gap: 16px; flex-wrap: wrap; }
.k { display: inline-block; width: 10px; height: 10px; border-radius: 3px; margin-inline-end: 6px; vertical-align: -1px; }
.lvk { background: repeating-linear-gradient(-45deg, transparent 0 2px, var(--info) 2px 4px); } .holk { background: var(--saffron); border-radius: 50%; }
.isk { background: var(--pom); } .shk { background: var(--pom-soft); outline: 1px solid var(--pom); }
.issues { max-height: 280px; overflow-y: auto; }
.link { border: 0; background: none; text-align: start; padding: 0; cursor: pointer; color: inherit; font: inherit; }
.link:hover { color: var(--brand); text-decoration: underline; }
.block { padding: 12px 14px; border-radius: 10px; background: var(--pom-soft); }
.rep { margin: 0; display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; } .rep dt { font-size: var(--fs-xs); color: var(--ink-3); } .rep dd { margin: 0; font-size: var(--fs-xl); font-weight: 600; }
.steps { display: flex; gap: 4px; flex-wrap: wrap; }
.people { max-height: 200px; overflow-y: auto; border: 1px solid var(--line); border-radius: 8px; padding: 6px 10px; display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); }
.people.tall { max-height: 50vh; }
.req { display: grid; grid-template-columns: 2fr 1.4fr 90px auto; gap: 8px; align-items: center; }
.warn { color: var(--saffron-ink); } .bad { color: var(--pom); }
@media (max-width: 760px) { .bt { display: none; } .toolbar { position: static; } .grid-wrap { max-height: none; } .corner, .emp { min-width: 150px; } .rep { grid-template-columns: 1fr 1fr; } }
</style>
