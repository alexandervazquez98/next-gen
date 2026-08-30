/**
 * MQTT Monitoring Frontend (Issue #385) — Bridge Status tab.
 *
 * PR1 surface:
 *   - Polls `GET /api/mqtt/status` every 5 seconds (same cadence as the
 *     readings panel; status is minutes-scale, not seconds-scale, so the
 *     design uses `refetchInterval: 5000` rather than 3000 like the system
 *     status feed).
 *   - Renders three branches from the runtime status payload:
 *       * Running — `running && connected && configured`
 *       * Not Running — backend reports `running=false`, OR the backend
 *         normalized a stale heartbeat to `running=false` (with
 *         `reason_code="STALE_HEARTBEAT"`).
 *       * Not Configured — `configured=false` (regardless of running).
 *   - Surfaces `reason_code`, `last_error`, `last_message_at`,
 *     `subscribed_patterns`, and the three counter fields
 *     (`mapped_writes_total`, `unmapped_skips_total`, `failed_writes_total`).
 *
 * The branch ordering matters: "Not Configured" wins over "Not Running"
 * when both apply, because a never-configured runtime cannot meaningfully
 * be "Running" — surfacing the configuration gap first helps the operator
 * diagnose.
 */
import React from "react";
import { useMqttStatusQuery } from "../../hooks/queries/useMqttQueries";
import type { MqttRuntimeStatus } from "../../types";

type Branch = "running" | "not-running" | "not-configured";

const resolveBranch = (status?: MqttRuntimeStatus | null): Branch => {
  if (!status) return "not-configured";
  if (!status.configured) return "not-configured";
  if (status.running) return "running";
  return "not-running";
};

const formatTimestamp = (value?: string | null) => {
  if (!value) return "never";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
};

interface BranchHeaderProps {
  branch: Branch;
  reasonCode?: string | null;
  lastError?: string | null;
  isStale?: boolean;
}

const BranchHeader: React.FC<BranchHeaderProps> = ({ branch, reasonCode, lastError, isStale }) => {
  if (branch === "running") {
    return (
      <div
        data-testid="mqtt-bridge-branch"
        data-branch="running"
        className="flex items-center gap-3"
      >
        <span className="w-3 h-3 rounded-full bg-emerald-500 animate-pulse" />
        <span className="text-xs font-black uppercase tracking-widest text-emerald-300">
          Running
        </span>
      </div>
    );
  }
  if (branch === "not-configured") {
    return (
      <div
        data-testid="mqtt-bridge-branch"
        data-branch="not-configured"
        className="flex items-center gap-3"
      >
        <span className="w-3 h-3 rounded-full bg-neutral-500" />
        <span className="text-xs font-black uppercase tracking-widest text-neutral-300">
          Not Configured
        </span>
      </div>
    );
  }
  return (
    <div
      data-testid="mqtt-bridge-branch"
      data-branch="not-running"
      className="flex flex-col gap-1"
    >
      <div className="flex items-center gap-3">
        <span className="w-3 h-3 rounded-full bg-red-500" />
        <span className="text-xs font-black uppercase tracking-widest text-red-300">
          Not Running
        </span>
        {isStale && (
          <span className="text-[10px] font-black uppercase tracking-widest text-amber-300 bg-amber-500/10 border border-amber-500/30 px-2 py-0.5 rounded">
            Stale heartbeat
          </span>
        )}
      </div>
      {reasonCode && (
        <p className="text-[10px] font-mono text-neutral-400">reason_code: {reasonCode}</p>
      )}
      {lastError && (
        <p className="text-[10px] font-mono text-red-300">last_error: {lastError}</p>
      )}
      {!reasonCode && !lastError && (
        <p className="text-[10px] text-neutral-500">
          See the runbook for diagnostics.
        </p>
      )}
    </div>
  );
};

const CounterTile: React.FC<{ label: string; value: number | undefined }> = ({ label, value }) => (
  <div className="border border-white/5 rounded-xl bg-white/[0.02] p-4 flex flex-col gap-1">
    <span className="text-[10px] font-black uppercase tracking-widest text-neutral-500">
      {label}
    </span>
    <span className="text-2xl font-black text-white tracking-tight tabular-nums">
      {value ?? 0}
    </span>
  </div>
);

const MqttBridgeStatusTab: React.FC = () => {
  const statusQuery = useMqttStatusQuery({ refetchInterval: 5_000 });
  const status = statusQuery.data;
  const branch = resolveBranch(status);

  return (
    <div className="space-y-6">
      <section
        data-testid="mqtt-bridge-status-card"
        className="border border-white/5 rounded-xl bg-white/[0.02] p-6"
      >
        <header className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <span className="material-symbols-outlined text-amber-300">cell_tower</span>
            <h2 className="text-sm font-black uppercase tracking-widest text-neutral-200">
              MQTT Bridge
            </h2>
          </div>
          <span className="text-[10px] font-black uppercase tracking-widest text-neutral-500">
            Polling 5s
          </span>
        </header>

        {statusQuery.isLoading && (
          <p className="text-xs text-neutral-500">Loading bridge status…</p>
        )}
        {statusQuery.error && (
          <p className="text-xs text-red-400">Failed to load bridge status.</p>
        )}

        {status && (
          <>
            <BranchHeader
              branch={branch}
              reasonCode={status.reason_code ?? null}
              lastError={status.last_error ?? null}
              isStale={status.is_stale ?? false}
            />

            <dl className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-6 text-xs">
              <div>
                <dt className="text-[10px] font-black uppercase tracking-widest text-neutral-500">
                  configured
                </dt>
                <dd className="font-mono text-white">{String(status.configured)}</dd>
              </div>
              <div>
                <dt className="text-[10px] font-black uppercase tracking-widest text-neutral-500">
                  connected
                </dt>
                <dd className="font-mono text-white">{String(status.connected)}</dd>
              </div>
              <div>
                <dt className="text-[10px] font-black uppercase tracking-widest text-neutral-500">
                  last message
                </dt>
                <dd className="font-mono text-white">{formatTimestamp(status.last_message_at)}</dd>
              </div>
              <div>
                <dt className="text-[10px] font-black uppercase tracking-widest text-neutral-500">
                  service
                </dt>
                <dd className="font-mono text-white">{status.service_name ?? "mqtt-bridge"}</dd>
              </div>
            </dl>

            {status.subscribed_patterns && status.subscribed_patterns.length > 0 && (
              <div className="mt-6">
                <p className="text-[10px] font-black uppercase tracking-widest text-neutral-500 mb-2">
                  Subscribed patterns
                </p>
                <ul
                  data-testid="mqtt-subscribed-patterns"
                  className="flex flex-wrap gap-2"
                >
                  {status.subscribed_patterns.map((pattern) => (
                    <li
                      key={pattern}
                      className="text-[10px] font-mono text-emerald-300 bg-emerald-500/10 border border-emerald-500/30 px-2 py-1 rounded"
                    >
                      {pattern}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </>
        )}
      </section>

      <section
        data-testid="mqtt-bridge-counters"
        className="grid grid-cols-1 md:grid-cols-3 gap-4"
      >
        <CounterTile label="Mapped writes" value={status?.mapped_writes_total} />
        <CounterTile label="Unmapped skips" value={status?.unmapped_skips_total} />
        <CounterTile label="Failed writes" value={status?.failed_writes_total} />
      </section>
    </div>
  );
};

export default MqttBridgeStatusTab;
