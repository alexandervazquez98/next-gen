import { act, render, screen, waitFor, cleanup } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import MetricAnalytics from "./MetricAnalytics";
import type { GraphNode } from "../types";

const {
	mockFetchNodes,
	mockFetchNodesSearch,
	mockFetchMetricsHistory,
	mockFetchNodeMetricHistory,
} = vi.hoisted(() => ({
	mockFetchNodes: vi.fn(),
	mockFetchNodesSearch: vi.fn(),
	mockFetchMetricsHistory: vi.fn(),
	mockFetchNodeMetricHistory: vi.fn(),
}));

vi.mock("../services/queryResources", () => ({
	fetchNodes: mockFetchNodes,
	fetchNodesSearch: mockFetchNodesSearch,
	fetchMetricsHistory: mockFetchMetricsHistory,
	fetchNodeMetricHistory: mockFetchNodeMetricHistory,
}));

// Mock global fetch for initial node loading
vi.stubGlobal("fetch", vi.fn());

// Mock MetricHistoryChart
vi.mock("./MetricHistoryChart", () => ({
	default: () => <span data-testid="metric-history-chart">Mock Chart</span>,
}));

describe("MetricAnalytics", () => {
	const mockNodes: GraphNode[] = [
		{
			id: "CI-001",
			label: "Core Router",
			type: "INFRASTRUCTURE",
			status: "OK",
			metadata: {},
			ip: "192.168.1.1",
			brand: "Cisco",
			model: "ASR-1000",
			metrics: [
				{
					name: "cpu-load",
					protocol: "snmp",
					oid: "1.3.6.1",
					value: "45",
					status: "OK",
					last_updated: "2026-05-11T10:00:00Z",
				},
				{
					name: "memory-usage",
					protocol: "snmp",
					oid: "1.3.6.2",
					value: "60",
					status: "OK",
					last_updated: "2026-05-11T10:00:00Z",
				},
			],
		},
		{
			id: "CI-002",
			label: "Backup Router",
			type: "INFRASTRUCTURE",
			status: "ACTIVE",
			metadata: {},
			ip: "192.168.1.2",
			brand: "Juniper",
			model: "MX204",
			metrics: [],
		},
	];

	beforeEach(() => {
		vi.useFakeTimers();
		mockFetchNodes.mockReset();
		mockFetchNodesSearch.mockReset();
		mockFetchMetricsHistory.mockReset();
		mockFetchNodeMetricHistory.mockReset();
		// Mock localStorage for MetricAnalytics component
		Object.defineProperty(globalThis, "localStorage", {
			value: {
				getItem: vi.fn(() => "fake-token"),
				setItem: vi.fn(),
				removeItem: vi.fn(),
				clear: vi.fn(),
			},
			writable: true,
		});
		mockFetchNodes.mockResolvedValue([]);
		mockFetchMetricsHistory.mockResolvedValue({ nodes: [] });
		mockFetchNodeMetricHistory.mockResolvedValue([]);
	});

	afterEach(() => {
		vi.useRealTimers();
		cleanup();
	});

	describe("search input", () => {
		it("renders search input replacing select dropdown", () => {
			mockFetchNodesSearch.mockResolvedValue([]);
			render(<MetricAnalytics />);

			expect(screen.getByRole("searchbox")).toBeInTheDocument();
		});

		it("debounces API call by 300ms after last keystroke", async () => {
			mockFetchNodesSearch.mockResolvedValue(mockNodes);
			render(<MetricAnalytics />);

			const searchInput = screen.getByRole("searchbox");

			// Type "router" - 6 chars, simulating 50ms between keystrokes
			await act(async () => {
				searchInput.focus();
				searchInput.setAttribute("value", "r");
				searchInput.dispatchEvent(new Event("input", { bubbles: true }));
			});

			// Advance timer by 100ms
			await act(async () => {
				vi.advanceTimersByTime(100);
			});

			await act(async () => {
				searchInput.setAttribute("value", "ro");
				searchInput.dispatchEvent(new Event("input", { bubbles: true }));
			});

			await act(async () => {
				vi.advanceTimersByTime(100);
			});

			await act(async () => {
				searchInput.setAttribute("value", "rou");
				searchInput.dispatchEvent(new Event("input", { bubbles: true }));
			});

			await act(async () => {
				vi.advanceTimersByTime(100);
			});

			await act(async () => {
				searchInput.setAttribute("value", "rout");
				searchInput.dispatchEvent(new Event("input", { bubbles: true }));
			});

			await act(async () => {
				vi.advanceTimersByTime(100);
			});

			await act(async () => {
				searchInput.setAttribute("value", "route");
				searchInput.dispatchEvent(new Event("input", { bubbles: true }));
			});

			await act(async () => {
				vi.advanceTimersByTime(100);
			});

			await act(async () => {
				searchInput.setAttribute("value", "router");
				searchInput.dispatchEvent(new Event("input", { bubbles: true }));
			});

			// At this point we're 500ms from first char, 50ms from last
			// Advance to fire the debounced call
			await act(async () => {
				vi.advanceTimersByTime(300);
			});

			// Only ONE call should have been made after 300ms from last keystroke
			expect(mockFetchNodesSearch).toHaveBeenCalledTimes(1);
			expect(mockFetchNodesSearch).toHaveBeenCalledWith({
				q: "router",
				signal: expect.any(AbortSignal),
			});
		});

		it("does not fetch when term has fewer than 2 characters", async () => {
			mockFetchNodesSearch.mockResolvedValue([]);
			render(<MetricAnalytics />);

			const searchInput = screen.getByRole("searchbox");

			await act(async () => {
				searchInput.setAttribute("value", "a");
				searchInput.dispatchEvent(new Event("input", { bubbles: true }));
			});

			await act(async () => {
				vi.advanceTimersByTime(500);
			});

			expect(mockFetchNodesSearch).not.toHaveBeenCalled();
		});

		it("aborts previous request when new keystroke occurs", async () => {
			mockFetchNodesSearch
				.mockResolvedValueOnce(
					new Promise((resolve) => {
						setTimeout(() => resolve(mockNodes), 1000);
					}),
				)
				.mockResolvedValueOnce(mockNodes);

			render(<MetricAnalytics />);

			const searchInput = screen.getByRole("searchbox");

			// First keystroke
			await act(async () => {
				searchInput.setAttribute("value", "rou");
				searchInput.dispatchEvent(new Event("input", { bubbles: true }));
			});

			// Advance 200ms - not yet at 300ms debounce
			await act(async () => {
				vi.advanceTimersByTime(200);
			});

			// Second keystroke (should abort first)
			await act(async () => {
				searchInput.setAttribute("value", "router");
				searchInput.dispatchEvent(new Event("input", { bubbles: true }));
			});

			await act(async () => {
				vi.advanceTimersByTime(350);
			});

			// Only the second call should have been made
			expect(mockFetchNodesSearch).toHaveBeenCalledTimes(1);
		});
	});

	describe("multi-CI metrics", () => {
		it("fetches each selected CI with its own default metric", async () => {
			vi.useRealTimers();
			const heterogeneousNodes: GraphNode[] = [
				mockNodes[0],
				{
					id: "CI-003",
					label: "Access Switch",
					type: "INFRASTRUCTURE",
					status: "OK",
					metadata: {},
					ip: "192.168.1.3",
					brand: "Huawei",
					model: "S5735",
					metrics: [
						{
							name: "temperature-celsius",
							protocol: "snmp",
							oid: "1.3.6.3",
							value: "40",
							status: "OK",
							last_updated: "2026-05-11T10:00:00Z",
						},
					],
				},
			];
			mockFetchNodes.mockResolvedValue(heterogeneousNodes);

			render(<MetricAnalytics />);

			await waitFor(() =>
				expect(screen.getByText("Core Router")).toBeInTheDocument(),
			);

			await act(async () => {
				screen.getByText("Core Router").click();
			});
			await act(async () => {
				screen.getByText("Access Switch").click();
			});

			await waitFor(() => {
				expect(mockFetchNodeMetricHistory).toHaveBeenCalledWith(
					expect.objectContaining({ nodeId: "CI-001", metricId: "cpu-load" }),
				);
				expect(mockFetchNodeMetricHistory).toHaveBeenCalledWith(
					expect.objectContaining({
						nodeId: "CI-003",
						metricId: "temperature-celsius",
					}),
				);
			});
		});
	});

	describe("responsive layout guards", () => {
		it("renders multi-CI controls with overflow guards for long labels", async () => {
			vi.useRealTimers();
			const longNodes: GraphNode[] = [
				{
					id: "CI-LONG-001",
					label:
						"Core Router With An Extremely Long Human Readable Name That Should Not Force Horizontal Overflow 001",
					type: "INFRASTRUCTURE",
					status: "OK",
					metadata: {},
					ip: "10.10.10.1",
					brand: "VeryLongNetworkVendorName",
					model: "VeryLongModelIdentifier-AAAAAAAAAAAAAAAAAAAAAAAA",
					metrics: [
						{
							name: "primary-throughput-metric-with-a-very-long-name",
							protocol: "snmp",
							oid: "1.3.6.1.4.1.1",
							value: "45",
							status: "OK",
							last_updated: "2026-05-11T10:00:00Z",
						},
						{
							name: "secondary-latency-metric-with-a-very-long-name",
							protocol: "snmp",
							oid: "1.3.6.1.4.1.2",
							value: "60",
							status: "OK",
							last_updated: "2026-05-11T10:00:00Z",
						},
					],
				},
				{
					id: "CI-LONG-002",
					label:
						"Backup Router With Another Extremely Long Human Readable Name That Should Truncate 002",
					type: "INFRASTRUCTURE",
					status: "OK",
					metadata: {},
					ip: "10.10.10.2",
					brand: "AnotherVeryLongNetworkVendorName",
					model: "VeryLongModelIdentifier-BBBBBBBBBBBBBBBBBBBBBBBB",
					metrics: [
						{
							name: "primary-packet-loss-metric-with-a-very-long-name",
							protocol: "snmp",
							oid: "1.3.6.1.4.1.3",
							value: "12",
							status: "OK",
							last_updated: "2026-05-11T10:00:00Z",
						},
						{
							name: "secondary-cpu-pressure-metric-with-a-very-long-name",
							protocol: "snmp",
							oid: "1.3.6.1.4.1.4",
							value: "18",
							status: "OK",
							last_updated: "2026-05-11T10:00:00Z",
						},
					],
				},
			];
			mockFetchNodes.mockResolvedValue(longNodes);
			mockFetchNodeMetricHistory.mockResolvedValue([]);

			const { container } = render(<MetricAnalytics />);

			await waitFor(() =>
				expect(screen.getByText(longNodes[0].label)).toBeInTheDocument(),
			);

			await act(async () => {
				screen.getByText(longNodes[0].label).click();
			});
			await act(async () => {
				screen.getByText(longNodes[1].label).click();
			});

			await waitFor(() =>
				expect(screen.getByText("Metric per CI")).toBeInTheDocument(),
			);

			expect(container.firstElementChild).toHaveClass(
				"min-w-0",
				"max-w-full",
				"overflow-x-hidden",
				"overflow-y-auto",
			);
			expect(
				screen.getByText("Metric per CI").closest(".col-span-12"),
			).toHaveClass("min-w-0", "max-w-full", "overflow-x-hidden");

			const selectedChipLabel = screen
				.getAllByText(longNodes[0].label)
				.find(
					(element) =>
						element.tagName.toLowerCase() === "span" &&
						element.className.includes("truncate"),
				);
			expect(selectedChipLabel).toHaveClass("min-w-0", "truncate");

			await act(async () => {
				screen
					.getByRole("button", {
						name: /toggle secondary metric comparison/i,
					})
					.click();
			});

			expect(
				screen.getByText("Secondary Metrics Comparison"),
			).toBeInTheDocument();
			expect(
				screen.getByRole("button", {
					name: /toggle secondary metric comparison/i,
				}),
			).toHaveClass("shrink-0");
		});
	});

	describe("search results display", () => {
		it("shows loading state while searching", async () => {
			let resolveSearch!: (value: GraphNode[]) => void;
			mockFetchNodesSearch.mockImplementation(
				() =>
					new Promise<GraphNode[]>((resolve) => {
						resolveSearch = resolve;
					}),
			);

			render(<MetricAnalytics />);

			const searchInput = screen.getByRole("searchbox");

			await act(async () => {
				searchInput.setAttribute("value", "router");
				searchInput.dispatchEvent(new Event("input", { bubbles: true }));
			});

			await act(async () => {
				vi.advanceTimersByTime(350);
			});

			expect(screen.getByText(/loading/i)).toBeInTheDocument();

			// Resolve the search
			await act(async () => {
				resolveSearch(mockNodes);
			});
		});

		it('shows "No results found" when search returns empty array', async () => {
			mockFetchNodesSearch.mockResolvedValue([]);

			render(<MetricAnalytics />);

			const searchInput = screen.getByRole("searchbox");

			await act(async () => {
				searchInput.setAttribute("value", "nonexistent");
				searchInput.dispatchEvent(new Event("input", { bubbles: true }));
			});

			await act(async () => {
				vi.advanceTimersByTime(350);
			});

			expect(screen.getByText(/no results/i)).toBeInTheDocument();
		});

		it("displays search results in a list", async () => {
			mockFetchNodesSearch.mockResolvedValue(mockNodes);

			render(<MetricAnalytics />);

			const searchInput = screen.getByRole("searchbox");

			await act(async () => {
				searchInput.setAttribute("value", "router");
				searchInput.dispatchEvent(new Event("input", { bubbles: true }));
			});

			await act(async () => {
				vi.advanceTimersByTime(350);
			});

			expect(screen.getByText("Core Router")).toBeInTheDocument();
			expect(screen.getByText("Backup Router")).toBeInTheDocument();
		});
	});
});
