<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { useApprovalQueue } from "@/composables/hr";
import { useResource, invalidate } from "@/composables/useResource";
import { Approvals } from "@/services/endpoints";
import { fmtDate, fmtMoney, t } from "@/i18n";
import { useUi } from "@/stores/ui";
import { useOnline } from "@/composables/useOnline";
import type { ApprovalItem } from "@/types";
import PageHeader from "@/components/ui/PageHeader.vue";
import SegmentTabs from "@/components/ui/SegmentTabs.vue";
import StatusBadge from "@/components/ui/StatusBadge.vue";
import Avatar from "@/components/ui/Avatar.vue";
import AccessibleDialog from "@/components/ui/AccessibleDialog.vue";
import ConfirmActionDialog from "@/components/ui/ConfirmActionDialog.vue";
import EmptyState from "@/components/ui/EmptyState.vue";
import SkeletonLoader from "@/components/ui/SkeletonLoader.vue";
import ErrorState from "@/components/ui/ErrorState.vue";
import Meter from "@/components/hr/Meter.vue";

const route = useRoute();
const ui = useUi();
const online = useOnline();
const view = ref("pending");
const type = ref("all");
const { items, data, loading, error, reload } = useApprovalQueue();
const { data: history, reload: reloadHistory } = useResource<any[]>(() => "approvals:history", () => Approvals.history());
const { data: delegations, reload: reloadDel } = useResource<any[]>(() => "approvals:del", () => Approvals.delegations());
const selected = ref<Set<string>>(new Set());
const detail = ref<any>(null);
const confirm = ref<{ action: "approve" | "reject"; items: ApprovalItem[] } | null>(null);
const busy = ref(false);
const delOpen = ref(false);
const del = ref<any>({ delegate: null, from_date: "", to_date: "", include_leave: 1, include_expense: 1, include_attendance: 1, reason: "" });
const delQ = ref(""); const delPeople = ref<any[]>([]);

const LABEL: Record<string, string> = { leave: "Leave", expense: "Expenses", attendance: "Attendance", shift: "Shifts", roster: "Roster changes", comp_off: "Compensatory leave", profile: "Profile updates", document: "Documents" };
const tabs = computed(() => [{ value: "all", label: t("All"), count: items.value.length },
  ...Object.entries(data.value?.counts || {}).map(([k, n]) => ({ value: k, label: LABEL[k] || k, count: n as number }))]);
const shown = computed(() => items.value.filter((i) => type.value === "all" || i.type === type.value));
const key = (i: ApprovalItem) => `${i.doctype}::${i.name}`;
function toggle(i: ApprovalItem) { const k = key(i); const s = new Set(selected.value); s.has(k) ? s.delete(k) : s.add(k); selected.value = s; }
const chosen = computed(() => shown.value.filter((i) => selected.value.has(key(i))));

async function openDetail(i: ApprovalItem) { detail.value = { ...i, loading: true }; try { detail.value = await Approvals.detail(i.doctype, i.name); } catch (e: any) { ui.toast(e.message, "error"); detail.value = null; } }
watch(() => [route.query.open, items.value.length], () => {
  const o = route.query.open as string | undefined;
  if (o && items.value.length && !detail.value) { const it = items.value.find((i) => key(i) === o); if (it) openDetail(it); }
}, { immediate: true });

async function run(comment: string) {
  if (!confirm.value) return;
  busy.value = true;
  const { action, items: list } = confirm.value;
  try {
    if (list.length === 1) {
      await Approvals.act(list[0].doctype, list[0].name, action, comment);
      ui.toast(action === "approve" ? `Approved ${list[0].employee_name}'s request` : "Request rejected");
    } else {
      const r: any = await Approvals.bulk(list.map((i) => ({ doctype: i.doctype, name: i.name })), action, comment);
      const failed = r.results.filter((x: any) => !x.ok);
      ui.toast(failed.length ? `${r.results.length - failed.length} done, ${failed.length} could not be processed: ${failed[0].error}` : `${r.results.length} requests ${action === "approve" ? "approved" : "rejected"}`, failed.length ? "error" : "success");
    }
    selected.value = new Set(); confirm.value = null; detail.value = null;
    invalidate("approvals"); invalidate("inbox"); invalidate("dashboard"); reload(); reloadHistory();
  } catch (e: any) { ui.toast(e.message, "error"); } finally { busy.value = false; }
}
let tmr: number | undefined;
function findDelegate() { window.clearTimeout(tmr); tmr = window.setTimeout(async () => { delPeople.value = delQ.value.length > 1 ? await Approvals.colleagues(delQ.value) : []; }, 250); }
async function saveDel() {
  try { await Approvals.saveDelegation({ ...del.value, delegate: del.value.delegate.user_id }); ui.toast("Delegation saved"); delOpen.value = false; reloadDel(); }
  catch (e: any) { ui.toast(e.message, "error"); }
}
async function revoke(name: string) { await Approvals.revokeDelegation(name); reloadDel(); }
const ageTone = (d: number) => (d > 3 ? "bad" : d > 1 ? "warn" : "muted");
</script>

<template>
  <div class="page">
    <PageHeader :title="t('Approvals')" subtitle="Requests from your reporting line and anything delegated to you. Decisions apply in thinkNXG HR immediately.">
      <button class="btn" @click="delOpen = true">{{ t("Delegate approvals") }}</button>
    </PageHeader>
    <SegmentTabs v-model="view" :tabs="[{ value: 'pending', label: t('Pending'), count: items.length }, { value: 'history', label: t('History') }, { value: 'delegations', label: t('Delegations'), count: delegations?.filter((d: any) => d.is_active).length }]" />
    <ErrorState :error="error" @retry="reload" />

    <template v-if="view === 'pending'">
      <SegmentTabs v-if="tabs.length > 2" v-model="type" :tabs="tabs" label="Type" />
      <div class="bulk" v-if="chosen.length">
        <span class="grow"><strong class="num">{{ chosen.length }}</strong> selected</span>
        <button class="btn sm danger" :disabled="!online" @click="confirm = { action: 'reject', items: chosen }">{{ t("Reject") }}</button>
        <button class="btn sm primary" :disabled="!online" @click="confirm = { action: 'approve', items: chosen }">{{ t("Approve") }} {{ chosen.length }}</button>
      </div>
      <section class="panel">
        <SkeletonLoader v-if="loading && !data" :lines="6" />
        <ul class="list" v-else-if="shown.length">
          <li v-for="i in shown" :key="key(i)" class="appr">
            <label class="check"><input type="checkbox" :checked="selected.has(key(i))" @change="toggle(i)" :aria-label="`Select ${i.employee_name} ${i.title}`" /></label>
            <Avatar :name="i.employee_name" :size="34" />
            <button class="grow open" @click="openDetail(i)">
              <span class="title">{{ i.employee_name }}</span> <span class="muted">· {{ i.title }}</span>
              <br><span class="small muted">
                <template v-if="i.details.from_date">{{ fmtDate(i.details.from_date) }}<template v-if="i.details.to_date !== i.details.from_date"> – {{ fmtDate(i.details.to_date) }}</template></template>
                <template v-if="i.details.amount"> {{ fmtMoney(i.details.amount, i.details.currency) }}</template>
                <template v-if="i.delegated_from"> · delegated</template></span>
            </button>
            <StatusBadge :tone="ageTone(i.age_days)" :label="i.age_days ? `${i.age_days}d waiting` : 'Today'" />
            <div class="quick">
              <button class="btn sm" :disabled="!online" @click="confirm = { action: 'reject', items: [i] }">{{ t("Reject") }}</button>
              <button class="btn sm primary" :disabled="!online" @click="confirm = { action: 'approve', items: [i] }">{{ t("Approve") }}</button>
            </div>
          </li>
        </ul>
        <EmptyState v-else :title="t('Nothing waiting for you')" text="New requests from your team will appear here." icon="check" />
      </section>
    </template>

    <section v-else-if="view === 'history'" class="panel">
      <ul class="list" v-if="history?.length"><li v-for="(h, i) in history" :key="i"><span class="grow"><span class="title">{{ h.reference_doctype }} {{ h.reference_name }}</span><br><span class="small muted">{{ h.details }}</span></span><span class="small muted">{{ fmtDate(h.creation) }}</span></li></ul>
      <EmptyState v-else title="No decisions yet" icon="check" />
    </section>

    <section v-else class="panel">
      <ul class="list" v-if="delegations?.length">
        <li v-for="d in delegations" :key="d.name"><span class="grow"><span class="title">{{ d.delegator }} → {{ d.delegate }}</span><br><span class="small muted">{{ fmtDate(d.from_date) }} – {{ fmtDate(d.to_date) }}<template v-if="d.reason"> · {{ d.reason }}</template></span></span>
          <StatusBadge :status="d.is_active ? 'Active' : 'Ended'" :tone="d.is_active ? 'ok' : 'muted'" />
          <button v-if="d.is_active" class="btn ghost sm" @click="revoke(d.name)">End now</button></li>
      </ul>
      <EmptyState v-else title="No delegations" text="Going on leave? Hand your approvals to a colleague for those dates." icon="users" :action-label="t('Delegate approvals')" @action="delOpen = true" />
    </section>

    <AccessibleDialog :open="!!detail" :title="detail ? `${detail.employee_name} · ${detail.title}` : ''" wide @close="detail = null">
      <div v-if="detail && !detail.loading" class="stack">
        <p v-if="detail.details.reason || detail.details.explanation || detail.details.remark || detail.details.purpose" class="quote">“{{ detail.details.reason || detail.details.explanation || detail.details.remark || detail.details.purpose }}”</p>
        <div v-if="detail.balances" class="stack"><h3>Their leave balance</h3>
          <Meter v-for="b in detail.balances.filter((b: any) => b.leave_type === detail.details.leave_type)" :key="b.leave_type" :label="b.leave_type" :value="b.remaining" :max="b.allocated" :detail="`${b.remaining} left, ${detail.details.days} requested`" /></div>
        <div v-if="detail.team_overlap?.length"><h3>Also away then</h3><ul class="small"><li v-for="(o, i) in detail.team_overlap" :key="i">{{ o.employee_name }} — {{ fmtDate(o.from_date) }}–{{ fmtDate(o.to_date) }} ({{ o.status }})</li></ul></div>
        <table class="data" v-if="detail.lines"><thead><tr><th>{{ t("Date") }}</th><th>Type</th><th>{{ t("Description") }}</th><th class="n">{{ t("Amount") }}</th></tr></thead>
          <tbody><tr v-for="(l, i) in detail.lines" :key="i"><td>{{ fmtDate(l.date) }}</td><td>{{ l.type }}</td><td>{{ l.description }}</td><td class="n">{{ fmtMoney(l.amount, detail.details.currency) }}</td></tr></tbody></table>
        <div v-if="detail.attachments?.length"><h3>{{ t("Receipts") }}</h3><ul class="small"><li v-for="a in detail.attachments" :key="a.file_url"><a :href="a.file_url" target="_blank" rel="noopener">{{ a.file_name }}</a></li></ul></div>
        <ul v-if="detail.details.changes" class="small"><li v-for="c in detail.details.changes" :key="c.label">{{ c.label }} → <strong>{{ c.new }}</strong></li></ul>
      </div>
      <SkeletonLoader v-else />
      <template #footer>
        <button class="btn danger" :disabled="!online" @click="confirm = { action: 'reject', items: [detail] }">{{ t("Reject") }}</button>
        <button class="btn primary" :disabled="!online" @click="confirm = { action: 'approve', items: [detail] }">{{ t("Approve") }}</button>
      </template>
    </AccessibleDialog>

    <ConfirmActionDialog :open="!!confirm" :busy="busy"
      :title="confirm ? `${confirm.action === 'approve' ? t('Approve') : t('Reject')} ${confirm.items.length > 1 ? confirm.items.length + ' requests' : 'this request'}?` : ''"
      :confirm-label="confirm?.action === 'approve' ? t('Approve') : t('Reject')" :danger="confirm?.action === 'reject'"
      :require-comment="confirm?.action === 'reject'" :comment-label="confirm?.action === 'reject' ? 'Reason (shared with the employee)' : 'Comment (optional)'"
      @close="confirm = null" @confirm="run" />

    <AccessibleDialog :open="delOpen" :title="t('Delegate approvals')" @close="delOpen = false">
      <form id="dlg" class="stack" @submit.prevent="saveDel">
        <div class="field" v-if="!del.delegate"><label for="dq">Delegate to</label><input id="dq" class="input" v-model="delQ" @input="findDelegate" placeholder="Type a colleague's name" autocomplete="off" />
          <ul class="list" v-if="delPeople.length"><li v-for="p in delPeople" :key="p.name"><button type="button" class="btn ghost" @click="del.delegate = p; delPeople = []">{{ p.employee_name }} · {{ p.designation }}</button></li></ul></div>
        <p v-else class="row"><strong class="grow">{{ del.delegate.employee_name }}</strong><button type="button" class="btn ghost sm" @click="del.delegate = null">Change</button></p>
        <div class="form-grid"><div class="field"><label for="df">{{ t("From") }}</label><input id="df" type="date" class="input" v-model="del.from_date" required /></div>
          <div class="field"><label for="dt2">{{ t("To") }}</label><input id="dt2" type="date" class="input" v-model="del.to_date" :min="del.from_date" required /></div></div>
        <div class="row wrap"><label class="check"><input type="checkbox" v-model="del.include_leave" :true-value="1" :false-value="0" />Leave</label>
          <label class="check"><input type="checkbox" v-model="del.include_expense" :true-value="1" :false-value="0" />Expenses</label>
          <label class="check"><input type="checkbox" v-model="del.include_attendance" :true-value="1" :false-value="0" />Attendance & shifts</label></div>
        <div class="field"><label for="dr">{{ t("Reason") }}</label><input id="dr" class="input" v-model="del.reason" placeholder="Annual leave" /></div>
      </form>
      <template #footer><button class="btn" @click="delOpen = false">{{ t("Cancel") }}</button><button class="btn primary" form="dlg" :disabled="!del.delegate">Save delegation</button></template>
    </AccessibleDialog>
  </div>
</template>

<style scoped>
.bulk { position: sticky; top: calc(var(--header) + 8px); z-index: 5; display: flex; align-items: center; gap: 8px; padding: 10px 14px; border-radius: 12px; background: var(--ink); color: var(--paper); }
.bulk .btn:not(.primary) { background: transparent; color: var(--paper); border-color: color-mix(in srgb, var(--paper) 35%, transparent); }
.appr { flex-wrap: wrap; }
.open { border: 0; background: none; text-align: start; cursor: pointer; padding: 0; min-width: 200px; }
.open:hover .title { color: var(--brand); }
.quick { display: flex; gap: 6px; }
.quote { padding: 12px 14px; background: var(--surface-2); border-radius: 10px; }
@media (max-width: 640px) { .quick { width: 100%; } .quick .btn { flex: 1; } }
</style>
