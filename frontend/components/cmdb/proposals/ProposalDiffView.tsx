import React from "react";

interface ProposalDiffViewProps {
  manifest: Record<string, unknown> | null;
  liveCi: Record<string, unknown> | null;
  liveCategories: string[];
  liveCiExists: boolean;
}

function classify(
  manifestCi: Record<string, unknown> | undefined,
  liveCi: Record<string, unknown> | undefined,
): {
  added: Array<[string, unknown]>;
  changed: Array<[string, { from: unknown; to: unknown }]>;
  removed: Array<[string, unknown]>;
} {
  const added: Array<[string, unknown]> = [];
  const changed: Array<[string, { from: unknown; to: unknown }]> = [];
  const removed: Array<[string, unknown]> = [];

  const manifestKeys = manifestCi ? Object.keys(manifestCi) : [];
  const liveKeys = liveCi ? Object.keys(liveCi) : [];

  // Pure-add case: when liveCi is null, every manifest field is added.
  if (liveCi === null || liveCi === undefined) {
    for (const k of manifestKeys) {
      added.push([k, manifestCi![k]]);
    }
    return { added, changed, removed };
  }

  // Live exists — both added/changed/removed are possible.
  const allKeys = new Set<string>([...manifestKeys, ...liveKeys]);
  allKeys.forEach((key) => {
    const from = manifestCi ? manifestCi[key] : undefined;
    const to = liveCi[key];
    if (from === undefined) added.push([key, to]);
    else if (to === undefined) removed.push([key, from]);
    else if (JSON.stringify(from) !== JSON.stringify(to)) {
      changed.push([key, { from, to }]);
    }
  });

  return { added, changed, removed };
}

export const ProposalDiffView: React.FC<ProposalDiffViewProps> = ({
  manifest,
  liveCi,
  liveCategories,
  liveCiExists,
}) => {
  const manifestCi = (manifest?.["ci"] ?? {}) as Record<string, unknown>;
  const { added, changed, removed } = classify(manifestCi, liveCi ?? undefined);
  const categoryDrift = !liveCategories.includes(String(manifestCi["category"] ?? ""));

  return (
    <div
      data-testid="proposal-diff-view"
      className="grid gap-3 p-4 bg-neutral-900/40 border border-white/5 rounded-xl"
    >
      {liveCiExists && (
        <div
          role="alert"
          data-testid="proposal-diff-collision"
          className="px-3 py-2 bg-amber-500/10 border border-amber-500/30 rounded text-amber-300 text-xs"
        >
          Collision: a :CI with this id already exists.
        </div>
      )}
      {categoryDrift && (
        <div
          role="alert"
          data-testid="proposal-diff-category-drift"
          className="px-3 py-2 bg-red-500/10 border border-red-500/30 rounded text-red-300 text-xs"
        >
          Category drift: <code>{String(manifestCi["category"])}</code> is no longer in the live
          Category catalog.
        </div>
      )}

      <section data-testid="proposal-diff-added">
        <h4 className="text-[10px] uppercase tracking-widest text-emerald-400 mb-1">
          Added fields
        </h4>
        {added.length === 0 ? (
          <p className="text-xs text-neutral-500">None.</p>
        ) : (
          <ul className="text-xs font-mono">
            {added.map(([k, v]) => (
              <li key={k} className="flex justify-between gap-3 border-b border-white/5 py-1">
                <span>{k}</span>
                <span className="text-emerald-300">{JSON.stringify(v)}</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section data-testid="proposal-diff-changed">
        <h4 className="text-[10px] uppercase tracking-widest text-amber-400 mb-1">
          Changed fields
        </h4>
        {changed.length === 0 ? (
          <p className="text-xs text-neutral-500">None.</p>
        ) : (
          <ul className="text-xs font-mono">
            {changed.map(([k, { from, to }]) => (
              <li key={k} className="flex flex-col gap-1 border-b border-white/5 py-1">
                <span>{k}</span>
                <span className="text-red-300 line-through">{JSON.stringify(from)}</span>
                <span className="text-emerald-300">{JSON.stringify(to)}</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section data-testid="proposal-diff-removed">
        <h4 className="text-[10px] uppercase tracking-widest text-red-400 mb-1">Removed fields</h4>
        {removed.length === 0 ? (
          <p className="text-xs text-neutral-500">None.</p>
        ) : (
          <ul className="text-xs font-mono">
            {removed.map(([k, v]) => (
              <li key={k} className="flex justify-between gap-3 border-b border-white/5 py-1">
                <span>{k}</span>
                <span className="text-red-300 line-through">{JSON.stringify(v)}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
};
