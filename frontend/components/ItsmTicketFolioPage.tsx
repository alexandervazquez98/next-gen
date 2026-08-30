import React, { useEffect, useMemo, useState } from "react";
import type { ChangeEvent, FormEvent } from "react";
import {
  createTicketFolio,
  downloadTicketTemplate,
  extractErrorMessage,
  extractImportError,
  importTicketWorkbook,
  listActiveUsers,
  listServiceCatalog,
  listTicketFolios,
  transitionTicketFolio,
  updateTicketFolio,
} from "../services/itsm";
import type {
  ActiveUser,
  ImportValidationFailure,
  ServiceCatalogResponse,
  TicketFolioCreatePayload,
  TicketFolioResponse,
  TicketFolioStatus,
  TicketFolioType,
} from "../types/itsm";
import TicketStatusStepper from "./TicketStatusStepper";

type TicketFormState = {
  type: TicketFolioType;
  title: string;
  description: string;
  service_catalog_id: string;
  assignee_username: string;
};

const emptyForm: TicketFormState = {
  type: "incident",
  title: "",
  description: "",
  service_catalog_id: "",
  assignee_username: "",
};

const toCreatePayload = (state: TicketFormState): TicketFolioCreatePayload => ({
  type: state.type,
  title: state.title.trim(),
  description: state.description.trim() ? state.description.trim() : null,
  service_catalog_id: state.service_catalog_id.trim(),
  assignee_username: state.assignee_username.trim(),
});

const statusLabel = (status: TicketFolioStatus) => status.replace("_", " ");

const ItsmTicketFolioPage: React.FC = () => {
  const [tickets, setTickets] = useState<TicketFolioResponse[]>([]);
  const [catalog, setCatalog] = useState<ServiceCatalogResponse[]>([]);
  const [assignees, setAssignees] = useState<ActiveUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [selectedTicketId, setSelectedTicketId] = useState<number | null>(null);
  const [formState, setFormState] = useState<TicketFormState>(emptyForm);
  const [importError, setImportError] = useState<ImportValidationFailure | null>(null);
  const [importInfo, setImportInfo] = useState<string | null>(null);

  const activeCatalog = useMemo(
    () => catalog.filter((c) => c.active),
    [catalog],
  );

  const compatibleServices = useMemo(
    () => activeCatalog.filter((c) => c.service_type === formState.type),
    [activeCatalog, formState.type],
  );

  const loadTickets = async () => {
    setLoading(true);
    setError(null);
    try {
      const items = await listTicketFolios({});
      setTickets(items);
    } catch (err) {
      setError(extractErrorMessage(err, "Unable to load tickets."));
    } finally {
      setLoading(false);
    }
  };

  const loadCatalogAndAssignees = async () => {
    try {
      const [catalogItems, userItems] = await Promise.all([
        listServiceCatalog(),
        listActiveUsers(),
      ]);
      setCatalog(catalogItems);
      setAssignees(userItems);
    } catch (err) {
      setError(extractErrorMessage(err, "Unable to load service catalog or users."));
    }
  };

  useEffect(() => {
    void loadTickets();
    void loadCatalogAndAssignees();
  }, []);

  const onChange = <K extends keyof TicketFormState>(
    field: K,
    value: TicketFormState[K],
  ) => {
    setFormState((prev) => {
      const next = { ...prev, [field]: value };
      // Reset incompatible service selection when ticket type changes.
      if (field === "type" && prev.service_catalog_id) {
        const stillCompatible = catalog.some(
          (c) => c.service_id === prev.service_catalog_id && c.service_type === value,
        );
        if (!stillCompatible) next.service_catalog_id = "";
      }
      return next;
    });
  };

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);

    if (!formState.title.trim()) {
      setError("Title is required.");
      return;
    }
    if (!formState.service_catalog_id) {
      setError("Service is required.");
      return;
    }
    if (!formState.assignee_username) {
      setError("Assignee is required.");
      return;
    }

    try {
      if (selectedTicketId !== null) {
        await updateTicketFolio(selectedTicketId, {
          title: formState.title.trim(),
          description: formState.description.trim() || null,
          service_catalog_id: formState.service_catalog_id.trim(),
        });
      } else {
        await createTicketFolio(toCreatePayload(formState));
      }
      await loadTickets();
      setFormState(emptyForm);
      setSelectedTicketId(null);
      setShowForm(false);
    } catch (err) {
      const message = extractErrorMessage(err, "Could not save ticket folio.");
      setError(message);
    }
  };

  const onStartEdit = (ticket: TicketFolioResponse) => {
    setSelectedTicketId(ticket.ticket_id);
    setFormState({
      type: ticket.type,
      title: ticket.title,
      description: ticket.description ?? "",
      service_catalog_id: ticket.service_catalog_id ?? "",
      assignee_username: ticket.assignee_username ?? "",
    });
    setShowForm(true);
  };

  const onTransition = async (ticketId: number, nextStatus: TicketFolioStatus) => {
    const closedReason =
      nextStatus === "closed" ? window.prompt("Close reason")?.trim() : undefined;
    if (nextStatus === "closed" && !closedReason) {
      setError("Closed tickets require a close reason.");
      return;
    }

    try {
      await transitionTicketFolio(ticketId, nextStatus, closedReason);
      await loadTickets();
    } catch (err) {
      setError(extractErrorMessage(err, "Could not transition ticket folio."));
    }
  };

  const onDownloadTemplate = async () => {
    setError(null);
    setImportError(null);
    setImportInfo(null);
    try {
      await downloadTicketTemplate();
    } catch (err) {
      setError(extractErrorMessage(err, "Could not download the import template."));
    }
  };

  const onImportFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = ""; // allow re-upload of the same file
    if (!file) return;
    setImportError(null);
    setImportInfo(null);
    setError(null);
    try {
      await importTicketWorkbook(file);
      setImportInfo("Tickets imported successfully.");
      await loadTickets();
    } catch (err) {
      const structured = extractImportError(err);
      if (structured) {
        setImportError(structured);
      } else {
        setError(extractErrorMessage(err, "Could not import tickets."));
      }
    }
  };

  return (
    <div className="h-full flex flex-col p-6 gap-4 overflow-hidden">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-3xl font-black text-white tracking-tighter uppercase">
            Service Management
          </h1>
          <p className="text-xs font-black text-neutral-400 uppercase tracking-wider">
            Manage incident and service request folios independently from event workflows.
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
            type="button"
            className="px-4 py-2 rounded-lg font-bold bg-brand-600 hover:bg-brand-500 text-white text-sm"
            onClick={() => {
              setSelectedTicketId(null);
              setFormState(emptyForm);
              setShowForm(true);
            }}
          >
            New Ticket
          </button>
        </div>
      </header>

      {error && (
        <div
          role="alert"
          className="rounded-lg border border-red-500/30 bg-red-500/10 text-red-300 p-3 text-sm"
        >
          {error}
        </div>
      )}

      {importInfo && (
        <div
          role="status"
          className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 text-emerald-300 p-3 text-sm"
        >
          {importInfo}
        </div>
      )}

      {importError && (
        <div
          role="alert"
          className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm space-y-2"
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
                  <td className="p-1">Row {err.row ?? "?"} — {err.field}</td>
                  <td className="p-1 text-red-200">{err.field}</td>
                  <td className="p-1 text-red-200">{err.code}</td>
                  <td className="p-1 text-red-200">{err.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showForm && (
        <form className="grid gap-3 glass rounded-xl border border-white/5 p-4" onSubmit={onSubmit}>
          <h2 className="text-sm font-black uppercase text-neutral-300">
            {selectedTicketId !== null ? `Edit Ticket ${selectedTicketId}` : "Create Ticket Folio"}
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <label className="text-xs text-neutral-300" htmlFor="type">
              Type
              <select
                id="type"
                aria-label="Type"
                className="mt-1 w-full bg-black/40 border border-white/10 p-2 rounded text-white"
                value={formState.type}
                onChange={(event) => onChange("type", event.target.value as TicketFolioType)}
                disabled={selectedTicketId !== null}
              >
                <option value="incident">incident</option>
                <option value="service_request">service_request</option>
              </select>
            </label>
            <label className="text-xs text-neutral-300" htmlFor="service_catalog_id">
              Service
              <select
                id="service_catalog_id"
                aria-label="Service"
                className="mt-1 w-full bg-black/40 border border-white/10 p-2 rounded text-white"
                value={formState.service_catalog_id}
                onChange={(event) => onChange("service_catalog_id", event.target.value)}
                disabled={selectedTicketId !== null}
              >
                <option value="">Select a compatible service…</option>
                {compatibleServices.map((svc) => (
                  <option key={svc.service_id} value={svc.service_id}>
                    {svc.service_id} — {svc.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-xs text-neutral-300 sm:col-span-2" htmlFor="title">
              Title
              <input
                id="title"
                aria-label="Title"
                className="mt-1 w-full bg-black/40 border border-white/10 p-2 rounded text-white"
                value={formState.title}
                onChange={(event) => onChange("title", event.target.value)}
              />
            </label>
            <label className="text-xs text-neutral-300 sm:col-span-2" htmlFor="assignee_username">
              Assignee
              <select
                id="assignee_username"
                aria-label="Assignee"
                className="mt-1 w-full bg-black/40 border border-white/10 p-2 rounded text-white"
                value={formState.assignee_username}
                onChange={(event) => onChange("assignee_username", event.target.value)}
                aria-required="true"
                disabled={selectedTicketId !== null}
              >
                <option value="">Select an active assignee…</option>
                {assignees.map((user) => (
                  <option key={user.username} value={user.username}>
                    {user.username}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-xs text-neutral-300 sm:col-span-2" htmlFor="description">
              Description
              <textarea
                id="description"
                aria-label="Description"
                className="mt-1 w-full bg-black/40 border border-white/10 p-2 rounded text-white"
                value={formState.description}
                onChange={(event) => onChange("description", event.target.value)}
              />
            </label>
          </div>
          <div className="flex gap-2">
            <button
              type="submit"
              className="px-4 py-2 rounded-lg bg-brand-600 text-white font-bold"
            >
              Save Ticket
            </button>
            <button
              type="button"
              className="px-4 py-2 rounded-lg bg-white/10 text-neutral-200 font-bold"
              onClick={() => {
                setShowForm(false);
                setSelectedTicketId(null);
                setFormState(emptyForm);
              }}
            >
              Cancel
            </button>
          </div>
        </form>
      )}

      <section className="flex-1 overflow-auto rounded-xl border border-white/5 glass">
        {loading ? (
          <div className="p-4 text-sm text-neutral-400">Loading tickets...</div>
        ) : tickets.length === 0 ? (
          <div className="p-4 text-sm text-neutral-400">No ticket folios found.</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="text-left text-neutral-400 uppercase text-xs">
              <tr>
                <th className="p-3">Ticket</th>
                <th className="p-3">Type</th>
                <th className="p-3">Service</th>
                <th className="p-3">Assignee</th>
                <th className="p-3">Status</th>
                <th className="p-3">Next Step</th>
                <th className="p-3">Actions</th>
              </tr>
            </thead>
            <tbody>
              {tickets.map((ticket) => (
                <tr key={ticket.ticket_id} className="border-t border-white/5">
                  <td className="p-3">
                    <div className="font-bold text-white">{ticket.title}</div>
                    <div className="text-xs text-neutral-500">#{ticket.ticket_id}</div>
                  </td>
                  <td className="p-3 text-neutral-300">{ticket.type}</td>
                  <td className="p-3 text-neutral-300">
                    {ticket.service_catalog_id || "Unassigned"}
                  </td>
                  <td className="p-3 text-neutral-300">
                    {ticket.assignee_username || "—"}
                    {ticket.assignee_currently_active === false && (
                      <span className="ml-2 text-[10px] uppercase text-amber-300">
                        (inactive)
                      </span>
                    )}
                  </td>
                  <td className="p-3 text-neutral-300">{statusLabel(ticket.status)}</td>
                  <td className="p-3">
                    <TicketStatusStepper
                      ticketId={String(ticket.ticket_id)}
                      status={ticket.status}
                      onTransition={(nextStatus) => onTransition(ticket.ticket_id, nextStatus)}
                    />
                  </td>
                  <td className="p-3">
                    <button
                      type="button"
                      className="px-3 py-1.5 rounded-lg text-xs font-bold bg-white/10 hover:bg-white/20 text-neutral-200 disabled:opacity-50"
                      onClick={() => onStartEdit(ticket)}
                      disabled={ticket.status === "closed"}
                      aria-label={`Edit ${ticket.ticket_id}`}
                    >
                      Edit
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
};

export default ItsmTicketFolioPage;