/**
 * MQTT Monitoring Frontend (Issue #385) — `RAW_MQTT_NON_KPI` badge.
 *
 * The badge is the load-bearing safety primitive for this feature: it makes
 * raw readings VISUALLY distinct from KPI cards on the System Dashboard and
 * from MqttMapping rows that are about to be approved.
 *
 * Spec §RAW_MQTT_NON_KPI Badge Always Visible:
 *   - The badge text MUST come from the payload's `classification` field.
 *   - The badge MUST also render a `kpi_eligible=false` indicator.
 *   - When the payload fields are missing or null, the badge MUST
 *     default-render `RAW_MQTT_NON_KPI` and `kpi_eligible=false` rather
 *     than omit itself.
 *
 * The component lives in its own file so PR1 reviewers can grep for the
 * badge contract directly, and so the badge is reusable from
 * `MqttRawReadingsTab` AND any future surface that displays raw readings.
 */
import React from "react";

export const RAW_MQTT_NON_KPI = "RAW_MQTT_NON_KPI";

export interface RawNonKpiBadgeProps {
  /** Raw payload classification. Defaults to `RAW_MQTT_NON_KPI`. */
  classification?: string | null;
  /** Raw payload `kpi_eligible` flag. Defaults to `false`. */
  kpiEligible?: boolean | null;
  /** Compact mode hides the textual `kpi_eligible=false` suffix. */
  compact?: boolean;
}

const RawNonKpiBadge: React.FC<RawNonKpiBadgeProps> = ({
  classification,
  kpiEligible,
  compact = false,
}) => {
  // Per spec §Missing payload fields default to non-KPI: any missing/null
  // classification falls back to the canonical `RAW_MQTT_NON_KPI` constant,
  // and any missing/null `kpi_eligible` falls back to `false`. We never
  // collapse the badge to null — the row must ALWAYS show non-KPI.
  const label = classification && classification.trim().length > 0
    ? classification
    : RAW_MQTT_NON_KPI;
  const eligible = kpiEligible === true;

  return (
    <span
      data-testid="raw-non-kpi-badge"
      data-classification={label}
      data-kpi-eligible={String(eligible)}
      className="inline-flex items-center gap-2 px-2 py-1 rounded-md text-[10px] font-black uppercase tracking-widest bg-amber-500/10 text-amber-300 border border-amber-500/30"
    >
      <span className="material-symbols-outlined text-xs">science</span>
      <span>{label}</span>
      {!compact && (
        <span
          className="font-mono text-[9px] opacity-80 normal-case tracking-normal"
          aria-label="kpi eligible"
        >
          kpi_eligible={String(eligible)}
        </span>
      )}
    </span>
  );
};

export default RawNonKpiBadge;
