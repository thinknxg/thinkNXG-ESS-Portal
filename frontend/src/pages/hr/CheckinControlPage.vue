<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useResource, invalidate } from "@/composables/useResource";
import { useGeolocation } from "@/composables/useGeolocation";
import { CheckinAdmin, HR } from "@/services/endpoints";
import { fmtDate, t } from "@/i18n";
import { useUi } from "@/stores/ui";
import PageHeader from "@/components/ui/PageHeader.vue";
import SegmentTabs from "@/components/ui/SegmentTabs.vue";
import ToggleSwitch from "@/components/ui/ToggleSwitch.vue";
import StatusBadge from "@/components/ui/StatusBadge.vue";
import AccessibleDialog from "@/components/ui/AccessibleDialog.vue";
import ShiftChip from "@/components/hr/ShiftChip.vue";
import SkeletonLoader from "@/components/ui/SkeletonLoader.vue";
import EmptyState from "@/components/ui/EmptyState.vue";

const ui = useUi();
const tab = ref("policy");
const { data: ov, reload } = useResource<any>(() => "ci:overview", () => CheckinAdmin.overview());
const v = ref<any>({});
watch(ov, (o) => { if (o) v.value = { ...o.values }; }, { immediate: true });
const editable = computed(() => !!ov.value?.can_edit);
const dirty = computed(() => ov.value && JSON.stringify(v.value) !== JSON.stringify(ov.value.values));
const ENFORCE = "Enforce global setting for everyone";

const effective = computed(() => {
  const x = v.value;
  const parts = [x.enable_checkin ? "Portal check-in enabled by default." : "Portal check-in disabled by default."];
  parts.push(x.checkin_policy_mode === ENFORCE ? "The global setting applies to everyone; employee rules are ignored." : "Employee-specific allow/deny rules can override the default.");
  if (x.require_geolocation) parts.push(x.geofence_enforcement === "Record location only"
    ? `GPS location recorded but not enforced; ${x.max_gps_accuracy} m accuracy limit.`
    : `GPS required; ${x.default_geofence_radius} m radius and ${x.max_gps_accuracy} m accuracy limit.`);
  else parts.push("GPS not required.");
  parts.push(x.enforce_shift_window ? "Check-in only during the assigned shift window." : "Check-in permitted outside shifts unless another policy restricts it.");
  if (!x.enforce_shift_window && !x.allow_checkin_without_shift) parts.push("People with no shift that day can't check in.");
  return parts.join(" ");
});
async function savePolicy() {
  try { const r: any = await CheckinAdmin.savePolicy(v.value); ui.toast(`Saved ${r.changed} change(s)`); invalidate("attendance"); reload(); }
  catch (e: any) { ui.toast(e.message, "error"); }
}

// locations
const { data: locs, reload: reloadLocs } = useResource<any>(() => "ci:locs", () => CheckinAdmin.locations());
const geo = useGeolocation();
const loc = ref<any>(null);
function editLoc(l?: any) { loc.value = l ? { ...l } : { location_name: "", latitude: null, longitude: null, radius: v.value.default_geofence_radius || 150, applies_to: "All Employees", is_active: 1 }; }
async function hereNow() { const f = await geo.locate(30, 15000); if (f) { loc.value.latitude = +f.latitude.toFixed(7); loc.value.longitude = +f.longitude.toFixed(7); ui.toast(`Captured, accurate to ±${f.accuracy} m`, "info"); } }
function fromShiftLocation(n: string) { const s = locs.value?.shift_locations.find((x: any) => x.name === n); if (s) Object.assign(loc.value, { shift_location: n, latitude: s.latitude, longitude: s.longitude, radius: s.checkin_radius || loc.value.radius, location_name: loc.value.location_name || s.location_name || n }); }
async function saveLoc() { try { await CheckinAdmin.saveLocation(loc.value); ui.toast("Location saved"); loc.value = null; reloadLocs(); reload(); } catch (e: any) { ui.toast(e.message, "error"); } }
const osm = (lat: number, lng: number) => `https://www.openstreetmap.org/?mlat=${lat}&mlon=${lng}#map=17/${lat}/${lng}`;

// overrides
const q = ref("");
const { data: ovs, reload: reloadOvs } = useResource<any[]>(() => `ci:ovs:${q.value}`, () => CheckinAdmin.overrides(q.value), { watch: [q] });
const ovr = ref<any>(null);
const empQ = ref(""); const empHits = ref<any[]>([]);
let tmr: number | undefined;
function searchEmp() { window.clearTimeout(tmr); tmr = window.setTimeout(async () => { empHits.value = empQ.value.length > 1 ? await HR.search(empQ.value) : []; }, 250); }
function editOvr(o?: any) {
  ovr.value = o ? { ...o, locations: [...(o.locations || [])] } : { employee: "", employee_name: "", checkin_access: "Inherit", gps_requirement: "Inherit", shift_window: "Inherit", radius_override: null, accuracy_override: null, location_mode: "Add to default locations", locations: [], valid_from: "", valid_until: "", reason: "", is_active: 1 };
  empQ.value = ""; empHits.value = [];
}
async function saveOvr() { try { await CheckinAdmin.saveOverride(ovr.value); ui.toast("Override saved"); ovr.value = null; reloadOvs(); reload(); } catch (e: any) { ui.toast(e.message, "error"); } }
async function removeOvr(o: any) { if (!confirm(`Remove the override for ${o.employee_name}?`)) return; await CheckinAdmin.removeOverride(o.employee); reloadOvs(); reload(); }
const ACCESS_TONE: Record<string, any> = { Allow: "ok", Deny: "bad", Inherit: "muted" };

// tester
const tQ = ref(""); const tHits = ref<any[]>([]); const tRes = ref<any>(null);
let tt: number | undefined;
function searchT() { window.clearTimeout(tt); tt = window.setTimeout(async () => { tHits.value = tQ.value.length > 1 ? await HR.search(tQ.value) : []; }, 250); }
async function test(e: any) { tHits.value = []; tQ.value = e.employee_name; tRes.value = await CheckinAdmin.resolveFor(e.name); }
</script>

<template>
  <div class="page">
    <PageHeader title="Check-in control" subtitle="Who can check in from the ESS portal, from where, and when.">
      <RouterLink to="/hr/checkin-log" class="btn">Check-in audit</RouterLink>
    </PageHeader>
    <SegmentTabs v-model="tab" :tabs="[{ value: 'policy', label: 'Global policy' }, { value: 'locations', label: 'Locations', count: ov?.counts.locations }, { value: 'overrides', label: 'Employee overrides', count: ov?.counts.overrides }, { value: 'test', label: 'Check an employee' }, { value: 'roster', label: 'Roster, records & leave' }]" />
    <SkeletonLoader v-if="!ov" :lines="8" />

    <template v-else-if="tab === 'policy'">
      <div class="cols">
        <section class="panel">
          <ToggleSwitch id="g1" v-model="v.enable_checkin" label="Global employee check-in" hint="Default permission for portal users." :disabled="!editable" />
          <div class="radio-block">
            <p class="l">Employee permission policy</p>
            <label class="radio"><input type="radio" v-model="v.checkin_policy_mode" value="Allow employee-specific overrides" :disabled="!editable" />Allow employee-specific overrides</label>
            <label class="radio"><input type="radio" v-model="v.checkin_policy_mode" :value="ENFORCE" :disabled="!editable" />Enforce global setting for everyone</label>
          </div>
          <ToggleSwitch id="g2" v-model="v.require_geolocation" label="Require GPS verification" hint="Capture location before accepting check-in." :disabled="!editable" />
          <template v-if="v.require_geolocation">
            <div class="sub">
              <div class="field"><label for="g3">Allowed geofence radius</label>
                <div class="row"><input id="g3" type="range" min="25" max="1000" step="25" v-model.number="v.default_geofence_radius" :disabled="!editable" class="grow" /><span class="num val">{{ v.default_geofence_radius }} m</span></div>
                <span class="hint">Default for locations without their own radius.</span></div>
              <div class="field"><span class="lbl">Maximum GPS accuracy uncertainty</span>
                <div class="seg" role="radiogroup" aria-label="Maximum GPS accuracy uncertainty">
                  <button v-for="a in [25, 50, 100]" :key="a" role="radio" :aria-checked="v.max_gps_accuracy === a" :class="{ on: v.max_gps_accuracy === a }" :disabled="!editable" @click="v.max_gps_accuracy = a">{{ a }} m</button>
                </div></div>
              <div class="field"><label for="g4">Enforcement</label><select id="g4" class="select" v-model="v.geofence_enforcement" :disabled="!editable"><option>Enforce geofence</option><option>Record location only</option></select></div>
              <div class="row wrap">
                <label class="check"><input type="checkbox" v-model="v.use_shift_location" :true-value="1" :false-value="0" :disabled="!editable" />Use Shift Location on assignments</label>
                <label class="check"><input type="checkbox" v-model="v.use_ess_locations" :true-value="1" :false-value="0" :disabled="!editable" />Use ESS check-in locations</label>
              </div>
            </div>
          </template>
          <ToggleSwitch id="g5" v-model="v.enforce_shift_window" label="Allow check-in only during assigned shift window" hint="The window uses each Shift Type's early check-in and late check-out times." :disabled="!editable" />
          <div class="sub" v-if="v.enforce_shift_window">
            <div class="form-grid">
              <div class="field"><label for="g6">Default minutes before start</label><input id="g6" type="number" class="input" v-model.number="v.shift_window_early_minutes" :disabled="!editable" /></div>
              <div class="field"><label for="g7">Default minutes after end</label><input id="g7" type="number" class="input" v-model.number="v.shift_window_late_minutes" :disabled="!editable" /></div>
            </div><span class="hint">Used only when the Shift Type doesn't set its own.</span>
          </div>
          <ToggleSwitch id="g8" v-model="v.allow_checkin_without_shift" label="Allow check-in on days without a shift" :disabled="!editable" />
          <ToggleSwitch id="g9" v-model="v.flag_location_risk" label="Flag suspicious locations" hint="Unrealistic accuracy, impossible travel and coordinates replayed from other days." :disabled="!editable" />
          <ToggleSwitch v-if="v.flag_location_risk" id="g10" v-model="v.block_high_risk_checkins" label="Block high-risk check-ins" :disabled="!editable" />
          <div class="form-grid" style="margin-top: 8px">
            <div class="field"><label for="g11">Minutes between punches</label><input id="g11" type="number" class="input" v-model.number="v.checkin_cooldown_minutes" :disabled="!editable" /></div>
            <div class="field"><label for="g12">Attempts per hour per person</label><input id="g12" type="number" class="input" v-model.number="v.checkin_rate_limit_per_hour" :disabled="!editable" /></div>
          </div>
          <div class="row save-row" v-if="editable"><button class="btn primary" :disabled="!dirty" @click="savePolicy">{{ t("Save") }}</button><button class="btn ghost" :disabled="!dirty" @click="v = { ...ov.values }">Discard</button></div>
          <p v-else class="small muted">Only HR Managers and ESS Portal Admins can change these settings.</p>
        </section>
        <aside class="stack">
          <section class="panel effective">
            <h2>Effective policy</h2>
            <p>{{ effective }}</p>
          </section>
          <section class="panel tight note">
            <h3>Other attendance channels aren't affected</h3>
            <p class="small">These rules only govern punches from the ESS portal. Biometric devices posting to the Employee Checkin API, and HR staff working in Desk, keep their own access.</p>
          </section>
          <section class="panel tight note warn" v-if="ov.native_geolocation_tracking">
            <h3>thinkNXG HR geolocation tracking is on</h3>
            <p class="small">HR Settings also checks each check-in against the Shift Location radius. An ESS exemption or extra ESS location can't override that rule; turn it off in HR Settings if ESS should decide.</p>
          </section>
          <section class="panel tight note">
            <h3>About GPS</h3>
            <p class="small">Browsers share location only over HTTPS and only with the employee's permission. Coordinates are re-checked on the server, but a phone's reported location can't prove physical presence. Use risk flags and the audit log to review unusual patterns.</p>
          </section>
          <section class="panel tight"><dl class="kv"><div><dt>Denied, last 7 days</dt><dd>{{ ov.counts.denied_7d }}</dd></div><div><dt>High risk, last 7 days</dt><dd>{{ ov.counts.high_risk_7d }}</dd></div></dl></section>
        </aside>
      </div>
    </template>

    <section v-else-if="tab === 'locations'" class="panel">
      <header><h2>Permitted check-in locations</h2><button v-if="editable" class="btn sm primary" @click="editLoc()">Add location</button></header>
      <div class="table-wrap" v-if="locs?.locations.length">
        <table class="data"><thead><tr><th>Location</th><th class="n">Radius</th><th>Applies to</th><th>Coordinates</th><th></th></tr></thead>
          <tbody><tr v-for="l in locs.locations" :key="l.name" :class="{ off: !l.is_active }">
            <td><strong>{{ l.location_name }}</strong><br><span class="small muted">{{ l.shift_location ? `Linked to ${l.shift_location}` : l.address }}</span></td>
            <td class="n">{{ l.radius }} m</td>
            <td>{{ l.applies_to }}<span class="small muted" v-if="l.company || l.branch || l.department"> · {{ l.company || l.branch || l.department }}</span></td>
            <td class="small num"><a :href="osm(l.latitude, l.longitude)" target="_blank" rel="noopener">{{ (+l.latitude).toFixed(5) }}, {{ (+l.longitude).toFixed(5) }}</a></td>
            <td><StatusBadge v-if="!l.is_active" tone="muted" label="Inactive" /><button v-if="editable" class="btn ghost sm" @click="editLoc(l)">Edit</button></td></tr></tbody></table>
      </div>
      <EmptyState v-else title="No ESS locations yet" text="Add your offices and sites. Shift Locations on assignments are also used when that option is on." icon="pin" />
      <p class="small muted" v-if="locs?.shift_locations?.length">{{ locs.shift_locations.length }} thinkNXG HR Shift Location(s) exist and can be used through Shift Assignments.</p>
    </section>

    <section v-else-if="tab === 'overrides'" class="panel">
      <header><h2>Employee overrides</h2><button v-if="editable" class="btn sm primary" @click="editOvr()">Add override</button></header>
      <p v-if="v.checkin_policy_mode === ENFORCE" class="note-inline small">The global policy is set to “Enforce global setting for everyone”, so these overrides are currently ignored.</p>
      <input class="input" v-model.lazy="q" placeholder="Search employees" aria-label="Search overrides" style="margin-bottom: 10px" />
      <ul class="list" v-if="ovs?.length">
        <li v-for="o in ovs" :key="o.name">
          <span class="grow"><span class="title">{{ o.employee_name }}</span> <span class="small muted">{{ o.employee }}</span>
            <br><span class="small muted">{{ o.reason }}<template v-if="o.valid_until"> · until {{ fmtDate(o.valid_until) }}</template></span></span>
          <StatusBadge :tone="ACCESS_TONE[o.checkin_access]" :label="`Check-in: ${o.checkin_access}`" />
          <StatusBadge v-if="o.gps_requirement !== 'Inherit'" :tone="o.gps_requirement === 'Exempt' ? 'warn' : 'info'" :label="`GPS: ${o.gps_requirement}`" />
          <StatusBadge v-if="o.shift_window !== 'Inherit'" tone="info" :label="`Window: ${o.shift_window}`" />
          <StatusBadge v-if="!o.is_active" tone="muted" label="Inactive" />
          <button v-if="editable" class="btn ghost sm" @click="editOvr(o)">Edit</button>
          <button v-if="editable" class="btn ghost sm" @click="removeOvr(o)">Remove</button>
        </li>
      </ul>
      <EmptyState v-else title="No overrides" text="Everyone follows the global policy." icon="users" />
    </section>

    <section v-else-if="tab === 'test'" class="panel stack">
      <div class="field"><label for="tq">Employee</label><input id="tq" class="input" v-model="tQ" @input="searchT" placeholder="Type a name" autocomplete="off" />
        <ul class="list pick" v-if="tHits.length"><li v-for="e in tHits" :key="e.name"><button class="rowlink plain" @click="test(e)">{{ e.employee_name }} <span class="small muted">{{ e.name }} · {{ e.department }}</span></button></li></ul></div>
      <template v-if="tRes">
        <div class="effective"><h2>{{ tRes.employee.employee_name }}</h2><p>{{ tRes.summary }}</p></div>
        <p v-if="!tRes.has_portal_user" class="small warn">This employee has no linked user, so they can't use the portal at all.</p>
        <div class="cols-2">
          <div><h3>How this was decided</h3><ol class="trace"><li v-for="(x, i) in tRes.policy.trace" :key="i">{{ x }}</li></ol></div>
          <div><h3>Today</h3>
            <p v-if="tRes.today.shifts.length"><span v-for="s in tRes.today.shifts" :key="s.start_dt" class="row"><ShiftChip :code="s.code" :color="s.color" :label="s.shift_type" /> <span class="num small">{{ s.start }}–{{ s.end }}</span></span></p>
            <p v-else class="muted small">{{ tRes.today.rest_day ? "Rest day" : tRes.today.holiday ? tRes.today.holiday.description : "No shift" }}</p>
            <p class="small">Shift window {{ tRes.window_open ? "open now" : "closed now" }}.</p>
            <h3>Permitted locations</h3>
            <ul class="small" v-if="tRes.locations.length"><li v-for="l in tRes.locations" :key="l.name"><a :href="osm(l.latitude, l.longitude)" target="_blank" rel="noopener">{{ l.name }}</a> · {{ l.radius }} m · {{ l.source }}</li></ul>
            <p v-else class="small" :class="tRes.policy.gps_required && tRes.policy.enforce_geofence ? 'bad' : 'muted'">None. {{ tRes.policy.gps_required && tRes.policy.enforce_geofence ? "Check-in will be refused until a location applies." : "" }}</p></div>
        </div>
      </template>
    </section>

    <section v-else class="panel stack">
      <ToggleSwitch id="r0" v-model="v.enable_roster" label="Roster module" hint="My Roster for employees and the roster planner for managers." :disabled="!editable" />
      <div class="form-grid">
        <div class="field"><label for="r1">Minimum rest between shifts (hours)</label><input id="r1" type="number" step="0.5" class="input" v-model.number="v.roster_min_rest_hours" :disabled="!editable" /></div>
        <div class="field"><label for="r2">Maximum consecutive working days</label><input id="r2" type="number" class="input" v-model.number="v.roster_max_consecutive_days" :disabled="!editable" /></div>
        <div class="field"><label for="r3">Maximum weekly hours</label><input id="r3" type="number" class="input" v-model.number="v.roster_max_weekly_hours" :disabled="!editable" /></div>
        <div class="field"><label for="r4">Week starts on</label><select id="r4" class="select" v-model="v.roster_week_start" :disabled="!editable"><option>Sunday</option><option>Monday</option><option>Saturday</option></select></div>
      </div>
      <p class="small muted">These are planner checks. Set them to your own working-time policy; they warn but don't stop publishing.</p>
      <ToggleSwitch id="r5" v-model="v.allow_roster_change_requests" label="Employees can request roster changes" :disabled="!editable" />
      <ToggleSwitch id="r6" v-model="v.allow_shift_swaps" label="Employees can request swaps with colleagues" :disabled="!editable" />
      <div class="field" style="max-width: 280px"><label for="r7">Notice required (hours)</label><input id="r7" type="number" class="input" v-model.number="v.roster_change_notice_hours" :disabled="!editable" /></div>
      <ToggleSwitch id="r8" v-model="v.roster_notify_on_publish" label="Notify people when their roster is published or changes" :disabled="!editable" />
      <ToggleSwitch id="r9" v-model="v.roster_auto_weekly_off" label="Mark weekly offs from holiday lists" hint="New rosters, added people, patterns and copies keep each person's weekly offs as rest days." :disabled="!editable" />

      <h2 class="sect">Past roster days</h2>
      <div class="form-grid">
        <div class="field"><label for="b1">Allow past-day changes for (days)</label><input id="b1" type="number" min="0" max="366" class="input" v-model.number="v.roster_backdate_days" :disabled="!editable" /><span class="hint">0 turns past-day changes off for everyone.</span></div>
        <div class="field"><label for="b2">Roles allowed to change past days</label><textarea id="b2" class="textarea" rows="3" v-model="v.roster_backdate_roles" :disabled="!editable" /><span class="hint">One role per line. System Managers and ESS Portal Admins are always allowed; assign "ESS Roster Backdate" to others who need it.</span></div>
      </div>
      <p class="small muted">Days with submitted attendance and manual shift assignments are never changed by a past-day publish.</p>

      <h2 class="sect">Check-in records</h2>
      <ToggleSwitch id="c1" v-model="v.show_own_checkins" label="Employees can see their own check-in records" :disabled="!editable" />
      <div class="form-grid">
        <div class="field"><label for="c2">Managers can see check-ins of</label><select id="c2" class="select" v-model="v.manager_checkin_visibility" :disabled="!editable"><option>Direct and indirect reports</option><option>Direct reports only</option><option>None</option></select></div>
        <div class="field"><label for="c3">Show raw GPS coordinates to</label><select id="c3" class="select" v-model="v.checkin_coordinates_visible_to" :disabled="!editable"><option>HR only</option><option>HR and managers</option></select></div>
        <div class="field"><label for="c4">Maximum days per query</label><input id="c4" type="number" min="1" max="92" class="input" v-model.number="v.checkin_records_max_days" :disabled="!editable" /></div>
      </div>
      <p class="small muted">HR sees records within their HR scope. Records from every channel are shown: portal, attendance devices and Desk.</p>

      <h2 class="sect">Compensatory leave</h2>
      <ToggleSwitch id="o1" v-model="v.enable_comp_off" label="Employees can request compensatory leave" :disabled="!editable" />
      <div class="form-grid">
        <div class="field"><label for="o2">Claim worked days from the last (days)</label><input id="o2" type="number" min="1" max="366" class="input" v-model.number="v.comp_off_window_days" :disabled="!editable" /></div>
        <div class="field"><label for="o3">Minimum worked hours</label><input id="o3" type="number" min="0" max="24" step="0.5" class="input" v-model.number="v.comp_off_min_hours" :disabled="!editable" /><span class="hint">0 accepts any Present, Work From Home or Half Day attendance.</span></div>
      </div>
      <ToggleSwitch id="o4" v-model="v.comp_off_allow_roster_rest_days" label="Roster rest days are eligible" hint="By default thinkNXG HR only accepts holiday-list days; this extends it to published roster rest days." :disabled="!editable" />
      <p class="small muted">Requests need a Leave Type marked "Is Compensatory" and an active Leave Period. Approvers are the employee's leave approver, or their manager.</p>
      <div class="row" v-if="editable"><button class="btn primary" :disabled="!dirty" @click="savePolicy">{{ t("Save") }}</button></div>
    </section>

    <AccessibleDialog :open="!!loc" :title="loc?.name ? 'Edit location' : 'Add location'" wide @close="loc = null">
      <form v-if="loc" id="lf" class="stack" @submit.prevent="saveLoc">
        <div class="form-grid">
          <div class="field"><label for="ln">Name</label><input id="ln" class="input" v-model="loc.location_name" :disabled="!!loc.name" required /></div>
          <div class="field" v-if="locs?.shift_locations?.length"><label for="ls">Copy from Shift Location</label>
            <select id="ls" class="select" :value="loc.shift_location || ''" @change="fromShiftLocation(($event.target as HTMLSelectElement).value)"><option value="">—</option><option v-for="s in locs.shift_locations" :key="s.name" :value="s.name">{{ s.location_name || s.name }}</option></select></div>
        </div>
        <div class="form-grid">
          <div class="field"><label for="la">Latitude</label><input id="la" class="input num" type="number" step="0.0000001" v-model.number="loc.latitude" required /></div>
          <div class="field"><label for="lo">Longitude</label><input id="lo" class="input num" type="number" step="0.0000001" v-model.number="loc.longitude" required /></div>
          <div class="field"><label for="lr">Radius (m)</label><input id="lr" class="input num" type="number" min="10" max="5000" v-model.number="loc.radius" required /></div>
        </div>
        <div class="row wrap"><button type="button" class="btn sm" @click="hereNow" :disabled="geo.state.value === 'locating'">{{ geo.state.value === "locating" ? "Locating…" : "Use my current location" }}</button>
          <a v-if="loc.latitude && loc.longitude" class="small" :href="osm(loc.latitude, loc.longitude)" target="_blank" rel="noopener">Check on the map</a>
          <span v-if="geo.message.value" class="small warn">{{ geo.message.value }}</span></div>
        <div class="form-grid">
          <div class="field"><label for="lp">Applies to</label><select id="lp" class="select" v-model="loc.applies_to"><option>All Employees</option><option>Company</option><option>Branch</option><option>Department</option><option>Selected Employees Only</option></select></div>
          <div class="field" v-if="['Company', 'Branch', 'Department'].includes(loc.applies_to)"><label for="lv">{{ loc.applies_to }}</label><input id="lv" class="input" v-model="loc[loc.applies_to.toLowerCase()]" required /></div>
        </div>
        <div class="field"><label for="lad">Address</label><input id="lad" class="input" v-model="loc.address" /></div>
        <label class="check"><input type="checkbox" v-model="loc.is_active" :true-value="1" :false-value="0" />Active</label>
      </form>
      <template #footer><button class="btn" @click="loc = null">{{ t("Cancel") }}</button><button class="btn primary" form="lf">{{ t("Save") }}</button></template>
    </AccessibleDialog>

    <AccessibleDialog :open="!!ovr" :title="ovr?.employee_name ? `Override for ${ovr.employee_name}` : 'Add override'" wide @close="ovr = null">
      <form v-if="ovr" id="of" class="stack" @submit.prevent="saveOvr">
        <div class="field" v-if="!ovr.name"><label for="oe">Employee</label>
          <input v-if="!ovr.employee" id="oe" class="input" v-model="empQ" @input="searchEmp" placeholder="Type a name" autocomplete="off" />
          <p v-else class="row"><strong class="grow">{{ ovr.employee_name }}</strong><button type="button" class="btn ghost sm" @click="ovr.employee = ''">Change</button></p>
          <ul class="list pick" v-if="empHits.length && !ovr.employee"><li v-for="e in empHits" :key="e.name"><button type="button" class="rowlink plain" @click="ovr.employee = e.name; ovr.employee_name = e.employee_name; empHits = []">{{ e.employee_name }} <span class="small muted">{{ e.name }}</span></button></li></ul></div>
        <div class="form-grid">
          <div class="field"><label for="oa">Portal check-in</label><select id="oa" class="select" v-model="ovr.checkin_access"><option>Inherit</option><option>Allow</option><option>Deny</option></select></div>
          <div class="field"><label for="og">GPS verification</label><select id="og" class="select" v-model="ovr.gps_requirement"><option>Inherit</option><option>Required</option><option>Exempt</option></select></div>
          <div class="field"><label for="ow">Shift window</label><select id="ow" class="select" v-model="ovr.shift_window"><option>Inherit</option><option>Enforce</option><option>Don't enforce</option></select></div>
          <div class="field"><label for="or">Radius override (m)</label><input id="or" type="number" class="input" v-model.number="ovr.radius_override" placeholder="Default" /></div>
          <div class="field"><label for="oc">Accuracy limit override (m)</label><input id="oc" type="number" class="input" v-model.number="ovr.accuracy_override" placeholder="Default" /></div>
        </div>
        <div class="field"><label for="om">Locations</label><select id="om" class="select" v-model="ovr.location_mode"><option>Add to default locations</option><option>Only these locations</option></select>
          <div class="people"><label v-for="l in locs?.locations || []" :key="l.name" class="check"><input type="checkbox" :value="l.name" v-model="ovr.locations" />{{ l.location_name }} <span class="small muted">{{ l.radius }} m</span></label></div></div>
        <div class="form-grid">
          <div class="field"><label for="of1">Valid from</label><input id="of1" type="date" class="input" v-model="ovr.valid_from" /></div>
          <div class="field"><label for="of2">Valid until</label><input id="of2" type="date" class="input" v-model="ovr.valid_until" :min="ovr.valid_from" /></div>
        </div>
        <div class="field"><label for="ors">Reason *</label><input id="ors" class="input" v-model="ovr.reason" required placeholder="Field engineer working across client sites" /></div>
        <label class="check"><input type="checkbox" v-model="ovr.is_active" :true-value="1" :false-value="0" />Active</label>
        <p class="small muted">Every change is recorded in the audit trail.</p>
      </form>
      <template #footer><button class="btn" @click="ovr = null">{{ t("Cancel") }}</button><button class="btn primary" form="of" :disabled="!ovr?.employee || !ovr?.reason">{{ t("Save") }}</button></template>
    </AccessibleDialog>
  </div>
</template>

<style scoped>
.radio-block { padding: 12px 0; border-top: 1px solid var(--line); }
.radio-block .l, .lbl { font-weight: 500; display: block; margin-bottom: 6px; }
.radio { display: flex; align-items: center; gap: 8px; min-height: 32px; cursor: pointer; }
.radio input { accent-color: var(--brand); width: 18px; height: 18px; }
.sub { padding: 4px 0 14px 16px; border-inline-start: 2px solid var(--brand-soft); margin-inline-start: 4px; display: flex; flex-direction: column; gap: 12px; }
.val { min-width: 64px; text-align: end; font-weight: 600; }
.seg { display: inline-flex; align-self: flex-start; border: 1px solid var(--line-strong); border-radius: 10px; overflow: hidden; }
.seg button { border: 0; background: var(--surface); padding: 8px 16px; cursor: pointer; font-weight: 500; }
.seg button + button { border-inline-start: 1px solid var(--line-strong); }
.seg button.on { background: var(--brand); color: #fff; }
.save-row { margin-top: 14px; padding-top: 14px; border-top: 1px solid var(--line); }
.effective { border-inline-start: 4px solid var(--brand); }
.effective h2 { font-size: var(--fs-md); margin-bottom: 6px; }
.effective p { line-height: 1.6; }
.note h3 { font-size: var(--fs-sm); margin-bottom: 4px; }
.note.warn { background: var(--saffron-soft); border-color: transparent; }
.note.warn h3, .note.warn p { color: var(--saffron-ink); }
.note-inline { padding: 8px 12px; border-radius: 8px; background: var(--saffron-soft); color: var(--saffron-ink); }
.kv { margin: 0; display: grid; grid-template-columns: 1fr 1fr; gap: 10px; } dt { font-size: var(--fs-xs); color: var(--ink-3); } dd { margin: 0; font-size: var(--fs-xl); font-weight: 600; }
tr.off td { opacity: .55; }
.trace { padding-inline-start: 18px; margin: 6px 0; font-size: var(--fs-sm); display: flex; flex-direction: column; gap: 4px; }
.pick { border: 1px solid var(--line); border-radius: 8px; padding: 0 8px; }
.plain { border: 0; background: none; cursor: pointer; text-align: start; padding: 0; }
.people { max-height: 180px; overflow-y: auto; border: 1px solid var(--line); border-radius: 8px; padding: 6px 10px; display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); margin-top: 6px; }
.warn { color: var(--saffron-ink); } .bad { color: var(--pom); }
h3 { font-size: var(--fs-sm); margin: 10px 0 4px; }
.sect { font-size: var(--fs-md); margin-top: 18px; padding-top: 16px; border-top: 1px solid var(--line); }
</style>
