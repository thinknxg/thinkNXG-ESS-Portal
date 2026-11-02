<script setup lang="ts">
import { fmtTime } from "@/i18n";
defineProps<{ punches: any[]; coordinates?: boolean }>();
const osm = (lat: number, lng: number) => `https://www.openstreetmap.org/?mlat=${lat}&mlon=${lng}#map=18/${lat}/${lng}`;
</script>

<template>
  <ul class="punches">
    <li v-for="p in punches" :key="p.name" :class="(p.log_type || 'none').toLowerCase()">
      <span class="t num">{{ fmtTime(p.time) }}</span>
      <span class="lt">{{ p.log_type || "Punch" }}</span>
      <span class="src" :class="p.source.replace(/\W/g, '').toLowerCase()">{{ p.source }}<template v-if="p.source === 'Device' && p.device_id"> · {{ p.device_id }}</template></span>
      <span class="loc small muted" v-if="p.ess_location || p.ess_distance != null">{{ p.ess_location || "Located" }}<template v-if="p.ess_distance != null"> · {{ Math.round(p.ess_distance) }} m</template><template v-if="p.ess_accuracy"> · ±{{ Math.round(p.ess_accuracy) }} m</template></span>
      <a v-if="coordinates && p.latitude" class="small" :href="osm(p.latitude, p.longitude)" target="_blank" rel="noopener">Map</a>
      <span v-if="p.offshift" class="tag">Off-shift</span>
    </li>
  </ul>
</template>

<style scoped>
.punches { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 4px; }
.punches li { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; font-size: var(--fs-sm); padding: 4px 0; }
.t { font-weight: 600; min-width: 48px; }
.lt { min-width: 34px; font-weight: 500; }
.in .lt { color: var(--brand); } .out .lt { color: var(--ink-2); }
.src { padding: 1px 8px; border-radius: 10px; background: var(--surface-2); color: var(--ink-2); font-size: var(--fs-xs); }
.src.portal { background: var(--brand-soft); color: var(--brand); }
.src.device { background: var(--info-soft); color: var(--info); }
.tag { font-size: var(--fs-xs); color: var(--saffron-ink); }
</style>
