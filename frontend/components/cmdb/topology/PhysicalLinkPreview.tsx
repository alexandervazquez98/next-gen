/**
 * PhysicalLinkPreview.tsx
 *
 * Slice 2/4 of feat-444 (closes #444): a presentational + interactive
 * showcase that proves the static visual contract
 * (``PHYSICAL_LINK_STYLES`` + ``LinkTypeLegend``) lines up with the real
 * CRUD data path (``/api/cmdb/physical-links``).
 *
 * Layout: two columns.
 *   - Left: ``<LinkTypeLegend />`` so the operator sees the canonical type
 *     legend next to the live data.
 *   - Right: a header for the selected entity, a fetched list of
 *     PhysicalLinks (each row carries a swatch from the registered style,
 *     the endpoints joined with an arrow, a status badge, and a status
 *     selector), and a small create form wired to
 *     ``useCreatePhysicalLink``.
 *
 * This slice does NOT wire styling into TopologyViewer /
 * NetworkVisualizer / VisualRelationshipEditor / MonitoringConsole. None
 * of those components consume PhysicalLink data today (verified by scout).
 * The showcase proves the visual contract works against real API data
 * without coupling to legacy renderers.
 */

import React from "react";
import { LinkTypeLegend } from "./LinkTypeLegend";
import {
  useCreatePhysicalLink,
  useUpdatePhysicalLinkStatus,
} from "../../../hooks/queries/usePhysicalLinkMutations";
import { usePhysicalLinksQuery } from "../../../hooks/queries/usePhysicalLinksQuery";
import {
  type PhysicalLinkCreatePayload,
  type PhysicalLinkStatus,
} from "../../../services/physicalLinks";
import { getPhysicalLinkStyle } from "../../../utils/physicalLinkStyles";
import type { PhysicalLinkType } from "../../../types";

const PHYSICAL_LINK_TYPES: PhysicalLinkType[] = ["fiber", "copper", "microwave", "wireless_ptp"];

const PHYSICAL_LINK_STATUSES: PhysicalLinkStatus[] = ["UP", "DOWN", "UNKNOWN", "PLANNED"];

interface CreateFormState {
  id: string;
  type: PhysicalLinkType;
  endpointA: string;
  endpointB: string;
}

const INITIAL_FORM_STATE: CreateFormState = {
  id: "",
  type: "fiber",
  endpointA: "",
  endpointB: "",
};

function statusBadgeStyle(status: PhysicalLinkStatus): React.CSSProperties {
  switch (status) {
    case "UP":
      return { backgroundColor: "#16a34a", color: "#fff" };
    case "DOWN":
      return { backgroundColor: "#dc2626", color: "#fff" };
    case "PLANNED":
      return { backgroundColor: "#475569", color: "#fff" };
    case "UNKNOWN":
    default:
      return { backgroundColor: "#94a3b8", color: "#fff" };
  }
}

export function PhysicalLinkPreview() {
  const { data: rows = [], isLoading, error } = usePhysicalLinksQuery();
  const { mutate: createLink } = useCreatePhysicalLink();
  const { mutate: updateStatus } = useUpdatePhysicalLinkStatus();

  const [form, setForm] = React.useState<CreateFormState>(INITIAL_FORM_STATE);

  const handleCreate = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const payload: PhysicalLinkCreatePayload = {
      id: form.id.trim(),
      type: form.type,
      endpoints: [form.endpointA.trim(), form.endpointB.trim()],
    };
    if (!payload.id || !payload.endpoints[0] || !payload.endpoints[1]) return;
    createLink(payload);
    setForm(INITIAL_FORM_STATE);
  };

  return (
    <section
      aria-label="PhysicalLink preview showcase"
      data-testid="physical-link-preview"
      style={{
        display: "grid",
        gridTemplateColumns: "minmax(240px, 1fr) 2fr",
        gap: "1.5rem",
        padding: "1rem",
      }}
    >
      <aside aria-label="Legend column">
        <h2 style={{ fontSize: "1rem", marginTop: 0 }}>PhysicalLink types</h2>
        <LinkTypeLegend />
      </aside>

      <div aria-label="Data column">
        <header style={{ marginBottom: "1rem" }}>
          <h2 style={{ fontSize: "1rem", margin: 0 }}>PhysicalLinks</h2>
          <p style={{ fontSize: "0.75rem", color: "#64748b", margin: "0.25rem 0 0" }}>
            Live data from <code>GET /api/cmdb/physical-links</code>.
          </p>
        </header>

        {isLoading ? (
          <p data-testid="physical-link-preview-loading">Loading…</p>
        ) : error ? (
          <p data-testid="physical-link-preview-error" role="alert">
            Failed to load PhysicalLinks.
          </p>
        ) : rows.length === 0 ? (
          <p data-testid="physical-link-preview-empty">No PhysicalLinks yet.</p>
        ) : (
          <ul
            role="list"
            aria-label="PhysicalLinks"
            data-testid="physical-link-preview-list"
            style={{ listStyle: "none", margin: 0, padding: 0 }}
          >
            {rows.map((row) => {
              const style = getPhysicalLinkStyle(row.type);
              return (
                <li
                  key={row.id}
                  data-testid={`physical-link-row-${row.id}`}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "0.75rem",
                    padding: "0.5rem 0",
                    borderBottom: "1px solid #e2e8f0",
                  }}
                >
                  <svg
                    aria-hidden="true"
                    focusable="false"
                    data-testid={`physical-link-row-swatch-${row.type}`}
                    width={40}
                    height={12}
                    viewBox="0 0 40 12"
                    style={{ display: "block", flexShrink: 0 }}
                  >
                    <line
                      x1={0}
                      y1={6}
                      x2={40}
                      y2={6}
                      stroke={style.color}
                      strokeWidth={style.weight}
                      strokeDasharray={style.dashArray ?? undefined}
                    />
                  </svg>
                  <code
                    style={{
                      fontFamily: "ui-monospace, SFMono-Regular, monospace",
                      fontSize: "0.75rem",
                      color: "#0f172a",
                    }}
                  >
                    {row.id}
                  </code>
                  <span style={{ flex: 1, fontSize: "0.875rem", color: "#0f172a" }}>
                    {row.endpoints[0]} → {row.endpoints[1]}
                  </span>
                  <span
                    aria-label={`Status ${row.status}`}
                    data-testid={`physical-link-row-status-${row.id}`}
                    style={{
                      ...statusBadgeStyle(row.status),
                      padding: "0.125rem 0.5rem",
                      borderRadius: "9999px",
                      fontSize: "0.75rem",
                      fontWeight: 600,
                    }}
                  >
                    {row.status}
                  </span>
                  <label
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: "0.25rem",
                      fontSize: "0.75rem",
                      color: "#475569",
                    }}
                  >
                    <span>Change:</span>
                    <select
                      aria-label={`Status for ${row.id}`}
                      value={row.status}
                      onChange={(e) =>
                        updateStatus({
                          id: row.id,
                          status: e.target.value as PhysicalLinkStatus,
                        })
                      }
                      style={{
                        fontSize: "0.75rem",
                        padding: "0.125rem 0.25rem",
                      }}
                    >
                      {PHYSICAL_LINK_STATUSES.map((s) => (
                        <option key={s} value={s}>
                          {s}
                        </option>
                      ))}
                    </select>
                  </label>
                </li>
              );
            })}
          </ul>
        )}

        <form
          aria-label="Create PhysicalLink"
          onSubmit={handleCreate}
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 1fr 1fr 1fr auto",
            gap: "0.5rem",
            marginTop: "1.5rem",
            alignItems: "end",
          }}
        >
          <label style={{ fontSize: "0.75rem", color: "#475569" }}>
            id
            <input
              aria-label="id"
              value={form.id}
              onChange={(e) => setForm((f) => ({ ...f, id: e.target.value }))}
              required
              style={{ display: "block", width: "100%" }}
            />
          </label>
          <label style={{ fontSize: "0.75rem", color: "#475569" }}>
            type
            <select
              aria-label="type"
              value={form.type}
              onChange={(e) => setForm((f) => ({ ...f, type: e.target.value as PhysicalLinkType }))}
              style={{ display: "block", width: "100%" }}
            >
              {PHYSICAL_LINK_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </label>
          <label style={{ fontSize: "0.75rem", color: "#475569" }}>
            endpoint A
            <input
              aria-label="endpoint A"
              value={form.endpointA}
              onChange={(e) => setForm((f) => ({ ...f, endpointA: e.target.value }))}
              required
              style={{ display: "block", width: "100%" }}
            />
          </label>
          <label style={{ fontSize: "0.75rem", color: "#475569" }}>
            endpoint B
            <input
              aria-label="endpoint B"
              value={form.endpointB}
              onChange={(e) => setForm((f) => ({ ...f, endpointB: e.target.value }))}
              required
              style={{ display: "block", width: "100%" }}
            />
          </label>
          <button
            type="submit"
            aria-label="Create"
            style={{
              padding: "0.5rem 1rem",
              fontSize: "0.875rem",
              fontWeight: 600,
              border: "1px solid #1e293b",
              borderRadius: "0.375rem",
              backgroundColor: "#1e293b",
              color: "#fff",
              cursor: "pointer",
            }}
          >
            Create
          </button>
        </form>
      </div>
    </section>
  );
}

export default PhysicalLinkPreview;
