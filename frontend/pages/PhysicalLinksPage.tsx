/**
 * PhysicalLinksPage — slice 2/4 of feat-444 (closes #444).
 *
 * Public surface for the PhysicalLink visualization chain. Wraps the
 * `PhysicalLinkPreview` showcase (legend + live CRUD list + create form +
 * per-row status selector) so operators can reach the static visual
 * contract against real API data without the preview being dead weight.
 *
 * The backend router is gated on `FEATURE_CMDB_PHYSICAL_LINKS_ENABLED`
 * (mirrors `FEATURE_CMDB_PROPOSALS_ENABLED`); when the flag is off the
 * API returns 404 and the page renders its empty/error state — same
 * behaviour as `ProposalsCmdbPage` when the proposals flag is off.
 *
 * No frontend feature flag here on purpose: the gate belongs to the API
 * contract. Adding a second gate at the page layer would split the truth
 * between two env vars and risk drift.
 */

import React from "react";
import { Link } from "react-router-dom";
import { PhysicalLinkPreview } from "../components/cmdb/topology/PhysicalLinkPreview";

export const PhysicalLinksPage: React.FC = () => {
  return (
    <div data-testid="physical-links-page" className="flex flex-col h-full w-full overflow-hidden">
      <header className="px-8 py-6 border-b border-white/5 flex items-center justify-between">
        <div>
          <h1 className="text-lg font-bold text-white tracking-tight uppercase tracking-widest">
            Physical Links
          </h1>
          <p className="text-xs text-neutral-500 mt-1">
            Slice 2/4 of the fiber-optic / physical-link visualization chain (#444). Visual contract
            per <code className="text-accent-cyan">PhysicalLinkType</code>; backed by{" "}
            <code className="text-accent-cyan">/api/cmdb/physical-links</code>.
          </p>
        </div>
        <Link
          to="/cmdb"
          className="text-xs text-neutral-500 hover:text-white transition-colors flex items-center gap-2"
        >
          <span className="material-symbols-outlined text-sm">arrow_back</span>
          Back to CMDB
        </Link>
      </header>
      <div className="flex-1 min-h-0 overflow-auto p-8">
        <PhysicalLinkPreview />
      </div>
    </div>
  );
};

export default PhysicalLinksPage;
