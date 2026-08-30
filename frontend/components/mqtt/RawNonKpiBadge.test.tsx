/**
 * MQTT Monitoring Frontend (Issue #385) — `RAW_MQTT_NON_KPI` badge contract.
 *
 * PR1 verifies the safety primitive from
 * `openspec/changes/feat-mqtt-385-frontend-ux/design.md` §Safety Contract
 * (1) "RAW_MQTT_NON_KPI badge always visible":
 *   - When payload supplies `classification` + `kpi_eligible`, both values
 *     are surfaced.
 *   - When payload is missing or null, the badge default-renders
 *     `RAW_MQTT_NON_KPI` and `kpi_eligible=false` rather than omit itself.
 *   - The badge exposes the canonical label as a data attribute so the
 *     MqttMonitoringPage integration test can find it without relying on
 *     styling / class selectors.
 */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import RawNonKpiBadge, { RAW_MQTT_NON_KPI } from "./RawNonKpiBadge";

describe("RawNonKpiBadge — always-visible badge contract (PR1)", () => {
  it("renders the API-supplied classification verbatim", () => {
    render(
      <RawNonKpiBadge
        classification="RAW_MQTT_NON_KPI"
        kpiEligible={false}
      />,
    );
    const badge = screen.getByTestId("raw-non-kpi-badge");
    expect(badge).toHaveAttribute("data-classification", "RAW_MQTT_NON_KPI");
    expect(badge).toHaveAttribute("data-kpi-eligible", "false");
    expect(badge).toHaveTextContent(RAW_MQTT_NON_KPI);
  });

  it("renders the kpi_eligible=false indicator by default", () => {
    render(<RawNonKpiBadge />);
    const badge = screen.getByTestId("raw-non-kpi-badge");
    expect(badge).toHaveAttribute("data-classification", RAW_MQTT_NON_KPI);
    expect(badge).toHaveAttribute("data-kpi-eligible", "false");
    expect(badge).toHaveTextContent(/kpi_eligible=false/);
  });

  it("defaults to RAW_MQTT_NON_KPI when classification is missing", () => {
    render(<RawNonKpiBadge classification={null} kpiEligible={null} />);
    const badge = screen.getByTestId("raw-non-kpi-badge");
    expect(badge).toHaveAttribute("data-classification", RAW_MQTT_NON_KPI);
    expect(badge).toHaveAttribute("data-kpi-eligible", "false");
  });

  it("defaults to RAW_MQTT_NON_KPI when classification is undefined", () => {
    render(<RawNonKpiBadge />);
    const badge = screen.getByTestId("raw-non-kpi-badge");
    expect(badge).toHaveAttribute("data-classification", RAW_MQTT_NON_KPI);
    expect(badge).toHaveAttribute("data-kpi-eligible", "false");
  });

  it("defaults to kpi_eligible=false when the field is missing", () => {
    render(<RawNonKpiBadge classification={RAW_MQTT_NON_KPI} />);
    const badge = screen.getByTestId("raw-non-kpi-badge");
    expect(badge).toHaveAttribute("data-kpi-eligible", "false");
  });

  it("defaults to kpi_eligible=false when the field is null", () => {
    render(<RawNonKpiBadge classification={RAW_MQTT_NON_KPI} kpiEligible={null} />);
    const badge = screen.getByTestId("raw-non-kpi-badge");
    expect(badge).toHaveAttribute("data-kpi-eligible", "false");
  });

  it("reflects kpiEligible=true when supplied (defensive: future-proof)", () => {
    render(<RawNonKpiBadge kpiEligible={true} />);
    const badge = screen.getByTestId("raw-non-kpi-badge");
    expect(badge).toHaveAttribute("data-kpi-eligible", "true");
  });

  it("hides the textual kpi_eligible suffix in compact mode", () => {
    render(<RawNonKpiBadge compact />);
    const badge = screen.getByTestId("raw-non-kpi-badge");
    expect(badge).not.toHaveTextContent(/kpi_eligible=false/);
    expect(badge).toHaveTextContent(RAW_MQTT_NON_KPI);
  });
});
