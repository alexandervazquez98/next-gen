/**
 * MQTT Monitoring Frontend (Issue #385) — Raw Readings tab.
 *
 * PR1 surface:
 *   - Lists every raw device from `GET /api/mqtt/devices`.
 *   - Expanding a row fetches per-device metrics via
 *     `useMqttDeviceMetricsQuery(deviceId, { enabled })` so the request
 *     fires only after the operator expands.
 *   - "Latest Readings" panel polls `GET /api/mqtt/readings?limit=100`
 *     every 5 seconds (matches the design's status cadence).
 *   - Every reading row renders `<RawNonKpiBadge/>` with the payload's
 *     `classification` + `kpiEligible` fields. The badge defaults to
 *     `RAW_MQTT_NON_KPI` when those fields are missing.
 *
 * The tab deliberately exposes no "mark as KPI" affordance. Spec §No "Mark
 * as KPI" Affordance is enforced both here (no button rendered) and at the
 * page level via the `MqttMonitoringPage` test regex.
 */
import React, { useState } from "react";
import {
  useMqttDevicesQuery,
  useMqttDeviceMetricsQuery,
  useMqttReadingsQuery,
} from "../../hooks/queries/useMqttQueries";
import RawNonKpiBadge, { RAW_MQTT_NON_KPI } from "./RawNonKpiBadge";
import type {
  MqttRawDeviceResponse,
  MqttRawMetricResponse,
} from "../../types";

const formatLastSeen = (value?: string | null) => {
  if (!value) return "never";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
};

const formatLastValue = (value: MqttRawMetricResponse["last_value"]) => {
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return value ? "true" : "false";
  return String(value);
};

const DeviceRow: React.FC<{ device: MqttRawDeviceResponse }> = ({ device }) => {
  const [open, setOpen] = useState(false);
  const metricsQuery = useMqttDeviceMetricsQuery(open ? device.device_id : null);

  const mapped = device.mapped_metrics_count ?? 0;
  const unmapped = device.unmapped_metrics_count ?? 0;
  const total = mapped + unmapped;

  return (
    <div
      data-testid="mqtt-device-row"
      data-device-id={device.device_id}
      className="border border-white/5 rounded-xl bg-white/[0.02] overflow-hidden"
    >
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between px-5 py-4 text-left hover:bg-white/5 transition-colors"
      >
        <div className="flex items-center gap-4 min-w-0">
          <span className="material-symbols-outlined text-amber-300">
            {open ? "expand_less" : "expand_more"}
          </span>
          <div className="min-w-0">
            <div className="flex items-center gap-3">
              <p className="font-bold text-white truncate">{device.name ?? device.device_id}</p>
              <span className="text-[10px] font-mono text-neutral-500">{device.device_id}</span>
            </div>
            <p className="text-[10px] text-neutral-500 uppercase tracking-widest mt-0.5">
              Last seen {formatLastSeen(device.last_seen)}
              {device.source_topic ? ` · topic ${device.source_topic}` : ""}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-[10px] font-black uppercase tracking-widest text-emerald-300 bg-emerald-500/10 border border-emerald-500/30 px-2 py-1 rounded">
            {mapped} mapped
          </span>
          <span className="text-[10px] font-black uppercase tracking-widest text-neutral-300 bg-neutral-500/10 border border-neutral-500/30 px-2 py-1 rounded">
            {unmapped} unmapped
          </span>
          <span className="text-[10px] font-black uppercase tracking-widest text-neutral-500">
            {total} total
          </span>
        </div>
      </button>

      {open && (
        <div className="border-t border-white/5 px-5 py-4 bg-surface-900">
          {metricsQuery.isLoading && (
            <p className="text-xs text-neutral-500">Loading metrics…</p>
          )}
          {metricsQuery.error && (
            <p className="text-xs text-red-400">Failed to load metrics.</p>
          )}
          {metricsQuery.data && metricsQuery.data.length === 0 && (
            <p className="text-xs text-neutral-500">No metrics for this device.</p>
          )}
          {metricsQuery.data && metricsQuery.data.length > 0 && (
            <table className="w-full text-left text-xs">
              <thead className="text-[10px] uppercase tracking-widest text-neutral-500">
                <tr>
                  <th className="py-2 pr-3">Metric</th>
                  <th className="py-2 pr-3">Last value</th>
                  <th className="py-2 pr-3">Last ts</th>
                  <th className="py-2 pr-3">Mapping</th>
                  <th className="py-2 pr-3">Classification</th>
                </tr>
              </thead>
              <tbody>
                {metricsQuery.data.map((metric) => (
                  <tr key={metric.metric_id} className="border-t border-white/5">
                    <td className="py-2 pr-3 font-bold text-white">{metric.name ?? metric.metric_id}</td>
                    <td className="py-2 pr-3 font-mono text-neutral-200">
                      {formatLastValue(metric.last_value)}
                      {metric.unit ? <span className="text-neutral-500 ml-1">{metric.unit}</span> : null}
                    </td>
                    <td className="py-2 pr-3 text-neutral-400">
                      {formatLastSeen(metric.last_ts)}
                    </td>
                    <td className="py-2 pr-3 text-neutral-300">
                      {metric.mapping_status ?? "UNMAPPED"}
                    </td>
                    <td className="py-2 pr-3">
                      <RawNonKpiBadge
                        classification={metric.classification}
                        kpiEligible={metric.kpi_eligible}
                        compact
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
};

const LatestReadingsPanel: React.FC = () => {
  const readingsQuery = useMqttReadingsQuery({ limit: 100, refetchInterval: 5_000 });

  return (
    <section
      data-testid="mqtt-latest-readings-panel"
      className="border border-white/5 rounded-xl bg-white/[0.02] p-5"
    >
      <header className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-black uppercase tracking-widest text-neutral-200 flex items-center gap-2">
          <span className="material-symbols-outlined text-amber-300">timeline</span>
          Latest Readings
        </h2>
        <span className="text-[10px] font-black uppercase tracking-widest text-neutral-500">
          Polling 5s · {readingsQuery.data?.length ?? 0} rows
        </span>
      </header>

      {readingsQuery.isLoading && (
        <p className="text-xs text-neutral-500">Loading latest readings…</p>
      )}
      {readingsQuery.error && (
        <p className="text-xs text-red-400">Failed to load latest readings.</p>
      )}
      {readingsQuery.data && readingsQuery.data.length === 0 && (
        <p className="text-xs text-neutral-500">No readings yet.</p>
      )}

      {readingsQuery.data && readingsQuery.data.length > 0 && (
        <ul className="space-y-2">
          {readingsQuery.data.map((reading, idx) => (
            <li
              key={`${reading.device_id}-${reading.metric_id}-${idx}`}
              data-testid="mqtt-reading-row"
              className="flex flex-wrap items-center gap-3 text-xs text-neutral-200 border border-white/5 rounded-lg p-3 bg-surface-900"
            >
              <span className="font-mono text-[10px] text-neutral-500">
                {reading.device_id}
              </span>
              <span className="font-bold">{reading.name ?? reading.metric_id}</span>
              <span className="font-mono">
                {formatLastValue(reading.last_value)}
                {reading.unit ? <span className="text-neutral-500 ml-1">{reading.unit}</span> : null}
              </span>
              <span className="text-neutral-500">{formatLastSeen(reading.last_ts)}</span>
              <span className="ml-auto">
                <RawNonKpiBadge
                  classification={reading.classification}
                  kpiEligible={reading.kpi_eligible}
                />
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
};

const MqttRawReadingsTab: React.FC = () => {
  const devicesQuery = useMqttDevicesQuery();
  const devices = devicesQuery.data ?? [];

  return (
    <div className="space-y-6">
      <section>
        <header className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-black uppercase tracking-widest text-neutral-200 flex items-center gap-2">
            <span className="material-symbols-outlined text-amber-300">sensors</span>
            Raw Devices
          </h2>
          <span className="text-[10px] font-black uppercase tracking-widest text-neutral-500">
            {devices.length} {devices.length === 1 ? "device" : "devices"}
          </span>
        </header>

        {devicesQuery.isLoading && (
          <p className="text-xs text-neutral-500">Loading devices…</p>
        )}
        {devicesQuery.error && (
          <p className="text-xs text-red-400">Failed to load devices.</p>
        )}
        {devicesQuery.data && devices.length === 0 && (
          <p
            data-testid="mqtt-devices-empty"
            className="text-xs text-neutral-500 border border-dashed border-white/10 rounded-xl p-8 text-center"
          >
            No devices
          </p>
        )}
        {devices.length > 0 && (
          <div className="space-y-2">
            {devices.map((device) => (
              <DeviceRow key={device.device_id} device={device} />
            ))}
          </div>
        )}
      </section>

      <LatestReadingsPanel />

      {/* Defensive constant export so tests can assert the canonical label
          without reaching into the badge module directly. */}
      <span data-testid="mqtt-raw-classification-constant" className="sr-only">
        {RAW_MQTT_NON_KPI}
      </span>
    </div>
  );
};

export default MqttRawReadingsTab;
