import React, { useState } from "react";
import {
  bulkImportProposals,
  bulkValidateProposals,
  type BulkImportError,
  type BulkImportResponse,
  type BulkValidationError,
  type BulkValidationResponse,
} from "../../../services/cmdbProposals";

interface BulkImportPanelProps {
  onCreated?: (_proposalId: string) => void;
}

const MAX_BYTES = 5 * 1024 * 1024;
const MAX_ROWS = 1000;

const BulkImportPanel: React.FC<BulkImportPanelProps> = ({ onCreated }) => {
  const [file, setFile] = useState<File | null>(null);
  const [defaultCategory, setDefaultCategory] = useState("");
  const [defaultOwner, setDefaultOwner] = useState("");
  const [validation, setValidation] = useState<BulkValidationResponse | null>(null);
  const [validationErrors, setValidationErrors] = useState<BulkValidationError[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<BulkImportError | null>(null);
  const [submitted, setSubmitted] = useState<BulkImportResponse | null>(null);

  const onFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const next = e.target.files?.[0] ?? null;
    setFile(next);
    setValidation(null);
    setValidationErrors([]);
    setSubmitError(null);
    setSubmitted(null);
  };

  const validate = async () => {
    if (!file) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const result = await bulkValidateProposals(
        file,
        defaultCategory || undefined,
        defaultOwner || undefined,
      );
      if ("dry_run" in result) {
        setValidation(result);
        setValidationErrors([]);
      } else {
        setValidation(null);
        setValidationErrors(result.errors ?? []);
      }
    } finally {
      setSubmitting(false);
    }
  };

  const submit = async () => {
    if (!file) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const result = await bulkImportProposals(
        file,
        defaultCategory || undefined,
        defaultOwner || undefined,
      );
      if ("proposal_id" in result) {
        setSubmitted(result);
        setValidation(null);
        setValidationErrors([]);
        onCreated?.(result.proposal_id);
      } else if ("harness_result" in result) {
        // Guardrail denial — surface to the operator without an error alert.
        setSubmitError({
          reason: "bulk_validation_failed",
          errors: [],
          hint: `Guardrail: ${result.harness_result.reason}`,
        });
      } else {
        setSubmitError(result);
      }
    } finally {
      setSubmitting(false);
    }
  };

  const tooLarge = file ? file.size > MAX_BYTES : false;

  return (
    <div
      data-testid="bulk-import-panel"
      className="p-4 bg-neutral-900/40 border border-white/5 rounded-xl flex flex-col gap-3"
    >
      <h3 className="text-sm font-black uppercase tracking-widest text-white">
        Bulk CSV import
      </h3>
      <p className="text-xs text-neutral-400">
        Upload a UTF-8 CSV with header row. Columns: <code>id</code>,{" "}
        <code>label</code>, <code>category</code>, <code>brand</code>,{" "}
        <code>model</code>, <code>serialNumber</code>,{" "}
        <code>firmwareVersion</code>, <code>ip</code>, <code>owner</code>,{" "}
        <code>location_name</code>, <code>status</code>,{" "}
        <code>pollingInterval</code>, <code>metadata_json</code>. Up to{" "}
        {MAX_ROWS.toLocaleString()} rows and {Math.round(MAX_BYTES / 1024 / 1024)}{" "}
        MB per upload. Secret columns (anything matching{" "}
        <code>*key|*token|*secret|*password|*community</code>) are
        rejected; use <code>{"<field>"}_ref</code> with a{" "}
        <code>secret://</code> URL instead.
      </p>

      <div className="flex flex-col gap-2">
        <label className="text-[10px] uppercase tracking-widest text-neutral-400">
          CSV file
          <input
            data-testid="bulk-import-file"
            type="file"
            accept=".csv,text/csv"
            onChange={onFile}
            className="mt-1 block w-full text-xs text-neutral-200 file:mr-2 file:py-1 file:px-3 file:rounded-lg file:border-0 file:bg-brand-600 file:text-white hover:file:bg-brand-500"
          />
        </label>
        {file && (
          <p className="text-xs text-neutral-400">
            {file.name} — {(file.size / 1024).toFixed(1)} KB
          </p>
        )}
        {tooLarge && (
          <p
            data-testid="bulk-import-file-too-large"
            role="alert"
            className="text-xs text-red-400"
          >
            File exceeds the {Math.round(MAX_BYTES / 1024 / 1024)} MB cap.
          </p>
        )}
      </div>

      <div className="grid grid-cols-2 gap-2">
        <label className="text-[10px] uppercase tracking-widest text-neutral-400">
          Default category (optional)
          <input
            data-testid="bulk-import-default-category"
            value={defaultCategory}
            onChange={(e) => setDefaultCategory(e.target.value)}
            placeholder="Router"
            className="mt-1 block w-full bg-neutral-950 text-neutral-200 border border-white/10 rounded px-2 py-1 text-xs"
          />
        </label>
        <label className="text-[10px] uppercase tracking-widest text-neutral-400">
          Default owner (optional)
          <input
            data-testid="bulk-import-default-owner"
            value={defaultOwner}
            onChange={(e) => setDefaultOwner(e.target.value)}
            placeholder="NOC-LATAM"
            className="mt-1 block w-full bg-neutral-950 text-neutral-200 border border-white/10 rounded px-2 py-1 text-xs"
          />
        </label>
      </div>

      <div className="flex items-center gap-2">
        <button
          data-testid="bulk-import-validate"
          onClick={validate}
          disabled={!file || submitting || tooLarge}
          className="px-3 py-1.5 text-xs rounded-lg bg-neutral-700 text-white hover:bg-neutral-600 disabled:opacity-50"
        >
          {submitting ? "Validating…" : "Validate (dry-run)"}
        </button>
        <button
          data-testid="bulk-import-submit"
          onClick={submit}
          disabled={
            !file ||
            submitting ||
            tooLarge ||
            (validationErrors.length > 0 && !validation)
          }
          className="px-3 py-1.5 text-xs rounded-lg bg-brand-600 text-white hover:bg-brand-500 disabled:opacity-50"
        >
          {submitting ? "Submitting…" : "Submit draft"}
        </button>
      </div>

      {validation && (
        <div
          data-testid="bulk-import-validation-ok"
          className="text-xs text-emerald-300 border border-emerald-500/30 rounded-lg p-2 bg-emerald-500/10"
        >
          ✓ Validation OK — {validation.cis_count} CI(s) ready across{" "}
          {validation.categories.length} categor
          {validation.categories.length === 1 ? "y" : "ies"}:{" "}
          {validation.categories.join(", ")}
        </div>
      )}

      {validationErrors.length > 0 && (
        <div
          data-testid="bulk-import-validation-errors"
          className="text-xs text-red-300 border border-red-500/30 rounded-lg p-2 bg-red-500/10"
        >
          <p className="font-bold mb-1">
            {validationErrors.length} row(s) failed — fix and resubmit
            (atomicity: no partial success):
          </p>
          <ul className="space-y-1 max-h-60 overflow-y-auto custom-scrollbar">
            {validationErrors.map((e) => (
              <li key={e.row} className="font-mono">
                row {e.row}: {e.errors.join("; ")}
              </li>
            ))}
          </ul>
        </div>
      )}

      {submitError && (
        <div
          data-testid="bulk-import-submit-error"
          className="text-xs text-red-300 border border-red-500/30 rounded-lg p-2 bg-red-500/10"
        >
          ✗ {submitError.reason}
          {submitError.hint ? ` — ${submitError.hint}` : null}
        </div>
      )}

      {submitted && (
        <div
          data-testid="bulk-import-submitted"
          className="text-xs text-emerald-300 border border-emerald-500/30 rounded-lg p-2 bg-emerald-500/10"
        >
          ✓ Created DRAFT proposal{" "}
          <a
            href={`/#/proposals/cmdb?id=${submitted.proposal_id}`}
            className="font-mono underline"
          >
            {submitted.proposal_id}
          </a>{" "}
          ({submitted.cis_count} CIs). Review and approve at{" "}
          <code>/#/proposals/cmdb?id={submitted.proposal_id}</code>.
        </div>
      )}
    </div>
  );
};

export default BulkImportPanel;
