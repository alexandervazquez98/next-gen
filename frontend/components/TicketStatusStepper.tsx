import React from "react";
import type { TicketFolioStatus } from "../types/itsm";

const statusOrder: TicketFolioStatus[] = [
  "open",
  "in_progress",
  "in_validation",
  "resolved",
  "closed",
];

// eslint-disable-next-line no-unused-vars
type TicketTransitionHandler = (status: TicketFolioStatus) => void;

interface TicketStatusStepperProps {
  ticketId: string;
  status: TicketFolioStatus;
  onTransition: TicketTransitionHandler;
}

const TicketStatusStepper: React.FC<TicketStatusStepperProps> = ({
  ticketId,
  status,
  onTransition,
}) => {
  const currentIndex = statusOrder.indexOf(status);
  const nextStatus = currentIndex >= 0 ? statusOrder[currentIndex + 1] : undefined;

  if (!nextStatus) {
    return <span className="text-xs font-bold uppercase text-neutral-400">Closed</span>;
  }

  return (
    <button
      type="button"
      className="px-3 py-1.5 rounded-lg text-xs font-bold bg-brand-600 hover:bg-brand-500 text-white"
      onClick={() => onTransition(nextStatus)}
      aria-label={`Move ${ticketId} to ${nextStatus}`}
    >
      Move to {nextStatus.replace("_", " ")}
    </button>
  );
};

export default TicketStatusStepper;
