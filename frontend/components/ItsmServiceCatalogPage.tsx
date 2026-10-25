// frontend/components/ItsmServiceCatalogPage.tsx
//
// Feature #480 — ITIL-aligned UX for the Service Catalog create/edit form.
//
// The free-text input fields that previously accepted any string are now
// driven by managed lookups:
// - value_stream  → GET /api/dictionaries?key=value_stream&active=true
// - owner_team    → GET /api/owners
// - category      → GET /api/categories
// - tier          → GET /api/dictionaries?key=tier&active=true
// - criticality   → GET /api/dictionaries?key=criticality&active=true
//
// service_id is auto-minted by the backend on create (S1): the create form
// has no service_id input and shows the assigned id read-only after the
// 201 response. Edit mode keeps the persisted service_id disabled.
//
// The SLA control is a composite [number][unit-select] that converts the
// user-entered value to ``sla_target_minutes`` int on submit.

import React, { useContext, useEffect, useMemo, useState } from "react";
import type { ChangeEvent, FormEvent } from "react";
import { Link } from "react-router-dom";
import { QueryClient, QueryClientContext, QueryClientProvider } from "@tanstack/react-query";
import {
  createServiceCatalog,
  deactivateServiceCatalog,
  downloadCatalogTemplate,
  extractErrorMessage,
  extractImportError,
  importCatalogWorkbook,
  listServiceCatalog,
  updateServiceCatalog,
} from "../services/itsm";
import type {
  ImportValidationFailure,
  ServiceCatalogCreatePayload,
  ServiceCatalogResponse,
  ServiceCatalogType,
  ServiceCatalogUpdatePayload,
} from "../types/itsm";

import { useCategories } from "../hooks/useCategories";
import {
  useCriticalities,
  useTiers,
  useValueStreams,
  type DictionaryValueRecord,
} from "../hooks/useDictionaries";
import { useOwners } from "../hooks/useOwners";

type FormMode = "create" | "edit";

// S2 — the Dictionary manager is the "DICTIONARIES" tab of the
// Administration surface. There is no `/itsm/dictionaries` route in this
// SPA, so the CTA deep links to the real manager: `/admin?tab=dictionaries`
// (AdminPage reads the `tab` query parameter to preselect the tab).
const DICTIONARY_MANAGER_ROUTE = "/admin?tab=dictionaries";

// S4 — canonical ITIL / ServiceNow-aligned service taxonomy. The list is
// the maintainer decision recorded in
// openspec/changes/feat-service-catalog-itil-ux/proposal.md and is seeded
// by the backend category seed.
const CANONICAL_CATEGORIES = [
  "Infrastructure & Platform",
  "Application Services",
  "End User Computing",
  "IT Security",
  "Telecommunications",
  "Business Services",
  "Workspace",
  "Consulting & Advisory",
] as const;

// S5 — recommended (not enforced) tier → criticality pairing. The two
// controls stay independent: the server does not derive one from the other
// and the wire format is unchanged.
const RECOMMENDED_TIER_CRITICALITY: ReadonlyArray<{ tier: string; criticality: string }> = [
  { tier: "bronze", criticality: "low" },
  { tier: "silver", criticality: "medium" },
  { tier: "gold", criticality: "high" },
  { tier: "platinum", criticality: "critical" },
];

// SLA control: converted to minutes before submit so the wire format
// stays ``sla_target_minutes: int`` (S6).
const SLA_UNITS = {
  minutes: { label: "minutes", factor: 1 },
  hours: { label: "hours", factor: 60 },
  days: { label: "days", factor: 60 * 24 },
} as const;
type SlaUnit = keyof typeof SLA_UNITS;
const DEFAULT_SLA_UNIT: SlaUnit = "hours";

type CatalogFormState = {
  service_id: string;
  name: string;
  description: string;
  owner_team: string;
  category: string;
  tier: string;
  criticality: string;
  sla_target_minutes: string;
  sla_unit: SlaUnit;
  service_type: ServiceCatalogType | "";
  value_stream: string;
};

const emptyForm: CatalogFormState = {
  service_id: "",
  name: "",
  description: "",
  owner_team: "",
  category: "",
  tier: "",
  criticality: "",
  sla_target_minutes: "0",
  sla_unit: DEFAULT_SLA_UNIT,
  service_type: "",
  value_stream: "",
};

const normalizeString = (value: string) => value.trim();

const slaMinutesForSubmit = (state: CatalogFormState): number => {
  const raw = Number(state.sla_target_minutes);
  if (!Number.isFinite(raw) || raw < 0) {
    return 0;
  }
  return Math.round(raw * SLA_UNITS[state.sla_unit].factor);
};

const toCreatePayload = (state: CatalogFormState): ServiceCatalogCreatePayload => ({
  // service_id is intentionally omitted on create — the backend mints it
  // and returns the assigned id in the 201 response (S1).
  name: normalizeString(state.name),
  description: normalizeString(state.description),
  service_type: state.service_type as ServiceCatalogType,
  value_stream: normalizeString(state.value_stream),
  owner_team: normalizeString(state.owner_team) || null,
  category: normalizeString(state.category) || null,
  tier: normalizeString(state.tier) || null,
  criticality: normalizeString(state.criticality) || null,
  sla_target_minutes: slaMinutesForSubmit(state),
});

const toUpdatePayload = (state: CatalogFormState): ServiceCatalogUpdatePayload => ({
  service_id: normalizeString(state.service_id),
  name: normalizeString(state.name),
  description: normalizeString(state.description) || null,
  service_type: state.service_type ? (state.service_type as ServiceCatalogType) : undefined,
  value_stream: normalizeString(state.value_stream) || undefined,
  owner_team: normalizeString(state.owner_team) || null,
  category: normalizeString(state.category) || null,
  tier: normalizeString(state.tier) || null,
  criticality: normalizeString(state.criticality) || null,
  sla_target_minutes: slaMinutesForSubmit(state),
});

const ItsmServiceCatalogForm: React.FC = () => {
  const [catalogs, setCatalogs] = useState<ServiceCatalogResponse[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<FormMode | null>(null);
  const [selectedServiceId, setSelectedServiceId] = useState<string>("");
  const [formState, setFormState] = useState<CatalogFormState>(emptyForm);
  const [importError, setImportError] = useState<ImportValidationFailure | null>(null);
  const [importInfo, setImportInfo] = useState<string | null>(null);
  // Feature #480 S1: hold the auto-minted service_id returned by the
  // backend so the create form can render it read-only after save.
  const [createdServiceId, setCreatedServiceId] = useState<string | null>(null);

  // Feature #480 S2/S3/S4/S5 — managed lookup sources backing the form
  // dropdowns. Each hook exposes React-Query state + a list of values.
  const valueStreamsQuery = useValueStreams();
  const tierQuery = useTiers();
  const criticalityQuery = useCriticalities();
  const { owners, isEmpty: ownersEmpty } = useOwners();
  const { categories, isEmpty: categoriesEmpty } = useCategories();

  const hasCatalogs = useMemo(() => catalogs.length > 0, [catalogs]);

  const toDictionaryOptions = (
    list: DictionaryValueRecord[] | undefined,
  ): DictionaryValueRecord[] => list ?? [];

  const loadCatalogs = async () => {
    setLoading(true);
    setError(null);
    try {
      const catalogItems = await listServiceCatalog();
      setCatalogs(catalogItems);
    } catch (err) {
      setError(extractErrorMessage(err, "Unable to load service catalog."));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadCatalogs();
  }, []);

  const onResetForm = () => {
    setMode(null);
    setSelectedServiceId("");
    setFormState(emptyForm);
    setCreatedServiceId(null);
  };

  const onStartCreate = () => {
    setMode("create");
    setSelectedServiceId("");
    setFormState({ ...emptyForm, sla_unit: DEFAULT_SLA_UNIT });
    setCreatedServiceId(null);
  };

  const onStartEdit = (catalog: ServiceCatalogResponse) => {
    setMode("edit");
    setSelectedServiceId(catalog.service_id);
    setCreatedServiceId(null);
    setFormState({
      service_id: catalog.service_id,
      name: catalog.name,
      description: catalog.description ?? "",
      owner_team: catalog.owner_team ?? "",
      category: catalog.category ?? "",
      tier: catalog.tier ?? "",
      criticality: catalog.criticality ?? "",
      sla_target_minutes: String(catalog.sla_target_minutes),
      // The persisted value is already minutes, so edit mode keeps the
      // minutes unit — defaulting to hours would silently rescale the SLA
      // on the next save.
      sla_unit: "minutes",
      service_type: catalog.service_type,
      value_stream: catalog.value_stream,
    });
  };

  const onChange = <K extends keyof CatalogFormState>(field: K, value: CatalogFormState[K]) => {
    setFormState((prev) => ({ ...prev, [field]: value }));
  };

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);

    if (mode === "edit" && !formState.service_id.trim()) {
      setError("Service ID is required to update an existing catalog.");
      return;
    }
    if (!formState.name.trim()) {
      setError("Name is required.");
      return;
    }
    if (!formState.description.trim()) {
      setError("Description is required.");
      return;
    }
    if (!formState.service_type) {
      setError("Service type is required.");
      return;
    }
    if (!formState.value_stream.trim()) {
      setError("Value stream is required.");
      return;
    }
    const sla = Number(formState.sla_target_minutes);
    if (Number.isNaN(sla) || sla < 0) {
      setError("SLA target must be a non-negative number.");
      return;
    }

    try {
      if (mode === "edit" && selectedServiceId) {
        await updateServiceCatalog(selectedServiceId, toUpdatePayload(formState));
        await loadCatalogs();
        onResetForm();
      } else {
        const created = await createServiceCatalog(toCreatePayload(formState));
        // Feature #480 S1: the backend mints the service_id and returns it
        // in the 201 response. Keep it visible (read-only) instead of
        // clearing it away together with the rest of the form.
        const assigned =
          created && typeof (created as ServiceCatalogResponse).service_id === "string"
            ? (created as ServiceCatalogResponse).service_id
            : null;
        setCreatedServiceId(assigned);
        // Reset the editable fields so a second submit cannot create a
        // duplicate of the record that was just minted.
        setFormState({ ...emptyForm, sla_unit: DEFAULT_SLA_UNIT });
        await loadCatalogs();
      }
    } catch (err) {
      setError(extractErrorMessage(err, "Could not save service catalog record."));
    }
  };

  const onDeactivate = async (serviceId: string) => {
    try {
      await deactivateServiceCatalog(serviceId);
      await loadCatalogs();
    } catch (err) {
      setError(extractErrorMessage(err, "Could not deactivate service catalog record."));
    }
  };

  const onDownloadTemplate = async () => {
    setError(null);
    setImportError(null);
    setImportInfo(null);
    try {
      await downloadCatalogTemplate();
    } catch (err) {
      setError(extractErrorMessage(err, "Could not download the import template."));
    }
  };

  const onImportFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setImportError(null);
    setImportInfo(null);
    setError(null);
    try {
      await importCatalogWorkbook(file);
      setImportInfo("Catalog imported successfully.");
      await loadCatalogs();
    } catch (err) {
      const structured = extractImportError(err);
      if (structured) {
        setImportError(structured);
      } else {
        setError(extractErrorMessage(err, "Could not import catalog."));
      }
    }
  };

  return (
    <div className="h-full flex flex-col p-6 gap-4 overflow-hidden">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-3xl font-black text-white tracking-tighter uppercase">
            Service Catalog
          </h1>
          <p className="text-xs font-black text-neutral-400 uppercase tracking-wider">
            Manage typed, governed service definitions in a dedicated surface distinct from CI
            inventory.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            className="px-4 py-2 rounded-lg font-bold bg-white/10 hover:bg-white/20 text-white text-sm"
            onClick={onDownloadTemplate}
            aria-label="Download import template"
          >
            Download Template
          </button>
          <label className="px-4 py-2 rounded-lg font-bold bg-white/10 hover:bg-white/20 text-white text-sm cursor-pointer">
            Import Workbook
            <input
              type="file"
              accept=".xlsx"
              className="hidden"
              aria-label="Import workbook"
              onChange={onImportFile}
            />
          </label>
          <button
            onClick={onStartCreate}
            type="button"
            className="px-4 py-2 rounded-lg font-bold bg-brand-600 hover:bg-brand-500 text-white text-sm"
            aria-label="New Service Catalog"
          >
            New Service Catalog
          </button>
        </div>
      </header>

      {error && (
        <div
          className="rounded-lg border border-red-500/30 bg-red-500/10 text-red-300 p-3 text-sm"
          role="alert"
        >
          {error}
        </div>
      )}

      {importInfo && (
        <div
          className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 text-emerald-300 p-3 text-sm"
          role="status"
        >
          {importInfo}
        </div>
      )}

      {importError && (
        <div
          className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm space-y-2"
          role="alert"
        >
          <p className="text-red-300 font-bold">{importError.message}</p>
          <table className="w-full text-left text-xs">
            <thead className="text-red-200">
              <tr>
                <th className="p-1">Row</th>
                <th className="p-1">Field</th>
                <th className="p-1">Code</th>
                <th className="p-1">Reason</th>
              </tr>
            </thead>
            <tbody>
              {importError.errors.map((err, idx) => (
                <tr key={`${err.row}-${err.field}-${idx}`} className="border-t border-red-500/20">
                  <td className="p-1">
                    Row {err.row ?? "?"} — {err.field}
                  </td>
                  <td className="p-1 text-red-200">{err.field}</td>
                  <td className="p-1 text-red-200">{err.code}</td>
                  <td className="p-1 text-red-200">{err.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {mode && (
        <form className="grid gap-3 glass rounded-xl border border-white/5 p-4" onSubmit={onSubmit}>
          <h2 className="text-sm font-black uppercase text-neutral-300">
            {mode === "create" ? "Create Service Catalog" : `Edit Service ${selectedServiceId}`}
          </h2>

          {mode === "edit" && (
            <p className="text-xs text-neutral-400">
              Service ID is assigned by the system on creation and cannot be changed.
            </p>
          )}

          {mode === "create" && createdServiceId && (
            <div
              className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-3 text-sm space-y-1"
              role="status"
            >
              <p className="text-emerald-300 font-bold">Service created.</p>
              <p className="text-[11px] text-emerald-200/80">
                The system assigned the service ID below on creation. It is read-only and cannot be
                changed.
              </p>
              <label className="block text-xs text-emerald-200" htmlFor="assigned_service_id">
                Service ID
              </label>
              <input
                id="assigned_service_id"
                className="mt-1 w-full bg-black/40 border border-white/10 p-2 rounded text-white"
                value={createdServiceId}
                readOnly
                aria-label="Service ID"
              />
            </div>
          )}

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <label className="text-xs text-neutral-300 sm:col-span-2" htmlFor="name">
              Name
              <input
                id="name"
                className="mt-1 w-full bg-black/40 border border-white/10 p-2 rounded text-white"
                value={formState.name}
                onChange={(event) => onChange("name", event.target.value)}
                aria-label="Name"
              />
            </label>
            <label className="text-xs text-neutral-300 sm:col-span-2" htmlFor="description">
              Description
              <textarea
                id="description"
                className="mt-1 w-full bg-black/40 border border-white/10 p-2 rounded text-white"
                value={formState.description}
                onChange={(event) => onChange("description", event.target.value)}
                aria-label="Description"
              />
            </label>

            <label className="text-xs text-neutral-300" htmlFor="service_type">
              Service Type
              <select
                id="service_type"
                className="mt-1 w-full bg-black/40 border border-white/10 p-2 rounded text-white"
                value={formState.service_type}
                onChange={(event) =>
                  onChange("service_type", event.target.value as ServiceCatalogType)
                }
                disabled={mode === "edit"}
                aria-label="Service Type"
              >
                <option value="">Select service type…</option>
                <option value="incident">incident</option>
                <option value="service_request">service_request</option>
              </select>
            </label>

            <div className="text-xs text-neutral-300">
              <label htmlFor="value_stream">
                Value Stream
                <span className="ml-2 text-[10px] text-brand-300 underline-offset-2">
                  <Link to={DICTIONARY_MANAGER_ROUTE} className="hover:underline">
                    + Add new value stream
                  </Link>
                </span>
              </label>
              <select
                id="value_stream"
                className="mt-1 w-full bg-black/40 border border-white/10 p-2 rounded text-white"
                value={formState.value_stream}
                onChange={(event) => onChange("value_stream", event.target.value)}
                aria-label="Value Stream"
              >
                <option value="">Select value stream…</option>
                {toDictionaryOptions(valueStreamsQuery.data).map((entry) => (
                  <option key={entry.value} value={entry.value}>
                    {entry.label}
                  </option>
                ))}
              </select>
              <p className="mt-1 text-[10px] text-neutral-500">
                Source: managed value stream dictionary (Administration → Dictionaries).
              </p>
            </div>

            <div className="text-xs text-neutral-300">
              <label htmlFor="owner_team">Owner Team</label>
              <select
                id="owner_team"
                className="mt-1 w-full bg-black/40 border border-white/10 p-2 rounded text-white"
                value={formState.owner_team}
                onChange={(event) => onChange("owner_team", event.target.value)}
                aria-label="Owner Team"
              >
                <option value="">Select owner team…</option>
                {owners.map((owner) => (
                  <option key={owner.name} value={owner.name}>
                    {owner.name}
                  </option>
                ))}
              </select>
              {ownersEmpty && (
                <p className="mt-1 text-[10px] text-amber-300" role="status">
                  No owner groups exist yet — create one in the Owners tab first.
                </p>
              )}
            </div>

            <div className="text-xs text-neutral-300">
              <label htmlFor="category">Category</label>
              <select
                id="category"
                className="mt-1 w-full bg-black/40 border border-white/10 p-2 rounded text-white"
                value={formState.category}
                onChange={(event) => onChange("category", event.target.value)}
                aria-label="Category"
              >
                <option value="">Select category…</option>
                {categories.map((category) => (
                  <option key={category.name} value={category.name}>
                    {category.name}
                  </option>
                ))}
              </select>
              <p className="mt-1 text-[10px] text-neutral-500">
                ITIL-aligned taxonomy — see docs/itsm/service-catalog.md for the canonical list.
              </p>
              <ul
                aria-label="Canonical ITIL categories"
                className="mt-1 flex flex-wrap gap-x-2 text-[10px] text-neutral-400"
              >
                {CANONICAL_CATEGORIES.map((category) => (
                  <li key={category}>{category}</li>
                ))}
              </ul>
              {categoriesEmpty && (
                <p className="mt-1 text-[10px] text-amber-300" role="status">
                  No categories defined yet — seed the canonical ITIL set listed above first.
                </p>
              )}
            </div>

            <div className="text-xs text-neutral-300">
              <label htmlFor="tier">Tier</label>
              <select
                id="tier"
                className="mt-1 w-full bg-black/40 border border-white/10 p-2 rounded text-white"
                value={formState.tier}
                onChange={(event) => onChange("tier", event.target.value)}
                aria-label="Tier"
              >
                <option value="">Select tier…</option>
                {toDictionaryOptions(tierQuery.data).map((entry) => (
                  <option key={entry.value} value={entry.value}>
                    {entry.label}
                  </option>
                ))}
              </select>
              <p className="mt-1 text-[10px] text-neutral-500">
                bronze / silver / gold / platinum — ITIL Service Design tier.
              </p>
            </div>

            <div className="text-xs text-neutral-300">
              <label htmlFor="criticality">Criticality</label>
              <select
                id="criticality"
                className="mt-1 w-full bg-black/40 border border-white/10 p-2 rounded text-white"
                value={formState.criticality}
                onChange={(event) => onChange("criticality", event.target.value)}
                aria-label="Criticality"
              >
                <option value="">Select criticality…</option>
                {toDictionaryOptions(criticalityQuery.data).map((entry) => (
                  <option key={entry.value} value={entry.value}>
                    {entry.label}
                  </option>
                ))}
              </select>
              <p className="mt-1 text-[10px] text-neutral-500">
                low / medium / high / critical — independent from tier; see the recommended pairing
                below.
              </p>
            </div>

            <div className="text-xs text-neutral-300 sm:col-span-2">
              <p className="font-bold text-neutral-200">Recommended tier / criticality pairing</p>
              <table
                aria-label="Recommended tier and criticality pairing"
                className="mt-1 w-full text-left text-[10px]"
              >
                <thead className="text-neutral-400">
                  <tr>
                    <th scope="col" className="p-1">
                      Tier
                    </th>
                    <th scope="col" className="p-1">
                      Recommended criticality
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {RECOMMENDED_TIER_CRITICALITY.map((pairing) => (
                    <tr key={pairing.tier} className="border-t border-white/5">
                      <td className="p-1">{pairing.tier}</td>
                      <td className="p-1">{pairing.criticality}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="mt-1 text-[10px] text-neutral-500">
                Recommended only — tier and criticality stay independent controls and the server
                does not enforce the pairing.
              </p>
            </div>

            <div className="text-xs text-neutral-300 sm:col-span-2">
              <label htmlFor="sla_target">SLA Target</label>
              <div className="mt-1 flex gap-2">
                <input
                  id="sla_target"
                  type="number"
                  min="0"
                  step="any"
                  className="flex-1 bg-black/40 border border-white/10 p-2 rounded text-white"
                  value={formState.sla_target_minutes}
                  onChange={(event) => onChange("sla_target_minutes", event.target.value)}
                  inputMode="numeric"
                  aria-label="SLA Target"
                />
                <select
                  className="bg-black/40 border border-white/10 p-2 rounded text-white"
                  value={formState.sla_unit}
                  onChange={(event) => onChange("sla_unit", event.target.value as SlaUnit)}
                  aria-label="SLA Unit"
                >
                  <option value="minutes">minutes</option>
                  <option value="hours">hours</option>
                  <option value="days">days</option>
                </select>
              </div>
              <p className="mt-1 text-[10px] text-neutral-500">
                Default unit: hours (ITIL service-hour convention). The entered value is converted
                to sla_target_minutes (int) before the request — the wire format never changes.
              </p>
            </div>

            {mode === "edit" && (
              <label className="text-xs text-neutral-300 sm:col-span-2" htmlFor="service_id">
                Service ID
                <input
                  id="service_id"
                  className="mt-1 w-full bg-black/40 border border-white/10 p-2 rounded text-white"
                  value={formState.service_id}
                  onChange={(event) => onChange("service_id", event.target.value)}
                  disabled
                  readOnly
                  aria-label="Service ID"
                />
              </label>
            )}
          </div>
          <div className="flex gap-3 justify-end">
            <button
              type="button"
              className="px-3 py-2 rounded-lg border border-white/20 text-white text-sm"
              onClick={onResetForm}
            >
              Cancel
            </button>
            <button
              className="px-3 py-2 rounded-lg bg-brand-600 text-white font-bold text-sm"
              type="submit"
            >
              Save
            </button>
          </div>
        </form>
      )}

      <section className="flex-1 min-h-0 glass rounded-xl border border-white/5 p-4 overflow-auto">
        {loading ? (
          <p className="text-sm text-neutral-400">Loading service catalog...</p>
        ) : hasCatalogs ? (
          <div className="space-y-3">
            {catalogs.map((catalog) => (
              <article
                key={catalog.service_id}
                className={`p-4 rounded-lg border ${catalog.active ? "border-white/10" : "border-red-500/40"} bg-black/40 flex items-center justify-between gap-3`}
                aria-label={`service catalog ${catalog.service_id}`}
              >
                <div className="space-y-1">
                  <p className="text-white font-bold">{catalog.name}</p>
                  <p className="text-xs text-neutral-400">
                    {catalog.service_id} · {catalog.category || "No category"} ·{" "}
                    {catalog.owner_team || "Unowned"}
                  </p>
                  <p className="text-xs text-neutral-500">
                    SLA {catalog.sla_target_minutes} min · {catalog.criticality || "Unknown"} ·{" "}
                    {catalog.tier || "Unknown tier"} · type {catalog.service_type} · stream{" "}
                    {catalog.value_stream}
                  </p>
                  <p className="text-[11px] text-neutral-500">
                    {catalog.active ? "Status: Active" : "Status: Deactivated"}
                  </p>
                </div>
                <div className="flex gap-2">
                  <button
                    type="button"
                    className="px-3 py-2 rounded-lg bg-white/5 text-xs font-black text-white hover:bg-white/10"
                    onClick={() => onStartEdit(catalog)}
                    aria-label={`Edit ${catalog.service_id}`}
                  >
                    Edit
                  </button>
                  {catalog.active ? (
                    <button
                      type="button"
                      className="px-3 py-2 rounded-lg bg-amber-500/20 border border-amber-300/40 text-xs font-black text-amber-200 hover:bg-amber-500/30"
                      onClick={() => onDeactivate(catalog.service_id)}
                      aria-label={`Deactivate ${catalog.service_id}`}
                    >
                      Deactivate
                    </button>
                  ) : (
                    <button
                      type="button"
                      className="px-3 py-2 rounded-lg bg-white/5 text-xs font-black text-white/40 cursor-not-allowed"
                      disabled
                    >
                      Deactivated
                    </button>
                  )}
                </div>
              </article>
            ))}
          </div>
        ) : (
          <p className="text-sm text-neutral-400">
            No service catalog entries yet. Create your first service above.
          </p>
        )}
      </section>
    </div>
  );
};

const ItsmServiceCatalogPage: React.FC = () => {
  // The S2/S5 lookup hooks need a React-Query client. The SPA mounts this
  // page inside the app-level QueryClientProvider (see index.tsx), but the
  // component is also mounted standalone (unit tests, embedded surfaces),
  // so fall back to a local client instead of throwing "No QueryClient set".
  const inheritedClient = useContext(QueryClientContext);
  const fallbackClient = useMemo(
    () =>
      new QueryClient({
        defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
      }),
    [],
  );

  return (
    <QueryClientProvider client={inheritedClient ?? fallbackClient}>
      <ItsmServiceCatalogForm />
    </QueryClientProvider>
  );
};

export default ItsmServiceCatalogPage;
