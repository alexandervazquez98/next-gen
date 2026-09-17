import React, { useState } from "react";
import { toast } from "sonner";
import { useApproveProposal, useRevokeProposal } from "../../../hooks/queries/useProposalsQuery";

interface ProposalActionsProps {
  proposalId: string;
  version: number;
  ciId: string | null;
  canApprove: boolean;
  isRevoked?: boolean;
  isApproved?: boolean;
}

export const ProposalActions: React.FC<ProposalActionsProps> = ({
  proposalId,
  version,
  ciId,
  canApprove,
  isRevoked,
  isApproved,
}) => {
  const [confirmApprove, setConfirmApprove] = useState(false);
  const [confirmRevoke, setConfirmRevoke] = useState(false);
  const approve = useApproveProposal();
  const revoke = useRevokeProposal();

  if (!canApprove) {
    return (
      <div data-testid="proposal-actions-no-permission" className="text-xs text-neutral-500 italic">
        You need CI_APPROVE_PROPOSAL to act on this proposal.
      </div>
    );
  }

  if (isRevoked) {
    return (
      <div className="text-xs text-red-400 italic" data-testid="proposal-actions-revoked">
        Proposal is REVOKED.
      </div>
    );
  }

  return (
    <div data-testid="proposal-actions" className="flex gap-3">
      {!isApproved && (
        <>
          <button
            type="button"
            data-testid="proposal-action-approve"
            onClick={() => setConfirmApprove(true)}
            className="px-4 py-2 rounded-lg bg-emerald-500/20 text-emerald-300 text-xs font-black uppercase tracking-widest border border-emerald-500/30"
          >
            Approve
          </button>
          {confirmApprove && (
            <div
              data-testid="proposal-action-approve-confirm"
              role="dialog"
              className="fixed inset-0 bg-black/60 flex items-center justify-center z-50"
            >
              <div className="bg-neutral-950 p-6 rounded-2xl border border-white/10 max-w-md">
                <h3 className="text-sm font-bold uppercase tracking-widest text-white mb-2">
                  Approve proposal {proposalId}?
                </h3>
                <p className="text-xs text-neutral-300 mb-4">
                  This will create :CI <code>{ciId ?? "(unknown)"}</code> via the existing node
                  write path.
                </p>
                <div className="flex gap-2 justify-end">
                  <button
                    type="button"
                    onClick={() => setConfirmApprove(false)}
                    className="px-4 py-2 text-xs border border-white/10 rounded"
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    data-testid="proposal-action-approve-confirm-yes"
                    onClick={() => {
                      setConfirmApprove(false);
                      approve.mutate(
                        { id: proposalId, version },
                        {
                          onSuccess: (data) => {
                            toast.success(`Approved — :CI ${data.resulted_ci_id} committed`);
                          },
                          onError: (err) => {
                            toast.error(`Approve failed: ${String(err)}`);
                          },
                        },
                      );
                    }}
                    className="px-4 py-2 text-xs bg-emerald-500 text-white rounded"
                  >
                    Confirm
                  </button>
                </div>
              </div>
            </div>
          )}
        </>
      )}
      <button
        type="button"
        data-testid="proposal-action-revoke"
        onClick={() => setConfirmRevoke(true)}
        className="px-4 py-2 rounded-lg bg-red-500/20 text-red-300 text-xs font-black uppercase tracking-widest border border-red-500/30"
      >
        Revoke
      </button>
      {confirmRevoke && (
        <div
          data-testid="proposal-action-revoke-confirm"
          role="dialog"
          className="fixed inset-0 bg-black/60 flex items-center justify-center z-50"
        >
          <div className="bg-neutral-950 p-6 rounded-2xl border border-white/10 max-w-md">
            <h3 className="text-sm font-bold uppercase tracking-widest text-white mb-2">
              Revoke proposal {proposalId}?
            </h3>
            <p className="text-xs text-neutral-300 mb-4">
              {isApproved
                ? "This will mark the proposal REVOKED but keep the live :CI."
                : "This will mark the proposal REVOKED. No :CI will be created."}
            </p>
            <div className="flex gap-2 justify-end">
              <button
                type="button"
                onClick={() => setConfirmRevoke(false)}
                className="px-4 py-2 text-xs border border-white/10 rounded"
              >
                Cancel
              </button>
              <button
                type="button"
                data-testid="proposal-action-revoke-confirm-yes"
                onClick={() => {
                  setConfirmRevoke(false);
                  revoke.mutate(
                    { id: proposalId, version, reason: "manual_revoke" },
                    {
                      onSuccess: () => {
                        toast.success("Proposal revoked.");
                      },
                      onError: (err) => {
                        toast.error(`Revoke failed: ${String(err)}`);
                      },
                    },
                  );
                }}
                className="px-4 py-2 text-xs bg-red-500 text-white rounded"
              >
                Confirm
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
