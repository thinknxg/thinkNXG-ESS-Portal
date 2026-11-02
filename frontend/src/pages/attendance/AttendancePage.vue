<script setup lang="ts">
import { computed, ref } from "vue";
import { useResource } from "@/composables/useResource";
import { Attendance } from "@/services/endpoints";
import { t, fmtDate } from "@/i18n";
import { useSession } from "@/stores/session";
import PageHeader from "@/components/ui/PageHeader.vue";
import MonthCalendar, { type DayCell } from "@/components/hr/MonthCalendar.vue";
import StatusBadge from "@/components/ui/StatusBadge.vue";
import SkeletonLoader from "@/components/ui/SkeletonLoader.vue";
import ErrorState from "@/components/ui/ErrorState.vue";
import MetricCard from "@/components/ui/MetricCard.vue";

const s = useSession();
const now = new Date();
const y = ref(now.getFullYear());
const m = ref(now.getMonth() + 1);
const selected = ref<string | null>(null);
const { data, loading, error, reload } = useResource<any>(() => `attendance:${y.value}-${m.value}`, () => Attendance.month(y.value, m.value), { watch: [y, m] });

const TONE: Record<string, string> = { Present: "ok", Absent: "bad", "On Leave": "info", "Half Day": "info", "Work From Home": "brand", Holiday: "warn", Missing: "bad", Unmarked: "", "Rest Day": "" };
const cells = computed<Record<string, DayCell>>(() => {
  const out: Record<string, DayCell> = {};
  for (const d of data.value?.days || []) {
    const marks = [] as { tone: string; text: string }[];
    if (d.late) marks.push({ tone: "warn", text: t("Late") });
    if (d.incomplete) marks.push({ tone: "bad", text: t("Missing punch") });
    const sh = d.shifts?.[0];
    out[d.date] = { date: d.date, tone: TONE[d.status] || "", color: d.status === "Future" && sh ? sh.color : undefined,
      label: d.holiday || (d.status === "Future" && sh ? `${sh.code} ${sh.start}` : ["Future", "Unmarked", "Weekly Off"].includes(d.status) ? "" : t(d.status)),
      marks, muted: d.status === "Future" && !sh };
  }
  return out;
});
const day = computed(() => data.value?.days.find((d: any) => d.date === selected.value));
function shift(n: number) { const d = new Date(y.value, m.value - 1 + n, 1); y.value = d.getFullYear(); m.value = d.getMonth() + 1; selected.value = null; }
</script>

<template>
  <div class="page">
    <PageHeader :title="t('Attendance')" subtitle="Your recorded attendance, from check-ins and HR's attendance records.">
      <RouterLink to="/attendance/check-in" class="btn primary">{{ t("Check in") }}</RouterLink>
      <RouterLink v-if="s.module('roster')" to="/roster" class="btn">{{ t("My roster") }}</RouterLink>
      <RouterLink to="/attendance/checkins" class="btn">{{ t("Check-in records") }}</RouterLink>
      <RouterLink to="/attendance/corrections" class="btn">{{ t("Corrections") }}</RouterLink>
    </PageHeader>
    <ErrorState :error="error" @retry="reload" />
    <div class="metrics" v-if="data">
      <MetricCard :label="t('Present')" :value="(data.summary.Present || 0) + (data.summary['Work From Home'] || 0)" tone="ok" />
      <MetricCard :label="t('Late')" :value="data.summary.late || 0" :tone="data.summary.late ? 'warn' : undefined" />
      <MetricCard :label="t('Absent')" :value="data.summary.Absent || 0" :tone="data.summary.Absent ? 'bad' : undefined" />
      <MetricCard :label="t('On leave')" :value="data.summary['On Leave'] || 0" />
      <MetricCard :label="t('Missing punch')" :value="data.days.filter((d: any) => d.incomplete).length" />
    </div>
    <div class="cols">
      <section class="panel">
        <SkeletonLoader v-if="loading && !data" :lines="8" :height="40" />
        <MonthCalendar v-else :year="y" :month="m" :cells="cells" :selected="selected" @select="selected = $event" @prev="shift(-1)" @next="shift(1)" />
      </section>
      <section class="panel">
        <template v-if="day">
          <header><h2>{{ fmtDate(day.date, { weekday: "long", day: "numeric", month: "long" }) }}</h2><StatusBadge :status="day.status" /></header>
          <p v-if="day.holiday" class="muted">{{ day.holiday }}</p>
          <p v-for="s in day.shifts || []" :key="s.start_dt" class="small">{{ s.shift_type }} · <span class="num">{{ s.start }}–{{ s.end }}</span></p>
          <ul class="list" v-if="day.logs.length">
            <li v-for="(l, i) in day.logs" :key="i"><span class="grow">{{ l.log_type === "IN" ? t("Check in") : t("Check out") }}</span><span class="num">{{ l.time }}</span></li>
          </ul>
          <p v-else class="muted">No check-ins recorded.</p>
          <p v-if="day.working_hours" class="small muted">Working hours: <span class="num">{{ day.working_hours.toFixed(2) }}</span></p>
          <RouterLink v-if="day.incomplete || day.status === 'Absent' || day.status === 'Missing'" class="btn sm"
                      :to="{ path: '/attendance/corrections', query: { new: 1, date: day.date } }">{{ t("Request correction") }}</RouterLink>
        </template>
        <p v-else class="muted">Select a day to see its punches and status.</p>
      </section>
    </div>
  </div>
</template>

<style scoped>
.metrics { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 8px; background: var(--surface); border: 1px solid var(--line); border-radius: var(--r-lg); padding: 6px; }
@media (max-width: 760px) { .metrics { grid-template-columns: repeat(2, 1fr); } }
</style>
