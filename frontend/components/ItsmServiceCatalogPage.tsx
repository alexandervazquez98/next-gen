import React, { useEffect, useMemo, useState } from "react";
import type { ChangeEvent, FormEvent } from "react";
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

type FormMode = "create" | "edit";

type CatalogFormState = {
  service_id: string;
  name: string;
  description: string;
  owner_team: string;
  category: string;
  tier: string;
  criticality: string;
  sla_target_minutes: string;
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
  service_type: "",
  value_stream: "",
};

const normalizeString = (value: string) => value.trim();

const toCreatePayload = (state: CatalogFormState): ServiceCatalogCreatePayload => ({
  service_id: normalizeString(state.service_id),
  name: normalizeString(state.name),
  description: normalizeString(state.description),
  service_type: state.service_type as ServiceCatalogType,
  value_stream: normalizeString(state.value_stream),
  owner_team: normalizeString(state.owner_team) || null,
  category: normalizeString(state.category) || null,
  tier: normalizeString(state.tier) || null,
  criticality: normalizeString(state.criticality) || null,
  sla_target_minutes: Number(state.sla_target_minutes),
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
  sla_target_minutes: Number(state.sla_target_minutes),
});

const ItsmServiceCatalogPage: React.FC = () => {
  const [catalogs, setCatalogs] = useState<ServiceCatalogResponse[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<FormMode | null>(null);
  const [selectedServiceId, setSelectedServiceId] = useState<string>("");
  const [formState, setFormState] = useState<CatalogFormState>(emptyForm);
  const [importError, setImportError] = useState<ImportValidationFailure | null>(null);
  const [importInfo, setImportInfo] = useState<string | null>(null);

  const hasCatalogs = useMemo(() => catalogs.length > 0, [catalogs]);

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
  };

  const onStartCreate = () => {
    setMode("create");
    setSelectedServiceId("");
    setFormState(emptyForm);
  };

  const onStartEdit = (catalog: ServiceCatalogResponse) => {
    setMode("edit");
    setSelectedServiceId(catalog.service_id);
    setFormState({
      service_id: catalog.service_id,
      name: catalog.name,
      description: catalog.description ?? "",
      owner_team: catalog.owner_team ?? "",
      category: catalog.category ?? "",
      tier: catalog.tier ?? "",
      criticality: catalog.criticality ?? "",
      sla_target_minutes: String(catalog.sla_target_minutes),
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

    if (!formState.name.trim() || !formState.service_id.trim()) {
      setError("Service ID and Name are required.");
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
      setError("SLA target minutes must be a non-negative number.");
      return;
    }

    try {
      if (mode === "edit" && selectedServiceId) {
        await updateServiceCatalog(selectedServiceId, toUpdatePayload(formState));
      } else {
        await createServiceCatalog(toCreatePayload(formState));
      }

      await loadCatalogs();
      onResetForm();
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
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <label className="text-xs text-neutral-300" htmlFor="service_id">
              Service ID
              <input
                id="service_id"
                className="mt-1 w-full bg-black/40 border border-white/10 p-2 rounded text-white"
                value={formState.service_id}
                onChange={(event) => onChange("service_id", event.target.value)}
                disabled={mode === "edit"}
                aria-label="Service ID"
              />
            </label>
            <label className="text-xs text-neutral-300" htmlFor="name">
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
            <label className="text-xs text-neutral-300" htmlFor="value_stream">
              Value Stream
              <input
                id="value_stream"
                className="mt-1 w-full bg-black/40 border border-white/10 p-2 rounded text-white"
                value={formState.value_stream}
                onChange={(event) => onChange("value_stream", event.target.value)}
                aria-label="Value Stream"
              />
            </label>
            <label className="text-xs text-neutral-300" htmlFor="owner_team">
              Owner Team
              <input
                id="owner_team"
                className="mt-1 w-full bg-black/40 border border-white/10 p-2 rounded text-white"
                value={formState.owner_team}
                onChange={(event) => onChange("owner_team", event.target.value)}
                aria-label="Owner Team"
              />
            </label>
            <label className="text-xs text-neutral-300" htmlFor="category">
              Category
              <input
                id="category"
                className="mt-1 w-full bg-black/40 border border-white/10 p-2 rounded text-white"
                value={formState.category}
                onChange={(event) => onChange("category", event.target.value)}
                aria-label="Category"
              />
            </label>
            <label className="text-xs text-neutral-300" htmlFor="tier">
              Tier
              <input
                id="tier"
                className="mt-1 w-full bg-black/40 border border-white/10 p-2 rounded text-white"
                value={formState.tier}
                onChange={(event) => onChange("tier", event.target.value)}
                aria-label="Tier"
              />
            </label>
            <label className="text-xs text-neutral-300" htmlFor="criticality">
              Criticality
              <input
                id="criticality"
                className="mt-1 w-full bg-black/40 border border-white/10 p-2 rounded text-white"
                value={formState.criticality}
                onChange={(event) => onChange("criticality", event.target.value)}
                aria-label="Criticality"
              />
            </label>
            <label className="text-xs text-neutral-300" htmlFor="sla_target_minutes">
              SLA Target Minutes
              <input
                id="sla_target_minutes"
                className="mt-1 w-full bg-black/40 border border-white/10 p-2 rounded text-white"
                value={formState.sla_target_minutes}
                onChange={(event) => onChange("sla_target_minutes", event.target.value)}
                inputMode="numeric"
                aria-label="SLA Target Minutes"
              />
            </label>
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

export default ItsmServiceCatalogPage;
