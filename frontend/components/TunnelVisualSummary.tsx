import type React from "react";
import type { TunnelVisualModel } from "../types";
import CategoryIcon from "./CategoryIcon";

interface TunnelVisualSummaryProps {
  visual: TunnelVisualModel;
  title?: string;
}

const stateTone: Record<TunnelVisualModel["state"], string> = {
  up: "text-emerald-300 border-emerald-500/30 bg-emerald-500/10",
  down: "text-red-300 border-red-500/30 bg-red-500/10",
  unknown: "text-neutral-300 border-white/10 bg-white/5",
};

const TunnelVisualSummary: React.FC<TunnelVisualSummaryProps> = ({ visual, title }) => (
  <div
    className="rounded-lg border border-white/10 bg-black/30 p-2 text-xs text-neutral-300"
    title={visual.tooltipRows.map((row) => `${row.label}: ${row.value}`).join(" • ")}
  >
    {title && <div className="mb-1 font-bold uppercase text-neutral-500">{title}</div>}
    <div className="flex flex-wrap items-center gap-2">
      <CategoryIcon
        iconKey={visual.iconKey}
        categoryName={visual.mediumLabel}
        className="text-base text-cyan-300"
      />
      <span className="font-bold text-white">{visual.mediumLabel}</span>
      <span className={`rounded border px-2 py-0.5 font-black ${stateTone[visual.state]}`}>
        {visual.authorityText}
      </span>
      {visual.warning && (
        <span className="rounded border border-amber-400/30 bg-amber-400/10 px-2 py-0.5 font-bold text-amber-200">
          Warning
        </span>
      )}
    </div>
    <div className="mt-1 grid gap-1">
      {visual.tooltipRows.map((row) => (
        <div key={`${row.label}-${row.value}`} className="flex gap-1">
          <span className="font-bold text-neutral-500">{row.label}:</span>
          <span>{row.value}</span>
        </div>
      ))}
    </div>
  </div>
);

export default TunnelVisualSummary;
