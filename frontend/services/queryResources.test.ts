import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { fetchActiveEvents, fetchCategories, fetchNodeMetricHistory, fetchNodesSearch } from "./queryResources";

const { mockApiGet } = vi.hoisted(() => ({
	mockApiGet: vi.fn(),
}));

vi.mock("./api", () => ({
	api: {
		get: mockApiGet,
	},
}));

describe("fetchActiveEvents", () => {
	beforeEach(() => {
		mockApiGet.mockReset();
	});

	it("calls the console event feed so recovered events remain visible", async () => {
		mockApiGet.mockResolvedValue([]);
		const signal = new AbortController().signal;

		await fetchActiveEvents({ signal });

		expect(mockApiGet).toHaveBeenCalledWith("/events?status=CONSOLE", {
			signal,
		});
	});
});

describe("fetchCategories", () => {
	beforeEach(() => {
		mockApiGet.mockReset();
	});

	it("fetches categories with icon metadata", async () => {
		const signal = new AbortController().signal;
		const mockCategories = [
			{ name: "Router", icon_key: "router" },
			{ name: "Storage", icon_key: "storage" },
		];
		mockApiGet.mockResolvedValue(mockCategories);

		const result = await fetchCategories({ signal });

		expect(mockApiGet).toHaveBeenCalledWith("/categories", {
			signal,
		});
		expect(result).toEqual(mockCategories);
		expect(result[0].icon_key).toBe("router");
	});

	it("supports missing icon metadata from older API responses", async () => {
		const mockCategories = [{ name: "Network" }];
		mockApiGet.mockResolvedValue(mockCategories);

		const result = await fetchCategories({});

		expect(mockApiGet).toHaveBeenCalledWith("/categories", { signal: undefined });
		expect(result).toEqual(mockCategories);
	});
});

describe("fetchNodesSearch", () => {
	beforeEach(() => {
		vi.useFakeTimers();
		mockApiGet.mockReset();
	});

	afterEach(() => {
		vi.useRealTimers();
	});

	it("calls /nodes/search with q query param", async () => {
		mockApiGet.mockResolvedValue([
			{ id: "CI-001", label: "Router", status: "OK", ip: "192.168.1.1" },
		]);

		await fetchNodesSearch({ q: "router" });

		expect(mockApiGet).toHaveBeenCalledWith("/nodes/search?q=router", {
			signal: undefined,
		});
	});

	it("forwards abort signal", async () => {
		mockApiGet.mockResolvedValue([]);
		const signal = new AbortController().signal;

		await fetchNodesSearch({ q: "server", signal });

		expect(mockApiGet).toHaveBeenCalledWith("/nodes/search?q=server", {
			signal,
		});
	});

	it("returns array of nodes on success", async () => {
		const mockNodes = [
			{
				id: "CI-001",
				label: "Core Router",
				ip: "192.168.1.1",
				status: "OK",
				brand: "Cisco",
				model: "ASR-1000",
			},
			{
				id: "CI-002",
				label: "Backup Router",
				ip: "192.168.1.2",
				status: "ACTIVE",
				brand: "Juniper",
				model: "MX204",
			},
		];
		mockApiGet.mockResolvedValue(mockNodes);

		const result = await fetchNodesSearch({ q: "router" });

		expect(result).toEqual(mockNodes);
		expect(mockApiGet).toHaveBeenCalledTimes(1);
	});

	it("throws ApiError for non-2xx responses", async () => {
		mockApiGet.mockRejectedValue(
			new Error("Query must be at least 2 characters"),
		);

		await expect(fetchNodesSearch({ q: "a" })).rejects.toThrow(
			"Query must be at least 2 characters",
		);
	});
});

describe("fetchNodeMetricHistory", () => {
	beforeEach(() => {
		mockApiGet.mockReset();
	});

	it("calls single-node metric history endpoint with encoded params", async () => {
		mockApiGet.mockResolvedValue([]);

		await fetchNodeMetricHistory({
			nodeId: "CI 001",
			metricId: "cpu/load",
			hours: 24,
		});

		expect(mockApiGet).toHaveBeenCalledWith(
			"/metrics/CI%20001/cpu%2Fload/history?limit=1000&hours=24",
			{ signal: undefined },
		);
	});
});
