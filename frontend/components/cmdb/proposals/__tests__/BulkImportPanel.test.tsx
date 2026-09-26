import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import BulkImportPanel from "../BulkImportPanel";
import * as cmdbProposals from "@/services/cmdbProposals";

vi.mock("@/services/cmdbProposals", () => ({
  bulkValidateProposals: vi.fn(),
  bulkImportProposals: vi.fn(),
}));

describe("BulkImportPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders with disabled buttons before a file is picked", () => {
    render(<BulkImportPanel />);
    const validateBtn = screen.getByTestId("bulk-import-validate");
    const submitBtn = screen.getByTestId("bulk-import-submit");
    expect(validateBtn).toBeDisabled();
    expect(submitBtn).toBeDisabled();
  });

  it("enables buttons after picking a valid CSV file", () => {
    render(<BulkImportPanel />);
    const file = new File(["id,label,category\nr1,R1,Router\n"], "test.csv", {
      type: "text/csv",
    });
    const input = screen.getByTestId("bulk-import-file");
    fireEvent.change(input, { target: { files: [file] } });

    expect(screen.getByTestId("bulk-import-validate")).toBeEnabled();
    expect(screen.getByTestId("bulk-import-submit")).toBeEnabled();
    expect(screen.getByText(/test\.csv/)).toBeTruthy();
  });

  it("shows error alert when file exceeds 5MB cap", () => {
    render(<BulkImportPanel />);
    // Mock a 6MB file
    const bigFile = new File([new ArrayBuffer(6 * 1024 * 1024)], "big.csv", {
      type: "text/csv",
    });
    const input = screen.getByTestId("bulk-import-file");
    fireEvent.change(input, { target: { files: [bigFile] } });

    expect(screen.getByTestId("bulk-import-file-too-large")).toBeTruthy();
    expect(screen.getByTestId("bulk-import-validate")).toBeDisabled();
    expect(screen.getByTestId("bulk-import-submit")).toBeDisabled();
  });

  it("displays success banner after successful dry-run validation", async () => {
    vi.mocked(cmdbProposals.bulkValidateProposals).mockResolvedValueOnce({
      dry_run: true,
      cis_count: 2,
      categories: ["Router", "Switch"],
      manifest: {},
    });

    render(<BulkImportPanel />);
    const file = new File(["dummy"], "valid.csv", { type: "text/csv" });
    fireEvent.change(screen.getByTestId("bulk-import-file"), {
      target: { files: [file] },
    });
    fireEvent.click(screen.getByTestId("bulk-import-validate"));

    await waitFor(() => {
      expect(screen.getByTestId("bulk-import-validation-ok")).toBeTruthy();
    });
    expect(screen.getByText(/2 CI\(s\) ready across 2 categories: Router, Switch/)).toBeTruthy();
  });

  it("displays per-row error list on validation failure (atomicity UI)", async () => {
    vi.mocked(cmdbProposals.bulkValidateProposals).mockResolvedValueOnce({
      reason: "bulk_validation_failed",
      errors: [
        { row: 2, errors: ["missing label", "category 'Unknown' does not exist"] },
        { row: 3, errors: ["column 'snmp_community' matches secret deny-list"] },
      ],
    });

    render(<BulkImportPanel />);
    const file = new File(["dummy"], "bad.csv", { type: "text/csv" });
    fireEvent.change(screen.getByTestId("bulk-import-file"), {
      target: { files: [file] },
    });
    fireEvent.click(screen.getByTestId("bulk-import-validate"));

    await waitFor(() => {
      expect(screen.getByTestId("bulk-import-validation-errors")).toBeTruthy();
    });
    expect(screen.getByText(/2 row\(s\) failed — fix and resubmit/)).toBeTruthy();
    expect(
      screen.getByText(/row 2: missing label; category 'Unknown' does not exist/),
    ).toBeTruthy();
    expect(
      screen.getByText(/row 3: column 'snmp_community' matches secret deny-list/),
    ).toBeTruthy();
  });

  it("calls onCreated and renders link on successful submit", async () => {
    const onCreated = vi.fn();
    vi.mocked(cmdbProposals.bulkImportProposals).mockResolvedValueOnce({
      proposal_id: "prop-bulk-456",
      status: "DRAFT",
      version: 1,
      cis_count: 50,
      manifest_mode: "bulk",
      created_at: "2026-09-18T12:00:00Z",
    });

    render(<BulkImportPanel onCreated={onCreated} />);
    const file = new File(["dummy"], "ok.csv", { type: "text/csv" });
    fireEvent.change(screen.getByTestId("bulk-import-file"), {
      target: { files: [file] },
    });
    fireEvent.click(screen.getByTestId("bulk-import-submit"));

    await waitFor(() => {
      expect(screen.getByTestId("bulk-import-submitted")).toBeTruthy();
    });
    expect(onCreated).toHaveBeenCalledWith("prop-bulk-456");
    const link = screen.getByRole("link", { name: "prop-bulk-456" });
    expect(link.getAttribute("href")).toBe("/#/proposals/cmdb?id=prop-bulk-456");
    expect(screen.getByText(/\(50 CIs\)/)).toBeTruthy();
  });
});
