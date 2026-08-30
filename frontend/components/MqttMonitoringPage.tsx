/**
 * MQTT Monitoring Frontend (Issue #385) — page shell.
 *
 * PR1 surface:
 *   - Route-level guard (`MQTT_READ` or `ADMIN`) with `<Navigate to="/" replace/>`
 *     fallback (design decision #1 — matches the existing ITSM nav pattern in
 *     `App.tsx`; no new `ProtectedRoute` variant).
 *   - Tab host for Raw Readings + Bridge Status. The Mappings + Thresholds
 *     tabs (and their write controls, confirm modal, threshold form) belong
 *     to PR2 — the `MqttMappingsTab` placeholder is intentionally absent so
 *     PR1 reviewers do not see partial-write affordances.
 *
 * Permission layers (per design §Permission Gates):
 *   - Sidebar: `App.tsx` `NavItem` is wrapped in
 *     `hasPermission("MQTT_READ") || hasPermission("ADMIN")`.
 *   - Page: this component returns `<Navigate to="/" replace/>` before any
 *     `useMqtt*Query` runs so no `/api/mqtt/*` fetch fires on deny.
 *   - Control: write controls in PR2 will be wrapped in
 *     `hasPermission("MQTT_MAPPING_MANAGE") || hasPermission("ADMIN")`.
 */
import React, { useState } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import MqttRawReadingsTab from "./mqtt/MqttRawReadingsTab";
import MqttBridgeStatusTab from "./mqtt/MqttBridgeStatusTab";

type TabKey = "raw" | "status";

const TABS: Array<{ key: TabKey; label: string; icon: string }> = [
  { key: "raw", label: "Raw Readings", icon: "sensors" },
  { key: "status", label: "Bridge Status", icon: "cell_tower" },
];

const MqttMonitoringPage: React.FC = () => {
  const { hasPermission } = useAuth();
  const canReadMqtt = hasPermission("MQTT_READ") || hasPermission("ADMIN");

  // Hooks MUST be declared unconditionally (rules-of-hooks). We default the
  // active tab to "raw" before the guard so the order is stable; when the
  // guard fires we never read `activeTab` again because we redirect.
  const [activeTab, setActiveTab] = useState<TabKey>("raw");

  // Route-level guard: if the session lacks MQTT_READ (and is not ADMIN),
  // redirect to the landing page WITHOUT firing any `/api/mqtt/*` fetch.
  // Spec §Route and Nav Entry Gated by MQTT_READ / Scenario: Operator
  // without MQTT_READ is denied entry.
  if (!canReadMqtt) {
    return <Navigate to="/" replace />;
  }

  return (
    <div className="flex flex-col h-full w-full overflow-hidden bg-surface-950 text-neutral-200 font-sans">
      <header className="border-b border-white/5 px-8 py-6 glass">
        <div className="flex items-center gap-3">
          <span className="material-symbols-outlined text-3xl text-amber-400">cell_tower</span>
          <div>
            <h1 className="text-2xl font-black text-white tracking-tight uppercase">
              MQTT Monitoring
            </h1>
            <p className="text-xs text-neutral-500 mt-1">
              Raw, non-KPI telemetry only. Readings stay classified as{" "}
              <span className="font-bold text-amber-300">RAW_MQTT_NON_KPI</span> and never become
              KPI-eligible.
            </p>
          </div>
        </div>
      </header>

      <nav
        role="tablist"
        aria-label="MQTT Monitoring tabs"
        className="border-b border-white/5 px-8 flex items-center gap-2 bg-white/[0.02]"
      >
        {TABS.map((tab) => {
          const isActive = activeTab === tab.key;
          return (
            <button
              key={tab.key}
              role="tab"
              aria-selected={isActive}
              data-tab-key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`px-4 py-3 text-xs font-black uppercase tracking-widest transition-colors flex items-center gap-2 border-b-2 ${
                isActive
                  ? "text-amber-300 border-amber-400"
                  : "text-neutral-500 border-transparent hover:text-neutral-200"
              }`}
            >
              <span className="material-symbols-outlined text-sm">{tab.icon}</span>
              {tab.label}
            </button>
          );
        })}
      </nav>

      <main className="flex-1 min-h-0 overflow-auto custom-scrollbar p-8">
        {activeTab === "raw" && <MqttRawReadingsTab />}
        {activeTab === "status" && <MqttBridgeStatusTab />}
      </main>
    </div>
  );
};

export default MqttMonitoringPage;
