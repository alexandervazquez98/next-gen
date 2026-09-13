import { describe, it, expect, beforeEach, vi } from "vitest";
import {
  fetchProposals,
  fetchProposal,
  fetchProposalDraftCount,
  approveProposal,
  revokeProposal,
} from "../cmdbProposals";
import { queryKeys } from "../queryKeys";

describe("cmdbProposals service", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  describe("queryKeys", () => {
    it("exposes stable cache keys for proposals", () => {
      expect(queryKeys.cmdbProposals()).toEqual(["cmdb-proposals", {}]);
      expect(queryKeys.cmdbProposals({ status: "DRAFT" })).toEqual([
        "cmdb-proposals",
        { status: "DRAFT" },
      ]);
      expect(queryKeys.cmdbProposalDetail("prop-1")).toEqual([
        "cmdb-proposals",
        "detail",
        "prop-1",
      ]);
      expect(queryKeys.cmdbProposalDraftCount()).toEqual([
        "cmdb-proposals",
        "count",
        "draft",
      ]);
    });
  });

  describe("fetchProposals", () => {
    it("passes filters as query string", async () => {
      const mockData = { rows: [], total: 0, page: 1, page_size: 50 };
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        headers: { get: () => "application/json" },
        json: () => Promise.resolve(mockData),
      }) as any;

      const result = await fetchProposals({ status: "DRAFT", page: 2, page_size: 25 });

      expect(globalThis.fetch).toHaveBeenCalledWith(
        "/api/cmdb/proposals?status=DRAFT&page=2&page_size=25",
        expect.objectContaining({ method: "GET" }),
      );
      expect(result).toEqual(mockData);
    });

    it("omits empty filters", async () => {
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        headers: { get: () => "application/json" },
        json: () => Promise.resolve({ rows: [], total: 0, page: 1, page_size: 50 }),
      }) as any;

      await fetchProposals({ status: "DRAFT", category: "" });

      expect(globalThis.fetch).toHaveBeenCalledWith(
        "/api/cmdb/proposals?status=DRAFT",
        expect.any(Object),
      );
    });
  });

  describe("fetchProposal", () => {
    it("returns the proposal row by id", async () => {
      const mockData = {
        id: "prop-1",
        status: "DRAFT",
        version: 1,
        manifest_json: "{}",
        applied_manifest_json: null,
        proposed_by: "ai-bot",
        proposed_role: "AI_OPERATOR",
        reviewed_by: null,
        reviewed_at: null,
        created_at: "2026-09-13T00:00:00Z",
        updated_at: "2026-09-13T00:00:00Z",
        resulted_ci_id: null,
        revoke_reason: null,
        proposed_category: "Router",
        ci_id: "CI-NEW",
      };
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        headers: { get: () => "application/json" },
        json: () => Promise.resolve(mockData),
      }) as any;

      const result = await fetchProposal("prop-1");
      expect(result.id).toBe("prop-1");
      expect(globalThis.fetch).toHaveBeenCalledWith(
        "/api/cmdb/proposals/prop-1",
        expect.objectContaining({ method: "GET" }),
      );
    });
  });

  describe("fetchProposalDraftCount", () => {
    it("returns the badge count", async () => {
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        headers: { get: () => "application/json" },
        json: () => Promise.resolve({ count: 3 }),
      }) as any;

      const result = await fetchProposalDraftCount();
      expect(result).toEqual({ count: 3 });
      expect(globalThis.fetch).toHaveBeenCalledWith(
        "/api/cmdb/proposals/count?status=DRAFT",
        expect.objectContaining({ method: "GET" }),
      );
    });
  });

  describe("approveProposal", () => {
    it("returns resulted_ci_id", async () => {
      const mockData = {
        proposal_id: "prop-1",
        status: "APPROVED",
        version: 2,
        resulted_ci_id: "CI-NEW",
      };
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        headers: { get: () => "application/json" },
        json: () => Promise.resolve(mockData),
      }) as any;

      const result = await approveProposal("prop-1", { version: 1 });
      expect(result.status).toBe("APPROVED");
      expect(result.resulted_ci_id).toBe("CI-NEW");
      expect(globalThis.fetch).toHaveBeenCalledWith(
        "/api/cmdb/proposals/prop-1/approve",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ version: 1 }),
        }),
      );
    });
  });

  describe("revokeProposal", () => {
    it("returns status REVOKED", async () => {
      const mockData = {
        proposal_id: "prop-1",
        status: "REVOKED",
        version: 2,
      };
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        headers: { get: () => "application/json" },
        json: () => Promise.resolve(mockData),
      }) as any;

      const result = await revokeProposal("prop-1", { version: 1, reason: "stale" });
      expect(result.status).toBe("REVOKED");
      expect(globalThis.fetch).toHaveBeenCalledWith(
        "/api/cmdb/proposals/prop-1/revoke",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ version: 1, reason: "stale" }),
        }),
      );
    });
  });
});