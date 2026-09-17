import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ProposalDiffView } from "../ProposalDiffView";

describe("ProposalDiffView", () => {
  const manifest = {
    ci: {
      id: "CI-NEW",
      label: "Core Router",
      category: "Router",
      ip: "10.20.30.1",
    },
  };

  it("lists added fields in the left column", () => {
    render(
      <ProposalDiffView
        manifest={manifest}
        liveCi={null}
        liveCategories={["Router"]}
        liveCiExists={false}
      />,
    );

    const added = screen.getByTestId("proposal-diff-added");
    expect(added).toHaveTextContent("label");
    expect(added).toHaveTextContent("Core Router");
  });

  it("lists changed fields with old → new", () => {
    const liveCi = { id: "CI-NEW", label: "Old Router", category: "Router", ip: "10.20.30.1" };
    render(
      <ProposalDiffView
        manifest={manifest}
        liveCi={liveCi}
        liveCategories={["Router"]}
        liveCiExists={true}
      />,
    );

    expect(screen.getByTestId("proposal-diff-collision")).toBeInTheDocument();
    expect(screen.getByTestId("proposal-diff-changed")).toHaveTextContent("label");
    expect(screen.getByTestId("proposal-diff-changed")).toHaveTextContent("Old Router");
    expect(screen.getByTestId("proposal-diff-changed")).toHaveTextContent("Core Router");
  });

  it("shows the collision badge when :CI id exists", () => {
    render(
      <ProposalDiffView
        manifest={manifest}
        liveCi={{ id: "CI-NEW" }}
        liveCategories={["Router"]}
        liveCiExists={true}
      />,
    );
    expect(screen.getByTestId("proposal-diff-collision")).toBeInTheDocument();
  });

  it("shows the category-drift badge when category not in live catalog", () => {
    render(
      <ProposalDiffView
        manifest={manifest}
        liveCi={null}
        liveCategories={["Server"]}
        liveCiExists={false}
      />,
    );
    expect(screen.getByTestId("proposal-diff-category-drift")).toBeInTheDocument();
  });
});
