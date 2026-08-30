/**
 * MQTT Monitoring Frontend (Issue #385) — placeholder for PR1.
 *
 * The full Raw Readings tab (devices list, expand-to-fetch-metrics,
 * Latest Readings panel with `<RawNonKpiBadge/>` on every row) lands in
 * WU3 (PR1 commit #3). This stub keeps the page imports resolvable and
 * gives reviewers a single landing diff for the route guard.
 */
import React from "react";

const MqttRawReadingsTab: React.FC = () => {
  return (
    <div className="border border-dashed border-white/10 rounded-xl p-12 text-center text-neutral-500">
      <p className="text-sm font-bold uppercase">Raw Readings tab — populated in WU3</p>
    </div>
  );
};

export default MqttRawReadingsTab;
