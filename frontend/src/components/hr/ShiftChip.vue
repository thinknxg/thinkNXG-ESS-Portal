<script setup lang="ts">
defineProps<{ code?: string | null; color?: string | null; label?: string; rest?: boolean; size?: "sm" | "md" }>();
</script>

<template>
  <span class="chip" :class="[size || 'md', { rest }]" :style="color ? { '--sc': color } : undefined" :title="label">
    <b>{{ rest ? (code || "R") : code }}</b><span v-if="label" class="lbl">{{ label }}</span>
  </span>
</template>

<style scoped>
.chip { --sc: var(--ink-3); display: inline-flex; align-items: center; gap: 6px; max-width: 100%; }
.chip b { display: inline-grid; place-items: center; min-width: 26px; height: 22px; padding: 0 5px; border-radius: 6px; font-size: 12px; font-weight: 700;
  background: color-mix(in srgb, var(--sc) 16%, var(--surface)); color: color-mix(in srgb, var(--sc) 80%, var(--ink)); border: 1px solid color-mix(in srgb, var(--sc) 40%, transparent); }
.chip.rest b { background: var(--surface-2); color: var(--ink-3); border-color: var(--line); }
.chip.sm b { min-width: 22px; height: 20px; font-size: 11px; }
.lbl { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
