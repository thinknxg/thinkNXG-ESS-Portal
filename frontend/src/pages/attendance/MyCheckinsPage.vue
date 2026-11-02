<script setup lang="ts">
import { computed, ref } from "vue";
import { useResource } from "@/composables/useResource";
import { Attendance } from "@/services/endpoints";
import { fmtDate, fmtTime, t } from "@/i18n";
import { addDays, isoToday } from "@/utils/format";
import PageHeader from "@/components/ui/PageHeader.vue";
import StatusBadge from "@/components/ui/StatusBadge.vue";
import PunchList from "@/components/hr/PunchList.vue";
import SkeletonLoader from "@/components/ui/SkeletonLoader.vue";
import ErrorState from "@/components/ui/ErrorState.vue";
import EmptyState from "@/components/ui/EmptyState.vue";

const from = ref(addDays(isoToday(), -6));
const to = ref(isoToday());
const range = computed(() => `${from.value}|${to.value}`);
const { data, loading, error, reload } = useResource<any>(() => `checkins:mine:${range.value}`, () => Attendance.myCheckins(from.value, to.value), { watch: [range] });
function preset(days: number) { to.value = isoToday(); from.value = addDays(isoToday(), -(days - 1)); }
function thisMonth() { const d = new Date(); to.value = isoToday(); from.value = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-01`; }
const totals = computed(() => {
  const days = data.value?.days || [];
  return { days: days.length, punches: days.reduce((a: number, d: any) => a + d.count, 0), open: days.filter((d: any) => d.open).length };
});
</script>

<template>
  <div class="page">
    <PageHeader :title="t('Check-in records')" subtitle="Every punch recorded for you: from this portal, attendance devices and HR." back="/attendance">
      <RouterLink to="/attendance/check-in" class="btn primary">{{ t("Check in") }}</RouterLink>
    </PageHeader>
    <div class="bar">
      <div class="row wrap">
        <button class="btn sm" @click="preset(7)">Last 7 days</button>
        <button class="btn sm" @click="preset(14)">Last 14 days</button>
        <button class="btn sm" @click="thisMonth">This month</button>
      </div>
      <div class="row">
        <label class="sr-only" for="mf">From</label><input id="mf" type="date" class="input" v-model="from" :max="to" />
        <span class="muted">–</span>
        <label class="sr-only" for="mt">To</label><input id="mt" type="date" class="input" v-model="to" :min="from" :max="isoToday()" />
      </div>
    </div>
    <ErrorState :error="error" @retry="reload" />
    <SkeletonLoader v-if="loading && !data" :lines="8" />
    <template v-else-if="data">
      <p class="small muted">{{ totals.punches }} punch(es) on {{ totals.days }} day(s)<template v-if="totals.open"> · {{ totals.open }} day(s) without a check-out</template></p>
      <section class="panel" v-if="data.days.length">
        <ul class="list days">
          <li v-for="d in data.days" :key="d.date">
            <div class="when"><span class="wd">{{ fmtDate(d.date, { weekday: "short" }) }}</span><span class="dn num">{{ fmtDate(d.date, { day: "numeric", month: "short" }) }}</span></div>
            <div class="grow">
              <div class="sum small"><span v-if="d.first_in">In {{ fmtTime(d.first_in) }}</span><span v-if="d.last_out">Out {{ fmtTime(d.last_out) }}</span>
                <StatusBadge v-if="d.open" tone="warn" label="No check-out" /><StatusBadge v-if="d.untyped" tone="muted" :label="`${d.untyped} untyped`" /></div>
              <PunchList :punches="d.punches" :coordinates="data.coordinates" />
            </div>
            <div class="att"><StatusBadge v-if="d.attendance" :status="d.attendance.status" /><span v-else class="small muted">Not marked yet</span>
              <span v-if="d.attendance?.working_hours" class="small muted num">{{ d.attendance.working_hours.toFixed(1) }} h</span></div>
          </li>
        </ul>
      </section>
      <section class="panel" v-else><EmptyState title="No punches in this period" icon="clock" /></section>
      <p class="small muted">Missing a punch? <RouterLink to="/attendance/corrections?new=1">{{ t("Request correction") }}</RouterLink></p>
    </template>
  </div>
</template>

<style scoped>
.bar { display: flex; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
.bar .input { width: auto; }
.days li { align-items: flex-start; gap: 16px; }
.when { display: flex; flex-direction: column; min-width: 64px; line-height: 1.25; }
.wd { font-size: var(--fs-xs); color: var(--ink-3); } .dn { font-weight: 600; }
.sum { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; margin-bottom: 4px; color: var(--ink-2); }
.att { display: flex; flex-direction: column; align-items: flex-end; gap: 4px; min-width: 90px; }
</style>
