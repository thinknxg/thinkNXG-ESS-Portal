<script setup lang="ts">
import { computed, ref } from "vue";
import { useResource, invalidate } from "@/composables/useResource";
import { CompOff } from "@/services/endpoints";
import { fmtDate, t } from "@/i18n";
import { useUi } from "@/stores/ui";
import PageHeader from "@/components/ui/PageHeader.vue";
import StatusBadge from "@/components/ui/StatusBadge.vue";
import SkeletonLoader from "@/components/ui/SkeletonLoader.vue";
import ErrorState from "@/components/ui/ErrorState.vue";
import EmptyState from "@/components/ui/EmptyState.vue";
import ConfirmActionDialog from "@/components/ui/ConfirmActionDialog.vue";

const ui = useUi();
const { data, loading, error, reload } = useResource<any>(() => "compoff:eligible", () => CompOff.eligible());
const { data: mine, reload: reloadMine } = useResource<any[]>(() => "compoff:mine", () => CompOff.mine());
const picked = ref<string[]>([]);
const reason = ref("");
const leaveType = ref("");
const busy = ref(false);
const err = ref("");
const withdrawing = ref<any>(null);
const showAll = ref(false);

const eligible = computed(() => (data.value?.days || []).filter((d: any) => d.eligible));
const shown = computed(() => (showAll.value ? data.value?.days || [] : eligible.value));
const total = computed(() => picked.value.reduce((a, d) => a + ((data.value?.days || []).find((x: any) => x.date === d)?.half_day ? 0.5 : 1), 0));
const KIND_TONE: Record<string, any> = { "Weekly off": "muted", Holiday: "warn", "Rest day": "info" };

async function submit() {
  err.value = "";
  busy.value = true;
  try {
    const r: any = await CompOff.create({ dates: picked.value, reason: reason.value, leave_type: leaveType.value || undefined });
    ui.toast(r.names?.length > 1 ? `${r.names.length} requests sent for approval` : "Request sent for approval");
    picked.value = []; reason.value = "";
    invalidate("compoff"); invalidate("inbox"); reload(); reloadMine();
  } catch (e: any) { err.value = e.message; } finally { busy.value = false; }
}
async function withdraw() {
  try { await CompOff.withdraw(withdrawing.value.name); ui.toast("Request withdrawn"); invalidate("compoff"); reload(); reloadMine(); }
  catch (e: any) { ui.toast(e.message, "error"); } finally { withdrawing.value = null; }
}
</script>

<template>
  <div class="page">
    <PageHeader :title="t('Compensatory leave')" subtitle="Worked on a weekly off, holiday or rest day? Claim the time back as leave." back="/leave" />
    <ErrorState :error="error" @retry="reload" />
    <SkeletonLoader v-if="loading && !data" :lines="6" />
    <div class="cols" v-else-if="data">
      <section class="panel stack">
        <header><h2>Days you worked off</h2><label class="check small"><input type="checkbox" v-model="showAll" />Show days that don't qualify</label></header>
        <p v-if="data.setup_problem" class="note">{{ data.setup_problem }}</p>
        <ul class="list" v-if="shown.length">
          <li v-for="d in shown" :key="d.date" :class="{ off: !d.eligible }">
            <label class="check grow" :class="{ disabled: !d.eligible }">
              <input type="checkbox" :value="d.date" v-model="picked" :disabled="!d.eligible || !!data.setup_problem" />
              <span class="when num">{{ fmtDate(d.date, { weekday: "short", day: "numeric", month: "short" }) }}</span>
              <StatusBadge :tone="KIND_TONE[d.kind]" :label="d.kind === 'Holiday' ? d.label : d.kind" />
              <span class="small muted">{{ d.eligible ? `${d.attendance.status}${d.attendance.working_hours ? ` · ${(+d.attendance.working_hours).toFixed(1)} h` : ""}${d.half_day ? " · counts as ½ day" : ""}` : d.reason }}</span>
            </label>
          </li>
        </ul>
        <EmptyState v-else title="No eligible days" :text="`Days you worked on a weekly off, holiday or rest day in the last period (${fmtDate(data.from)} – ${fmtDate(data.to)}) appear here once attendance is marked.`" icon="calendar" />
      </section>

      <aside class="panel stack">
        <h2>Request</h2>
        <p class="big num">{{ total }} <span class="unit">day(s)</span></p>
        <div class="field" v-if="data.leave_types.length > 1"><label for="lt">{{ t("Leave type") }}</label>
          <select id="lt" class="select" v-model="leaveType"><option value="" disabled>Choose</option><option v-for="x in data.leave_types" :key="x">{{ x }}</option></select></div>
        <div class="field"><label for="rs">{{ t("Reason") }}</label><textarea id="rs" class="textarea" v-model="reason" maxlength="1000" placeholder="For example: covered the Eid shift at Sohar port" /></div>
        <p class="small muted" v-if="data.approver">Goes to {{ data.approver }} for approval. Approved days are added to your compensatory leave balance.</p>
        <p v-if="err" class="small bad" role="alert">{{ err }}</p>
        <button class="btn primary" :disabled="busy || !picked.length || !reason.trim() || (data.leave_types.length > 1 && !leaveType) || !!data.setup_problem" @click="submit">Send for approval</button>
        <p class="small muted">Consecutive full days are sent as one request; half days are sent separately.</p>
      </aside>
    </div>

    <section class="panel" v-if="mine?.length">
      <header><h2>My requests</h2></header>
      <ul class="list">
        <li v-for="r in mine" :key="r.name">
          <span class="grow"><span class="title">{{ fmtDate(r.work_from_date) }}<template v-if="r.work_end_date !== r.work_from_date"> – {{ fmtDate(r.work_end_date) }}</template></span>
            <span class="small muted"> · {{ r.days }} day(s) · {{ r.leave_type }}</span><br>
            <span class="small muted">{{ r.reason }}</span><br v-if="r.ess_review_comment"><span v-if="r.ess_review_comment" class="small">{{ r.ess_review_comment }}</span></span>
          <StatusBadge :status="r.status" />
          <button v-if="r.status === 'Pending'" class="btn ghost sm" @click="withdrawing = r">Withdraw</button>
        </li>
      </ul>
    </section>
    <ConfirmActionDialog :open="!!withdrawing" title="Withdraw this request?" confirm-label="Withdraw request" danger @close="withdrawing = null" @confirm="withdraw" />
  </div>
</template>

<style scoped>
.list li.off { opacity: .6; }
.check.disabled { cursor: default; }
.when { min-width: 96px; font-weight: 600; }
.big { font-size: var(--fs-2xl); font-weight: 600; letter-spacing: -0.02em; }
.unit { font-size: var(--fs-md); font-weight: 400; color: var(--ink-3); }
.note { padding: 10px 12px; border-radius: 8px; background: var(--saffron-soft); color: var(--saffron-ink); font-size: var(--fs-sm); }
.bad { color: var(--pom); }
</style>
