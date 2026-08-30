/**
 * MQTT Monitoring Frontend (Issue #385) — placeholder for PR1.
 *
 * The full Bridge Status tab (Running / Not Running / Not Configured
 * branches with reason_code, last_error, last_message_at, subscribed
 * patterns) lands in WU3 (PR1 commit #3). This stub keeps the page
 * imports resolvable.
 */
import React from "react";

const MqttBridgeStatusTab: React.FC = () => {
  return (
    <div className="border border-dashed border-white/10 rounded-xl p-12 text-center text-neutral-500">
      <p className="text-sm font-bold uppercase">Bridge Status tab — populated in WU3</p>
    </div>
  );
};

export default MqttBridgeStatusTab;
