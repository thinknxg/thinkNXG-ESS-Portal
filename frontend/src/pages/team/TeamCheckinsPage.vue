<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useResource } from "@/composables/useResource";
import { CheckinRecords } from "@/services/endpoints";
import { fmtDate, fmtTime, t } from "@/i18n";
import { addDays, isoToday } from "@/utils/format";
import PageHeader from "@/components/ui/PageHeader.vue";
import StatusBadge from "@/components/ui/StatusBadge.vue";
import PunchList from "@/components/hr/PunchList.vue";
import SkeletonLoader from "@/components/ui/SkeletonLoader.vue";
import ErrorState from "@/components/ui/ErrorState.vue";
import EmptyState from "@/components/ui/EmptyState.vue";

const route = useRoute();
const router = useRouter();
const f = ref({ from_date: (route.query.from as string) || isoToday(), to_date: (route.query.to as string) || isoToday(),
  department: (route.query.department as string) || "", branch: (route.query.branch as string) || "", employee: (route.query.employee as string) || "" });
const issuesOnly = ref(false);
const params = computed(() => ({ ...f.value }));
watch(params, (p) => router.replace({ query: Object.fromEntries(Object.entries({ from: p.from_date, to: p.to_date, department: p.department, branch: p.branch, employee: p.employee }).filter(([, v]) => v)) }));
const { data, loading, error, reload } = useResource<any>(() => `checkins:team:${JSON.stringify(params.value)}`, () => CheckinRecords.team(params.value), { watch: [params] });
const open = ref<Set<string>>(new Set());
const rows = computed(() => (data.value?.days || []).filter((d: any) => !issuesOnly.value || d.open || d.untyped || !d.attendance));
function toggle(k: string) { const s = new Set(open.value); s.has(k) ? s.delete(k) : s.add(k); open.value = s; }
function preset(days: number) { f.value.to_date = isoToday(); f.value.from_date = addDays(isoToday(), -(days - 1)); }
function csv() {
  const out = [["date", "employee", "employee_name", "department", "branch", "time", "log_type", "source", "device_id", "location", "distance_m", "accuracy_m", ...(data.value.coordinates ? ["latitude", "longitude"] : []), "attendance"]];
  for (const d of rows.value) for (const p of d.punches)
    out.push([d.date, d.employee, d.employee_name, d.department || "", d.branch || "", p.time, p.log_type || "", p.source, p.device_id || "", p.ess_location || "", p.ess_distance ?? "", p.ess_accuracy ?? "", ...(data.value.coordinates ? [p.latitude ?? "", p.longitude ?? ""] : []), d.attendance?.status || ""]);
  const body = out.map((r) => r.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(",")).join("\n");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([body], { type: "text/csv" }));
  a.download = `checkins-${f.value.from_date}-${f.value.to_date}.csv`;
  a.click();
}
</script>

<template>
  <div class="page">
    <PageHeader :title="t('Team check-ins')" :subtitle="data?.scope === 'hr' ? 'Everyone within your HR scope, from all channels.' : 'Your team, from all channels.'">
      <button class="btn" @click="csv" :disabled="!rows.length">Export CSV</button>
    </PageHeader>
    <div class="filters">
      <input type="date" class="input" v-model="f.from_date" :max="f.to_date" aria-label="From" />
      <input type="date" class="input" v-model="f.to_date" :min="f.from_date" :max="isoToday()" aria-label="To" />
      <select class="select" v-model="f.department" aria-label="Department"><option value="">{{ t("All departments") }}</option><option v-for="d in data?.departments || []" :key="d" :value="d">{{ d }}</option></select>
      <select class="select" v-model="f.branch" aria-label="Branch"><option value="">{{ t("All branches") }}</option><option v-for="b in data?.branches || []" :key="b" :value="b">{{ b }}</option></select>
      <select class="select" v-model="f.employee" aria-label="Employee"><option value="">Everyone</option><option v-for="e in data?.employees || []" :key="e.name" :value="e.name">{{ e.employee_name }}</option></select>
    </div>
    <div class="spread wrap">
      <div class="row wrap"><button class="btn sm" @click="preset(1)">{{ t("Today") }}</button><button class="btn sm" @click="preset(7)">Last 7 days</button><button class="btn sm" @click="preset(14)">Last 14 days</button></div>
      <label class="check"><input type="checkbox" v-model="issuesOnly" />Only days needing attention</label>
    </div>
    <ErrorState :error="error" @retry="reload" />
    <section class="panel">
      <SkeletonLoader v-if="loading && !data" :lines="8" />
      <div class="table-wrap" v-else-if="rows.length">
        <table class="data">
          <thead><tr><th>Date</th><th>Employee</th><th>First in</th><th>Last out</th><th class="n">Punches</th><th>Sources</th><th>Attendance</th><th></th></tr></thead>
          <tbody>
            <template v-for="d in rows" :key="d.employee + d.date">
              <tr class="click" tabindex="0" @click="toggle(d.employee + d.date)" @keydown.enter="toggle(d.employee + d.date)" :aria-expanded="open.has(d.employee + d.date)">
                <td class="num small">{{ fmtDate(d.date, { weekday: "short", day: "numeric", month: "short" }) }}</td>
                <td>{{ d.employee_name }}<br><span class="small muted">{{ d.department }}<template v-if="d.branch"> · {{ d.branch }}</template></span></td>
                <td class="num">{{ d.first_in ? fmtTime(d.first_in) : "—" }}</td>
                <td class="num">{{ d.last_out ? fmtTime(d.last_out) : "—" }}</td>
                <td class="n">{{ d.count }}</td>
                <td class="small">{{ [...new Set(d.punches.map((p: any) => p.source))].join(", ") }}</td>
                <td><StatusBadge v-if="d.attendance" :status="d.attendance.status" /><span v-else class="small muted">Not marked</span></td>
                <td><StatusBadge v-if="d.open" tone="warn" label="No check-out" /><StatusBadge v-if="d.untyped" tone="muted" :label="`${d.untyped} untyped`" /></td>
              </tr>
              <tr v-if="open.has(d.employee + d.date)" class="detail"><td></td><td colspan="7"><PunchList :punches="d.punches" :coordinates="data.coordinates" /></td></tr>
            </template>
          </tbody>
        </table>
        <p v-if="data.truncated" class="small warn">Showing the first 5,000 punches. Narrow the dates or filters to see the rest.</p>
      </div>
      <EmptyState v-else title="No punches match these filters" icon="clock" />
      <p class="small muted" v-if="data && !data.coordinates">Raw GPS coordinates are visible to HR only.</p>
    </section>
  </div>
</template>

<style scoped>
.filters { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 8px; }
tr.click { cursor: pointer; } tr.click:hover td { background: var(--surface-2); }
tr.detail td { background: var(--surface-2); }
.warn { color: var(--saffron-ink); }
@media (max-width: 860px) { .filters { grid-template-columns: 1fr 1fr; } }
</style>
