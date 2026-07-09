import React, { useEffect, useState } from "react";
import type { FormEvent } from "react";
import {
  createTicketFolio,
  listTicketFolios,
  transitionTicketFolio,
  updateTicketFolio,
} from "../services/itsm";
import type {
  TicketFolioCreatePayload,
  TicketFolioResponse,
  TicketFolioStatus,
  TicketFolioType,
} from "../types/itsm";
import TicketStatusStepper from "./TicketStatusStepper";

type TicketFormState = {
  ticket_id: string;
  type: TicketFolioType;
  title: string;
  description: string;
  service_catalog_id: string;
};

const emptyForm: TicketFormState = {
  ticket_id: "",
  type: "request",
  title: "",
  description: "",
  service_catalog_id: "",
};

const toCreatePayload = (state: TicketFormState): TicketFolioCreatePayload => ({
  ticket_id: state.ticket_id.trim(),
  type: state.type,
  title: state.title.trim(),
  description: state.description.trim() || null,
  service_catalog_id: state.service_catalog_id.trim() || null,
});

const statusLabel = (status: TicketFolioStatus) => status.replace("_", " ");

const ItsmTicketFolioPage: React.FC = () => {
  const [tickets, setTickets] = useState<TicketFolioResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [selectedTicketId, setSelectedTicketId] = useState<string | null>(null);
  const [formState, setFormState] = useState<TicketFormState>(emptyForm);

  const loadTickets = async () => {
    setLoading(true);
    setError(null);
    try {
      const items = await listTicketFolios({});
      setTickets(items);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load ITSM tickets.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadTickets();
  }, []);

  const onChange = (field: keyof TicketFormState, value: string) => {
    setFormState(prev => ({ ...prev, [field]: value }));
  };

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!formState.ticket_id.trim() || !formState.title.trim()) {
      setError("Ticket ID and Title are required.");
      return;
    }

    try {
      if (selectedTicketId) {
        await updateTicketFolio(selectedTicketId, {
          title: formState.title.trim(),
          description: formState.description.trim() || null,
          service_catalog_id: formState.service_catalog_id.trim() || null,
        });
      } else {
        await createTicketFolio(toCreatePayload(formState));
      }
      await loadTickets();
      setFormState(emptyForm);
      setSelectedTicketId(null);
      setShowForm(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save ticket folio.");
    }
  };

  const onStartEdit = (ticket: TicketFolioResponse) => {
    setSelectedTicketId(ticket.ticket_id);
    setFormState({
      ticket_id: ticket.ticket_id,
      type: ticket.type,
      title: ticket.title,
      description: ticket.description ?? "",
      service_catalog_id: ticket.service_catalog_id ?? "",
    });
    setShowForm(true);
  };

  const onTransition = async (ticketId: string, nextStatus: TicketFolioStatus) => {
    const closedReason = nextStatus === "closed" ? window.prompt("Close reason")?.trim() : undefined;
    if (nextStatus === "closed" && !closedReason) {
      setError("Closed tickets require a close reason.");
      return;
    }

    try {
      await transitionTicketFolio(ticketId, nextStatus, closedReason);
      await loadTickets();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not transition ticket folio.");
    }
  };

  return (
    <div className="h-full flex flex-col p-6 gap-4 overflow-hidden">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-3xl font-black text-white tracking-tighter uppercase">ITSM Tickets</h1>
          <p className="text-xs font-black text-neutral-400 uppercase tracking-wider">
            Manage request and incident folios independently from event workflows.
          </p>
        </div>
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
      </header>

      {error && (
        <div role="alert" className="rounded-lg border border-red-500/30 bg-red-500/10 text-red-300 p-3 text-sm">
          {error}
        </div>
      )}

      {showForm && (
        <form className="grid gap-3 glass rounded-xl border border-white/5 p-4" onSubmit={onSubmit}>
          <h2 className="text-sm font-black uppercase text-neutral-300">
            {selectedTicketId ? `Edit Ticket ${selectedTicketId}` : "Create Ticket Folio"}
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <label className="text-xs text-neutral-300" htmlFor="ticket_id">
              Ticket ID
              <input
                id="ticket_id"
                aria-label="Ticket ID"
                className="mt-1 w-full bg-black/40 border border-white/10 p-2 rounded text-white"
                value={formState.ticket_id}
                onChange={event => onChange("ticket_id", event.target.value)}
                disabled={Boolean(selectedTicketId)}
              />
            </label>
            <label className="text-xs text-neutral-300" htmlFor="type">
              Type
              <select
                id="type"
                aria-label="Type"
                className="mt-1 w-full bg-black/40 border border-white/10 p-2 rounded text-white"
                value={formState.type}
                onChange={event => onChange("type", event.target.value as TicketFolioType)}
                disabled={Boolean(selectedTicketId)}
              >
                <option value="request">request</option>
                <option value="incident">incident</option>
              </select>
            </label>
            <label className="text-xs text-neutral-300" htmlFor="title">
              Title
              <input
                id="title"
                aria-label="Title"
                className="mt-1 w-full bg-black/40 border border-white/10 p-2 rounded text-white"
                value={formState.title}
                onChange={event => onChange("title", event.target.value)}
              />
            </label>
            <label className="text-xs text-neutral-300" htmlFor="service_catalog_id">
              Service Catalog ID
              <input
                id="service_catalog_id"
                aria-label="Service Catalog ID"
                className="mt-1 w-full bg-black/40 border border-white/10 p-2 rounded text-white"
                value={formState.service_catalog_id}
                onChange={event => onChange("service_catalog_id", event.target.value)}
              />
            </label>
            <label className="text-xs text-neutral-300 sm:col-span-2" htmlFor="description">
              Description
              <textarea
                id="description"
                aria-label="Description"
                className="mt-1 w-full bg-black/40 border border-white/10 p-2 rounded text-white"
                value={formState.description}
                onChange={event => onChange("description", event.target.value)}
              />
            </label>
          </div>
          <div className="flex gap-2">
            <button type="submit" className="px-4 py-2 rounded-lg bg-brand-600 text-white font-bold">
              Save Ticket
            </button>
            <button type="button" className="px-4 py-2 rounded-lg bg-white/10 text-neutral-200 font-bold" onClick={() => {
              setShowForm(false);
              setSelectedTicketId(null);
              setFormState(emptyForm);
            }}>
              Cancel
            </button>
          </div>
        </form>
      )}

      <section className="flex-1 overflow-auto rounded-xl border border-white/5 glass">
        {loading ? (
          <div className="p-4 text-sm text-neutral-400">Loading ITSM tickets...</div>
        ) : tickets.length === 0 ? (
          <div className="p-4 text-sm text-neutral-400">No ticket folios found.</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="text-left text-neutral-400 uppercase text-xs">
              <tr>
                <th className="p-3">Ticket</th>
                <th className="p-3">Type</th>
                <th className="p-3">Service</th>
                <th className="p-3">Status</th>
                <th className="p-3">Next Step</th>
                <th className="p-3">Actions</th>
              </tr>
            </thead>
            <tbody>
              {tickets.map(ticket => (
                <tr key={ticket.ticket_id} className="border-t border-white/5">
                  <td className="p-3">
                    <div className="font-bold text-white">{ticket.title}</div>
                    <div className="text-xs text-neutral-500">{ticket.ticket_id}</div>
                  </td>
                  <td className="p-3 text-neutral-300">{ticket.type}</td>
                  <td className="p-3 text-neutral-300">{ticket.service_catalog_id || "Unassigned"}</td>
                  <td className="p-3 text-neutral-300">{statusLabel(ticket.status)}</td>
                  <td className="p-3">
                    <TicketStatusStepper
                      ticketId={ticket.ticket_id}
                      status={ticket.status}
                      onTransition={nextStatus => onTransition(ticket.ticket_id, nextStatus)}
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
