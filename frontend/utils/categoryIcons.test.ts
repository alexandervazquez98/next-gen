import { describe, expect, it } from "vitest";
import {
	CATEGORY_ICON_CATALOG,
	findCategoryIcons,
	getCategoryIconEntry,
	normalizeCategoryName,
	isCategoryIconKey,
	resolveCategoryIconKey,
} from "./categoryIcons";

describe("categoryIcons utility", () => {
	it("resolves known icon keys to catalog entries", () => {
		const routerEntry = getCategoryIconEntry("router");
		const serverEntry = getCategoryIconEntry("server");

		expect(routerEntry.key).toBe("router");
		expect(routerEntry.label).toBe("Router");
		expect(routerEntry.materialSymbol).toBe("router");
		expect(routerEntry.materialSymbol).not.toBe("");

		expect(serverEntry.key).toBe("server");
		expect(serverEntry.label).toBe("Server");
		expect(serverEntry.materialSymbol).not.toBe("");
	});

	it("searches catalog entries by query", () => {
		const switches = findCategoryIcons("switch");
		const results = switches.map((entry) => entry.key);

		expect(results).toEqual(expect.arrayContaining(["switch_l2", "switch_l3"]));
		expect(switches).toHaveLength(2);

	const none = findCategoryIcons("non-existent-technology");
		expect(none).toHaveLength(0);
	});

	it("falls back to generic icon for invalid icon keys", () => {
		expect(resolveCategoryIconKey({ iconKey: "bad-key" })).toBe("generic");
		expect(resolveCategoryIconKey({ iconKey: "bad-key", categoryName: "Router" })).toBe("router");
		expect(resolveCategoryIconKey({ categoryName: "Unknown Category" })).toBe("generic");
		expect(isCategoryIconKey("bad-key")).toBe(false);
	});

	it("infers initial default icon by category name", () => {
		expect(resolveCategoryIconKey({ categoryName: "Layer 2 switch" })).toBe("switch_l2");
		expect(resolveCategoryIconKey({ categoryName: "Layer 3 switch" })).toBe("switch_l3");
		expect(resolveCategoryIconKey({ categoryName: "Video Analytics" })).toBe("video_analytics");
		expect(resolveCategoryIconKey({ categoryName: "", iconKey: "camera" })).toBe("camera");
	});

	it("normalizes category names consistently", () => {
		expect(normalizeCategoryName(" Layer-2 SWITCH  ")).toBe("layer2 switch");
		expect(normalizeCategoryName("Layer   3   switch")).toBe("layer3 switch");
		expect(normalizeCategoryName("Cameras")).toBe("cameras");
		expect(CATEGORY_ICON_CATALOG).toBeInstanceOf(Array);
		expect(CATEGORY_ICON_CATALOG.length).toBeGreaterThan(0);
	});

	it("guarantees no blank symbol for unknown lookup", () => {
		const unknownEntry = getCategoryIconEntry("mystery");
		expect(unknownEntry.key).toBe("generic");
		expect(unknownEntry.materialSymbol).toBe("category");
		expect(unknownEntry.materialSymbol).not.toBe("");
	});
});
