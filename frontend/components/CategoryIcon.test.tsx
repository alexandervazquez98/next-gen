import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import CategoryIcon from "./CategoryIcon";

describe("CategoryIcon", () => {
	it("renders explicit icon keys and exposes readable labels", () => {
		render(<CategoryIcon iconKey="router" />);

		const icon = screen.getByRole("img", { name: /router technology icon/i });

		expect(icon).toBeInTheDocument();
		expect(icon).toHaveTextContent("router");
	});

	it("falls back to generic icon for unknown keys", () => {
		render(<CategoryIcon iconKey="not-a-key" />);

		const icon = screen.getByRole("img", { name: /generic technology icon/i });

		expect(icon).toBeInTheDocument();
		expect(icon).toHaveTextContent("category");
	});

	it("falls back to category-derived icon", () => {
		render(<CategoryIcon categoryName="Layer 3 switch" />);

		const icon = screen.getByRole("img", { name: /layer 3 switch technology icon/i });

		expect(icon).toBeInTheDocument();
		expect(icon).toHaveTextContent("hub");
	});
});
