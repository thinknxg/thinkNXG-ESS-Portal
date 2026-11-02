<script setup lang="ts">
import { useLeaveBalance } from "@/composables/hr";
import { invalidate } from "@/composables/useResource";
import { Leave } from "@/services/endpoints";
import { fmtDate, t } from "@/i18n";
import { useUi } from "@/stores/ui";
import { useSession } from "@/stores/session";
import { ref } from "vue";
import PageHeader from "@/components/ui/PageHeader.vue";
import StatusBadge from "@/components/ui/StatusBadge.vue";
import SkeletonLoader from "@/components/ui/SkeletonLoader.vue";
import ErrorState from "@/components/ui/ErrorState.vue";
import EmptyState from "@/components/ui/EmptyState.vue";
import ConfirmActionDialog from "@/components/ui/ConfirmActionDialog.vue";

const ui = useUi();
const s = useSession();
const { data, balances, loading, error, reload } = useLeaveBalance();
const withdrawing = ref<any>(null);
async function withdraw() {
  try { await Leave.withdraw(withdrawing.value.name); ui.toast("Request withdrawn"); invalidate("leave"); reload(); }
  catch (e: any) { ui.toast(e.message, "error"); } finally { withdrawing.value = null; }
}
</script>

<template>
  <div class="page">
    <PageHeader :title="t('Leave')" :subtitle="data?.approver ? `Requests go to ${data.approver.name} for approval.` : undefined">
      <RouterLink to="/leave/calendar" class="btn">{{ t("Leave calendar") }}</RouterLink>
      <RouterLink v-if="s.module('comp_off')" to="/leave/comp-off" class="btn">{{ t("Compensatory leave") }}</RouterLink>
      <RouterLink to="/leave/apply" class="btn primary">{{ t("Apply for leave") }}</RouterLink>
    </PageHeader>
    <ErrorState :error="error" @retry="reload" />
    <SkeletonLoader v-if="loading && !data" :lines="6" />
    <template v-if="data">
      <section class="balances" v-if="balances.length">
        <article v-for="b in balances" :key="b.leave_type" class="bal">
          <h2>{{ b.leave_type }}</h2>
          <p class="rem num">{{ b.remaining }}<span class="of"> / {{ b.allocated }}</span></p>
          <div class="bar" role="img" :aria-label="`${b.taken} taken, ${b.pending} pending, ${b.remaining} remaining of ${b.allocated}`">
            <span class="taken" :style="{ width: (b.allocated ? (b.taken / b.allocated) * 100 : 0) + '%' }" />
            <span class="pend" :style="{ width: (b.allocated ? (b.pending / b.allocated) * 100 : 0) + '%' }" />
          </div>
          <p class="small muted"><span class="num">{{ b.taken }}</span> taken · <span class="num">{{ b.pending }}</span> pending<template v-if="b.expired"> · <span class="num">{{ b.expired }}</span> expired</template></p>
        </article>
      </section>
      <section class="panel" v-else><EmptyState title="No leave allocated yet" text="Your HR team allocates leave at the start of each period." icon="sun" /></section>

      <div class="cols">
        <section class="panel">
          <header><h2>Requests</h2></header>
          <ul class="list" v-if="data.recent.length">
            <li v-for="r in data.recent" :key="r.name">
              <span class="grow"><span class="title">{{ r.leave_type }}</span>
                <br><span class="small muted">{{ fmtDate(r.from_date) }} – {{ fmtDate(r.to_date) }} · <span class="num">{{ r.total_leave_days }}</span> {{ t("Days").toLowerCase() }}</span></span>
              <StatusBadge :status="r.status" />
              <button v-if="r.status === 'Open' && r.docstatus === 0" class="btn ghost sm" @click="withdrawing = r">Withdraw</button>
            </li>
          </ul>
          <EmptyState v-else title="No leave requests yet" :action-label="t('Apply for leave')" action-to="/leave/apply" icon="sun" />
        </section>
        <section class="panel">
          <header><h2>Coming up</h2></header>
          <ul class="list" v-if="data.upcoming.length">
            <li v-for="u in data.upcoming" :key="u.name"><span class="grow">{{ u.leave_type }}</span><span class="small num">{{ fmtDate(u.from_date) }} – {{ fmtDate(u.to_date) }}</span></li>
          </ul>
          <p v-else class="muted small">No approved leave ahead.</p>
        </section>
      </div>
    </template>
    <ConfirmActionDialog :open="!!withdrawing" title="Withdraw this request?" text="Your manager will no longer see it. You can apply again any time."
      confirm-label="Withdraw request" danger @close="withdrawing = null" @confirm="withdraw" />
  </div>
</template>

<style scoped>
.balances { display: grid; grid-template-columns: repeat(auto-fill, minmax(210px, 1fr)); gap: 12px; }
.bal { background: var(--surface); border: 1px solid var(--line); border-radius: var(--r-md); padding: 16px; display: flex; flex-direction: column; gap: 8px; }
.bal h2 { font-size: var(--fs-sm); font-weight: 500; color: var(--ink-2); }
.rem { font-size: var(--fs-2xl); font-weight: 600; letter-spacing: -0.03em; line-height: 1; }
.of { font-size: var(--fs-md); color: var(--ink-3); font-weight: 400; }
.bar { display: flex; height: 6px; border-radius: 3px; background: color-mix(in srgb, var(--brand) 22%, var(--surface-2)); overflow: hidden; }
.taken { background: var(--ink-3); } .pend { background: var(--saffron); }
</style>
