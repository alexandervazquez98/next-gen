/* eslint-disable @typescript-eslint/no-explicit-any -- GraphCMDB still carries legacy D3 and metadata payloads that are outside this UX polish scope. */
import {
	type Dispatch,
	type RefObject,
	type SetStateAction,
	useEffect,
	useMemo,
	useRef,
	useState,
} from "react";
import { createPortal } from "react-dom";
import * as d3 from "d3";
import type { GraphLink, GraphNode } from "../types";
import { STATUS_COLORS } from "../utils/status";
import { useGraphTopologyQuery } from "../hooks/queries/useGraphTopologyQuery";
import { useCategoriesQuery } from "../hooks/queries/useCategoriesQuery";
import { useOwnersQuery } from "../hooks/queries/useOwnersQuery";
import {
	GRAPH_NODE_COLLISION_RADIUS,
	clampClusterCenterToBounds,
	estimateClusterRadius,
	getBoundedClusterDelta,
	getClusterInnerRadius,
	getClusterNodeTarget,
	isValidGeoCoordinate,
	projectGeoPointsToCanvas,
	resolveClusterOverlaps,
	summarizeClusterGeoQuality,
} from "./graphLayout";

interface GraphCMDBProps {
	// eslint-disable-next-line no-unused-vars -- callback prop names the clicked graph node for API clarity.
	onNodeClick(node: GraphNode): void;
}

const AnimatedLinksLayer = ({
	svgRef,
	links,
}: {
	svgRef: RefObject<SVGSVGElement | null>;
	links: GraphLink[];
}) => {
	const portalSvgRef = useRef<SVGSVGElement>(null);

	useEffect(() => {
		const portalRoot = document.getElementById("d3-portal-root");
		if (!portalRoot || !portalSvgRef.current || !svgRef.current) {
			return;
		}

		const rect = svgRef.current.getBoundingClientRect();
		const portalSvg = d3
			.select(portalSvgRef.current)
			.attr("width", rect.width)
			.attr("height", rect.height)
			.style("position", "absolute")
			.style("top", `${rect.top + window.scrollY}px`)
			.style("left", `${rect.left + window.scrollX}px`)
			.style("pointer-events", "none")
			.style("overflow", "visible");

		const pulseGroup = portalSvg.append("g").attr("class", "d3-pulse-layer");
		pulseGroup
			.selectAll("circle")
			.data(
				links.filter((link: any) => link.relationship === "CONNECTS_TO"),
				(link: any) => link.id,
			)
			.join(
				(enter) =>
					enter
						.append("circle")
						.attr("r", 5)
						.attr("fill", "#10b981")
						.attr("opacity", 0.8),
				(update) => update,
				(exit) => exit.remove(),
			);

		return () => {
			portalSvg.selectAll("*").remove();
		};
	}, [links, svgRef]);

	const portalRoot = document.getElementById("d3-portal-root");
	if (!portalRoot) {
		return null;
	}

	return createPortal(
		<svg
			ref={portalSvgRef}
			style={{ position: "absolute", pointerEvents: "none" }}
		/>,
		portalRoot,
	);
};

const GraphCMDB = ({ onNodeClick }: GraphCMDBProps) => {
	const [filterLayers, setFilterLayers] = useState<string[]>([]);
	const [filterLocations, setFilterLocations] = useState<string[]>([]);
	const [filterOwners, setFilterOwners] = useState<string[]>([]);
	const [groupByLocation, setGroupByLocation] = useState<boolean>(true);
	const [expandedFilters, setExpandedFilters] = useState({
		technology: true,
		location: true,
		owner: true,
	});
	const [searchTechnology, setSearchTechnology] = useState<string>("");
	const [searchLocation, setSearchLocation] = useState<string>("");
	const [searchOwner, setSearchOwner] = useState<string>("");
	const [graphSearch, setGraphSearch] = useState<string>("");
	const [selectedCluster, setSelectedCluster] = useState<string | null>(null);

	const svgRef = useRef<SVGSVGElement>(null);
	const zoomTransformRef = useRef<d3.ZoomTransform>(d3.zoomIdentity);
	const nodeStateRef = useRef<
		Map<string, { x: number; y: number; vx: number; vy: number }>
	>(new Map());
	const clusterOffsetRef = useRef<Map<string, { dx: number; dy: number }>>(
		new Map(),
	);
	const layoutSignatureRef = useRef<string>("");

	const { data, isLoading } = useGraphTopologyQuery({
		layer: filterLayers,
		location: filterLocations,
		owner: filterOwners,
	});

	const { data: fullData } = useGraphTopologyQuery({});
	const { data: categories } = useCategoriesQuery();
	const { data: owners } = useOwnersQuery();

	const nodes = useMemo(() => data?.nodes ?? [], [data?.nodes]);
	const links = useMemo(() => data?.links ?? [], [data?.links]);

	const allLocations = useMemo(
		() =>
			Array.from(
				new Set(
					(fullData?.nodes ?? [])
						.map((n) => n.location_name)
						.filter((loc): loc is string => Boolean(loc)),
				),
			).sort(),
		[fullData?.nodes],
	);
	const filteredTechnologies = useMemo(
		() =>
			(categories ?? []).filter((category) =>
				category.name.toLowerCase().includes(searchTechnology.toLowerCase()),
			),
		[categories, searchTechnology],
	);
	const filteredLocations = useMemo(
		() =>
			allLocations.filter((loc) =>
				loc.toLowerCase().includes(searchLocation.toLowerCase()),
			),
		[allLocations, searchLocation],
	);
	const filteredOwners = useMemo(
		() =>
			(owners ?? []).filter((owner) =>
				owner.name.toLowerCase().includes(searchOwner.toLowerCase()),
			),
		[owners, searchOwner],
	);
	const selectedFilterCount =
		filterLayers.length + filterLocations.length + filterOwners.length;
	const setSelection = (
		values: string[],
		setter: Dispatch<SetStateAction<string[]>>,
	) => {
		setter(values);
	};
	const toggleSelection = (
		value: string,
		setter: Dispatch<SetStateAction<string[]>>,
	) => {
		setter((current) =>
			current.includes(value)
				? current.filter((item) => item !== value)
				: [...current, value],
		);
	};
	const toggleFilterSection = (section: keyof typeof expandedFilters) => {
		setExpandedFilters((current) => ({
			...current,
			[section]: !current[section],
		}));
	};
	const renderFilterSummary = (values: string[], emptyLabel: string) => {
		if (values.length === 0) {
			return emptyLabel;
		}

		return values.length <= 2
			? values.join(", ")
			: `${values.slice(0, 2).join(", ")} +${values.length - 2}`;
	};

	useEffect(() => {
		if (!svgRef.current) return;

		const viewportWidth = svgRef.current.clientWidth || 1200;
		const viewportHeight = svgRef.current.clientHeight || 800;
		const clusterCount = Math.max(
			1,
			new Set(nodes.map((node) => node.location_name || node.owner || node.id))
				.size,
		);
		const virtualScale = Math.sqrt(clusterCount);
		const width = Math.min(
			12000,
			Math.max(viewportWidth, 3200, virtualScale * 760),
		);
		const height = Math.min(
			8000,
			Math.max(viewportHeight, 2200, virtualScale * 520),
		);
		const svg = d3.select(svgRef.current);

		// PERSIST ZOOM: prefer the ref-backed transform because the SVG DOM
		// is fully rebuilt on data refreshes and DOM-derived state can be stale.
		const currentTransform =
			zoomTransformRef.current === d3.zoomIdentity &&
			(width > viewportWidth || height > viewportHeight)
				? d3.zoomIdentity.translate(
						(viewportWidth - width) / 2,
						(viewportHeight - height) / 2,
					)
				: zoomTransformRef.current || d3.zoomTransform(svgRef.current);
		svg.selectAll("*").remove();

		const container = svg.append("g").attr("class", "main-container");

		const zoomBehavior = d3
			.zoom<SVGSVGElement, unknown>()
			.scaleExtent([0.01, 12])
			.on("zoom", (event) => {
				zoomTransformRef.current = event.transform;
				container.attr("transform", event.transform);
			});

		svg.call(zoomBehavior);

		// RESTORE ZOOM: Re-apply the transform
		svg.call(zoomBehavior.transform, currentTransform);

		const getClusterName = (node: GraphNode) => {
			const raw =
				(node as any).cluster_name ||
				node.location_name ||
				node.owner ||
				"Unassigned";
			return String(raw);
		};

		const clusterEntries = Array.from(
			d3.group(nodes, getClusterName).entries(),
		).sort(([a], [b]) => a.localeCompare(b));

		const clusterCenters: Record<
			string,
			{ x: number; y: number; radius: number; count: number; hasGeo: boolean }
		> = {};
		const clusterGeoQuality = new Map<
			string,
			ReturnType<typeof summarizeClusterGeoQuality>
		>();
		const clusterBounds = { width, height, padding: 24 };
		if (groupByLocation && clusterEntries.length > 0) {
			const layouts = clusterEntries.map(([clusterName, group], index) => {
				const quality = summarizeClusterGeoQuality(group);
				clusterGeoQuality.set(clusterName, quality);
				return {
					clusterName,
					group,
					index,
					radius: estimateClusterRadius(group.length),
					geo: quality.medianCoordinate
						? {
								lat: quality.medianCoordinate.lat,
								lon: quality.medianCoordinate.long,
							}
						: null,
				};
			});
			const geoLayouts = layouts.filter((layout) => layout.geo);
			const fallbackLayouts = layouts.filter((layout) => !layout.geo);
			const fallbackLaneWidth =
				geoLayouts.length > 0 && fallbackLayouts.length > 0
					? Math.min(width * 0.4, Math.max(320, width * 0.32))
					: 0;
			const geoBase = projectGeoPointsToCanvas(
				geoLayouts.map((layout) => ({
					id: layout.clusterName,
					lat: layout.geo?.lat ?? 0,
					long: layout.geo?.lon ?? 0,
				})),
				{ width, height, reservedRightWidth: fallbackLaneWidth },
			);
			const sameCoordinateGroups = d3.group(
				geoLayouts,
				(layout) =>
					`${layout.geo?.lat.toFixed(4)},${layout.geo?.lon.toFixed(4)}`,
			);
			sameCoordinateGroups.forEach((sameGeoLayouts) => {
				sameGeoLayouts.forEach((layout, index) => {
					const base = geoBase.get(layout.clusterName) || {
						x: width / 2,
						y: height / 2,
					};
					const spreadRadius =
						sameGeoLayouts.length > 1 ? Math.max(110, layout.radius + 44) : 0;
					const angle =
						(index / sameGeoLayouts.length) * Math.PI * 2 - Math.PI / 2;
					const offset = clusterOffsetRef.current.get(layout.clusterName) || {
						dx: 0,
						dy: 0,
					};
					clusterCenters[layout.clusterName] = {
						x: base.x + Math.cos(angle) * spreadRadius + offset.dx,
						y: base.y + Math.sin(angle) * spreadRadius + offset.dy,
						radius: layout.radius,
						count: layout.group.length,
						hasGeo: true,
					};
				});
			});
			if (fallbackLayouts.length > 0) {
				const cols = Math.max(
					1,
					Math.ceil(
						Math.sqrt(
							fallbackLayouts.length * (geoLayouts.length > 0 ? 0.65 : 1),
						),
					),
				);
				const rows = Math.ceil(fallbackLayouts.length / cols);
				const laneMinX = geoLayouts.length > 0 ? width - fallbackLaneWidth : 0;
				const laneWidth = width - laneMinX;
				const cellWidth = laneWidth / Math.max(cols, 1);
				const cellHeight = height / Math.max(rows, 1);
				fallbackLayouts.forEach((layout, i) => {
					const col = i % cols;
					const row = Math.floor(i / cols);
					const offset = clusterOffsetRef.current.get(layout.clusterName) || {
						dx: 0,
						dy: 0,
					};
					clusterCenters[layout.clusterName] = {
						x: laneMinX + cellWidth * (col + 0.5) + offset.dx,
						y: cellHeight * (row + 0.5) + offset.dy,
						radius: layout.radius,
						count: layout.group.length,
						hasGeo: false,
					};
				});
			}
		}

		if (groupByLocation) {
			const resolvedClusterCenters = resolveClusterOverlaps(
				clusterCenters,
				clusterBounds,
				{ padding: 20, iterations: 10 },
			);
			Object.entries(resolvedClusterCenters).forEach(([name, center]) => {
				const bounded = clampClusterCenterToBounds(center, clusterBounds);
				const correction = {
					dx: bounded.x - center.x,
					dy: bounded.y - center.y,
				};
				clusterCenters[name] = bounded;
				if (correction.dx !== 0 || correction.dy !== 0) {
					const previousOffset = clusterOffsetRef.current.get(name) || {
						dx: 0,
						dy: 0,
					};
					clusterOffsetRef.current.set(name, {
						dx: previousOffset.dx + correction.dx,
						dy: previousOffset.dy + correction.dy,
					});
				}
			});
		}

		if (
			selectedCluster &&
			groupByLocation &&
			!clusterCenters[selectedCluster]
		) {
			setSelectedCluster(null);
		}

		const nodeClusterIndex = new Map<
			string,
			{ index: number; total: number; clusterName: string }
		>();
		clusterEntries.forEach(([clusterName, group]) => {
			group
				.slice()
				.sort((a, b) => a.id.localeCompare(b.id, undefined, { numeric: true }))
				.forEach((node, index) => {
					nodeClusterIndex.set(node.id, {
						index,
						total: group.length,
						clusterName,
					});
				});
		});

		const nodeGeoTargets = projectGeoPointsToCanvas(
			nodes
				.filter((node) =>
					isValidGeoCoordinate(node.location?.lat, node.location?.long),
				)
				.map((node) => ({
					id: node.id,
					lat: node.location?.lat ?? 0,
					long: node.location?.long ?? 0,
				})),
			{ width, height },
		);

		const clampPointToCluster = (clusterName: string, x: number, y: number) => {
			if (!groupByLocation) return { x, y };
			const center = clusterCenters[clusterName];
			if (!center) return { x, y };
			const maxRadius = getClusterInnerRadius(center.radius);
			const dx = x - center.x;
			const dy = y - center.y;
			const distance = Math.hypot(dx, dy);
			if (distance <= maxRadius) return { x, y };
			if (distance === 0) return { x: center.x, y: center.y };
			const scale = maxRadius / distance;
			return { x: center.x + dx * scale, y: center.y + dy * scale };
		};

		const getClusterTarget = (node: GraphNode) => {
			const info = nodeClusterIndex.get(node.id);
			if (!groupByLocation || !info) {
				return nodeGeoTargets.get(node.id) || { x: width / 2, y: height / 2 };
			}

			const center = clusterCenters[info.clusterName] || {
				x: width / 2,
				y: height / 2,
				radius: 90,
			};
			return getClusterNodeTarget(center, info.index, info.total);
		};

		const defs = container.append("defs");
		Object.values(STATUS_COLORS).forEach((color) => {
			const idColor = color.replace("#", "");
			defs
				.append("marker")
				.attr("id", `arrow-${idColor}`)
				.attr("viewBox", "0 -5 10 10")
				.attr("refX", 28)
				.attr("refY", 0)
				.attr("markerWidth", 6)
				.attr("markerHeight", 6)
				.attr("orient", "auto")
				.append("path")
				.attr("d", "M0,-5L10,0L0,5")
				.attr("fill", color);
		});

		const nodeById = new Map(nodes.map((node) => [node.id, node]));
		const getLinkEndpointId = (endpoint: string | GraphNode) =>
			typeof endpoint === "object" ? (endpoint as any).id : endpoint;
		const validLinks = links
			.filter((link) => {
				const sourceId = getLinkEndpointId(link.source as any);
				const targetId = getLinkEndpointId(link.target as any);
				return nodeById.has(sourceId) && nodeById.has(targetId);
			})
			.map((link) => Object.create(link));

		const linkCountByNodeId = new Map<string, number>();
		validLinks.forEach((link: any) => {
			const sourceId = getLinkEndpointId(link.source);
			const targetId = getLinkEndpointId(link.target);
			linkCountByNodeId.set(
				sourceId,
				(linkCountByNodeId.get(sourceId) || 0) + 1,
			);
			linkCountByNodeId.set(
				targetId,
				(linkCountByNodeId.get(targetId) || 0) + 1,
			);
		});
		const isHighConnectivityNode = (nodeId: string) =>
			(linkCountByNodeId.get(nodeId) || 0) > 4;

		const clusterMode = groupByLocation && clusterEntries.length > 1;
		const isNoisyDetailedLink = (link: any) => {
			if (!clusterMode || !selectedCluster) return false;
			const sourceId = getLinkEndpointId(link.source);
			const targetId = getLinkEndpointId(link.target);
			return (
				isHighConnectivityNode(sourceId) || isHighConnectivityNode(targetId)
			);
		};
		const getDefaultDetailedLinkOpacity = (link: any, fallback = 0.6) =>
			isNoisyDetailedLink(link) ? 0 : fallback;
		const detailedLinks = clusterMode
			? selectedCluster
				? validLinks.filter((link: any) => {
						const sourceNode = nodeById.get(getLinkEndpointId(link.source));
						const targetNode = nodeById.get(getLinkEndpointId(link.target));
						return (
							(sourceNode && getClusterName(sourceNode) === selectedCluster) ||
							(targetNode && getClusterName(targetNode) === selectedCluster)
						);
					})
				: []
			: validLinks;

		const clusterLinkMap = new Map<
			string,
			{
				source: string;
				target: string;
				count: number;
				relationships: Set<string>;
			}
		>();
		if (clusterMode) {
			validLinks.forEach((link: any) => {
				const sourceNode = nodeById.get(getLinkEndpointId(link.source));
				const targetNode = nodeById.get(getLinkEndpointId(link.target));
				if (!sourceNode || !targetNode) return;
				const sourceCluster = getClusterName(sourceNode);
				const targetCluster = getClusterName(targetNode);
				if (sourceCluster === targetCluster) return;
				const key = `${sourceCluster}→${targetCluster}`;
				const current = clusterLinkMap.get(key) || {
					source: sourceCluster,
					target: targetCluster,
					count: 0,
					relationships: new Set<string>(),
				};
				current.count += 1;
				current.relationships.add(link.relationship);
				clusterLinkMap.set(key, current);
			});
		}
		const clusterLinks = Array.from(clusterLinkMap.values()).map((link) => ({
			...link,
			isBidirectional: clusterLinkMap.has(`${link.target}→${link.source}`),
		}));
		const visibleClusterLinks = selectedCluster
			? clusterLinks.filter(
					(link) =>
						link.source === selectedCluster || link.target === selectedCluster,
				)
			: clusterLinks;

		const curvedPath = (source: any, target: any, bend = 0.18) => {
			const sx = source.x ?? source.targetX ?? 0;
			const sy = source.y ?? source.targetY ?? 0;
			const tx = target.x ?? target.targetX ?? 0;
			const ty = target.y ?? target.targetY ?? 0;
			const dx = tx - sx;
			const dy = ty - sy;
			const mx = (sx + tx) / 2;
			const my = (sy + ty) / 2;
			const cx = mx - dy * bend;
			const cy = my + dx * bend;
			return `M${sx},${sy} Q${cx},${cy} ${tx},${ty}`;
		};

		const layoutSignature = `${groupByLocation}:${width}x${height}:${clusterEntries.map(([name, group]) => `${name}:${group.length}`).join("|")}:${Object.entries(
			clusterCenters,
		)
			.map(
				([name, center]) =>
					`${name}:${Math.round(center.x)}:${Math.round(center.y)}:${Math.round(center.radius)}`,
			)
			.join("|")}`;
		if (layoutSignatureRef.current !== layoutSignature) {
			nodeStateRef.current.clear();
			layoutSignatureRef.current = layoutSignature;
		}
		const cachedNodesExist = nodes.some((n) => nodeStateRef.current.has(n.id));

		const validNodes = nodes.map((node) => {
			const n = Object.create(node);
			const cached = nodeStateRef.current.get(node.id);
			const target = getClusterTarget(node);
			n.clusterName = getClusterName(node);
			const quality = clusterGeoQuality.get(n.clusterName);
			n.isGeoOutlier = quality?.outlierNodeIds.has(node.id) ?? false;
			n.targetX = target.x;
			n.targetY = target.y;

			if (cached) {
				n.x = cached.x;
				n.y = cached.y;
				n.vx = cached.vx;
				n.vy = cached.vy;
			} else {
				n.x = target.x;
				n.y = target.y;
			}
			const contained = clampPointToCluster(n.clusterName, n.x, n.y);
			n.x = contained.x;
			n.y = contained.y;
			return n;
		});
		const validNodeById = new Map(
			validNodes.map((node: any) => [node.id, node]),
		);
		const normalizedGraphSearch = graphSearch.trim().toLowerCase();
		const searchableText = (value: unknown): string => {
			if (value === null || value === undefined) return "";
			if (
				typeof value === "string" ||
				typeof value === "number" ||
				typeof value === "boolean"
			) {
				return String(value);
			}
			if (Array.isArray(value)) return value.map(searchableText).join(" ");
			if (typeof value === "object") {
				return Object.entries(value as Record<string, unknown>)
					.map(([key, entryValue]) => `${key} ${searchableText(entryValue)}`)
					.join(" ");
			}
			return "";
		};
		const nodeMatchesSearch = (node: any) => {
			if (!normalizedGraphSearch) return false;
			const apiNode = nodeById.get(node.id) || node;
			const searchPayload = {
				...apiNode,
				metadata: (apiNode as any).metadata,
				clusterName: node.clusterName,
				cluster_name: (apiNode as any).cluster_name,
				location_name: (apiNode as any).location_name,
				owner: (apiNode as any).owner,
				ip: (apiNode as any).ip,
				label: (apiNode as any).label,
				type: (apiNode as any).type,
				status: (apiNode as any).status,
			};
			return searchableText(searchPayload)
				.toLowerCase()
				.includes(normalizedGraphSearch);
		};
		const matchingNodeIds = new Set(
			validNodes
				.filter((node: any) => nodeMatchesSearch(node))
				.map((node: any) => node.id),
		);
		const matchingClusterNames = new Set<string>();
		if (normalizedGraphSearch) {
			clusterEntries.forEach(([clusterName, group]) => {
				const clusterText =
					`${clusterName} ${searchableText(clusterCenters[clusterName])}`.toLowerCase();
				if (
					clusterText.includes(normalizedGraphSearch) ||
					group.some((node) => matchingNodeIds.has(node.id))
				) {
					matchingClusterNames.add(clusterName);
				}
			});
		}
		const hasSearchMatches =
			normalizedGraphSearch.length > 0 && matchingNodeIds.size > 0;
		const getRenderedEndpoint = (endpoint: string | GraphNode) =>
			typeof endpoint === "object"
				? endpoint
				: validNodeById.get(endpoint) || nodeById.get(endpoint);
		const clusterQualityTooltip = (name: string) => {
			const center = clusterCenters[name];
			const quality = clusterGeoQuality.get(name);
			if (!center || !quality) return `${name}: coordinate quality unavailable`;
			const notes = [
				`${name}: ${quality.validCoordinateCount}/${center.count} CIs with valid coordinates`,
			];
			if (!center.hasGeo) {
				notes.push("Fallback lane: no valid coordinates in this cluster");
			}
			if (quality.missingCoordinateCount > 0) {
				notes.push(`${quality.missingCoordinateCount} CIs without coordinates`);
			}
			if (quality.outlierNodeIds.size > 0) {
				notes.push(`${quality.outlierNodeIds.size} possible geo outlier CIs`);
			}
			return notes.join(" • ");
		};

		const clusterSelection = groupByLocation
			? container
					.append("g")
					.attr("class", "cluster-layer")
					.selectAll("g")
					.data(Object.entries(clusterCenters))
					.join("g")
					.attr("class", "cursor-pointer")
					.attr(
						"transform",
						([, center]) => `translate(${center.x},${center.y})`,
					)
					.on("click", (event, [name]) => {
						event.stopPropagation();
						setSelectedCluster((current) => (current === name ? null : name));
					})
			: null;

		clusterSelection
			?.append("title")
			.text(([name]) => clusterQualityTooltip(name));

		clusterSelection
			?.append("circle")
			.attr("r", ([, center]) => center.radius)
			.attr("fill", ([name]) =>
				matchingClusterNames.has(name)
					? "#3a2f08"
					: selectedCluster === name
						? "#1e3a5f"
						: "#172033",
			)
			.attr("fill-opacity", ([name]) =>
				matchingClusterNames.has(name)
					? 0.46
					: selectedCluster === name
						? 0.38
						: 0.24,
			)
			.attr("stroke", ([name]) =>
				matchingClusterNames.has(name)
					? "#facc15"
					: selectedCluster === name
						? "#60a5fa"
						: "#345bf2",
			)
			.attr("stroke-opacity", ([name]) =>
				matchingClusterNames.has(name)
					? 1
					: hasSearchMatches
						? 0.12
						: selectedCluster === name
							? 0.8
							: 0.35,
			)
			.attr("stroke-width", ([name]) =>
				matchingClusterNames.has(name)
					? 4
					: selectedCluster === name
						? 2.5
						: 1.5,
			)
			.attr("filter", ([name]) =>
				matchingClusterNames.has(name) ? "drop-shadow(0 0 14px #facc15)" : null,
			)
			.attr("stroke-dasharray", "6,6");

		clusterSelection
			?.append("text")
			.attr("y", ([, center]) => -center.radius - 10)
			.attr("text-anchor", "middle")
			.attr("fill", "#d4d4d4")
			.attr("font-size", "11px")
			.attr("font-weight", 800)
			.attr("letter-spacing", "0.05em")
			.text(([name, center]) => `${name} (${center.count})`);

		const clusterBadgeSelection = clusterSelection
			?.append("g")
			.attr("class", "geo-quality-badges pointer-events-none")
			.attr("transform", ([, center]) => `translate(0,${center.radius - 20})`);

		clusterBadgeSelection
			?.append("text")
			.attr("text-anchor", "middle")
			.attr("fill", ([name]) =>
				clusterCenters[name]?.hasGeo ? "#fbbf24" : "#fb7185",
			)
			.attr("font-size", "10px")
			.attr("font-weight", 800)
			.attr("paint-order", "stroke")
			.attr("stroke", "#0f172a")
			.attr("stroke-width", 3)
			.text(([name]) => {
				const center = clusterCenters[name];
				const quality = clusterGeoQuality.get(name);
				if (!center || !quality) return "";
				const badges: string[] = [];
				if (!center.hasGeo) badges.push("sin coords");
				else if (quality.missingCoordinateCount > 0) {
					badges.push(`${quality.missingCoordinateCount} sin coords`);
				}
				if (quality.outlierNodeIds.size > 0) {
					badges.push(`${quality.outlierNodeIds.size} outlier`);
				}
				return badges.join(" • ");
			});

		const clusterLinkSelection = container
			.append("g")
			.attr("class", "cluster-links")
			.selectAll("g")
			.data(visibleClusterLinks)
			.join("g")
			.attr("opacity", (link) => {
				if (hasSearchMatches) {
					return matchingClusterNames.has(link.source) ||
						matchingClusterNames.has(link.target)
						? 0.78
						: 0.08;
				}
				if (selectedCluster) return link.isBidirectional ? 0.95 : 0.82;
				return link.count > 4 ? 0.22 : 0.42;
			});

		clusterLinkSelection
			.append("path")
			.attr("class", "cluster-link-base")
			.attr("d", (link) => {
				const source = clusterCenters[link.source];
				const target = clusterCenters[link.target];
				return source && target ? curvedPath(source, target, 0.12) : "";
			})
			.attr("fill", "none")
			.attr("stroke", (link) => (link.isBidirectional ? "#34d399" : "#10b981"))
			.attr("stroke-width", (link) => Math.min(5, 1.5 + Math.sqrt(link.count)))
			.attr("stroke-linecap", "round")
			.attr("stroke-dasharray", (link) =>
				link.isBidirectional ? "6,10" : link.count > 4 ? "2,10" : "none",
			)
			.attr("marker-end", `url(#arrow-${STATUS_COLORS.OK.replace("#", "")})`)
			.style("pointer-events", "none");

		const standbyClusterLink = clusterLinkSelection
			.append("path")
			.attr("class", "cluster-link-standby-flow")
			.attr("d", (link) => {
				const source = clusterCenters[link.source];
				const target = clusterCenters[link.target];
				return source && target ? curvedPath(source, target, 0.12) : "";
			})
			.attr("fill", "none")
			.attr("stroke", "#6ee7b7")
			.attr("stroke-width", 1.6)
			.attr("stroke-linecap", "round")
			.attr("stroke-dasharray", "1,22")
			.attr("opacity", selectedCluster ? 0.55 : 0.38)
			.style("pointer-events", "none");

		standbyClusterLink
			.append("animate")
			.attr("attributeName", "stroke-dashoffset")
			.attr("from", "28")
			.attr("to", "0")
			.attr("dur", "1.8s")
			.attr("repeatCount", "indefinite");

		const bilateralClusterLink = clusterLinkSelection
			.filter((link) => link.isBidirectional)
			.append("path")
			.attr("class", "cluster-link-bilateral-flow")
			.attr("d", (link) => {
				const source = clusterCenters[link.source];
				const target = clusterCenters[link.target];
				return source && target ? curvedPath(source, target, 0.12) : "";
			})
			.attr("fill", "none")
			.attr("stroke", "#a7f3d0")
			.attr("stroke-width", 2)
			.attr("stroke-linecap", "round")
			.attr("stroke-dasharray", "1,18")
			.attr("opacity", selectedCluster ? 0.95 : 0.55)
			.attr("marker-end", `url(#arrow-${STATUS_COLORS.OK.replace("#", "")})`)
			.style("pointer-events", "none");

		bilateralClusterLink
			.append("animate")
			.attr("attributeName", "stroke-dashoffset")
			.attr("from", "24")
			.attr("to", "0")
			.attr("dur", "1.1s")
			.attr("repeatCount", "indefinite");

		const simulation = d3
			.forceSimulation<GraphNode>(validNodes)
			.force(
				"link",
				clusterMode
					? null
					: d3
							.forceLink<GraphNode, GraphLink>(validLinks)
							.id((node) => node.id)
							.distance(90)
							.strength(0.2),
			)
			.force(
				"charge",
				d3
					.forceManyBody()
					.strength(clusterMode ? -8 : groupByLocation ? -140 : -420),
			)
			.force(
				"center",
				d3.forceCenter(width / 2, height / 2).strength(clusterMode ? 0 : 0.02),
			)
			.force(
				"collision",
				d3.forceCollide().radius(GRAPH_NODE_COLLISION_RADIUS).iterations(2),
			)
			.force(
				"x",
				d3
					.forceX()
					.x((d: any) => d.targetX ?? width / 2)
					.strength(clusterMode ? 0.9 : groupByLocation ? 0.58 : 0.22),
			)
			.force(
				"y",
				d3
					.forceY()
					.y((d: any) => d.targetY ?? height / 2)
					.strength(clusterMode ? 0.9 : groupByLocation ? 0.58 : 0.22),
			)
			.alpha(cachedNodesExist ? 0.18 : 1.0);

		const linkSelection = container
			.append("g")
			.selectAll("path")
			.data(detailedLinks)
			.join("path")
			.attr("fill", "none")
			.attr("stroke-opacity", 0.6)
			.attr("stroke-width", 2)
			.attr("stroke", (link: any) => {
				const targetNode = getRenderedEndpoint(link.target) as
					| GraphNode
					| undefined;
				const targetStatus = String(targetNode?.status || "UNKNOWN");
				if (targetStatus === "CRITICAL") return STATUS_COLORS.CRITICAL;
				if (targetStatus === "WARNING") return STATUS_COLORS.WARNING;
				return targetStatus === "ACTIVE" || targetStatus === "OK"
					? STATUS_COLORS.OK
					: STATUS_COLORS.UNKNOWN;
			})
			.attr("marker-end", (link: any) => {
				const targetNode = getRenderedEndpoint(link.target) as
					| GraphNode
					| undefined;
				const targetStatus = String(targetNode?.status || "UNKNOWN");
				let color = STATUS_COLORS.UNKNOWN;
				if (targetStatus === "CRITICAL") color = STATUS_COLORS.CRITICAL;
				else if (targetStatus === "WARNING") color = STATUS_COLORS.WARNING;
				else if (targetStatus === "ACTIVE" || targetStatus === "OK")
					color = STATUS_COLORS.OK;
				return `url(#arrow-${color.replace("#", "")})`;
			})
			.attr("stroke-dasharray", (link: any) => {
				if (link.relationship === "DEPENDS_ON") return "5, 8";
				if (link.relationship === "HOSTED_ON") return "2, 2";
				return "none";
			})
			.attr("opacity", (link: any) => getDefaultDetailedLinkOpacity(link, 0.6))
			.style("pointer-events", "none");

		const trafficLink = container
			.append("g")
			.selectAll("path")
			.data(
				detailedLinks.filter(
					(link: any) => link.relationship === "CONNECTS_TO",
				),
			)
			.join("path")
			.attr("fill", "none")
			.attr("stroke-width", 3)
			.attr("stroke", "#10b981")
			.attr("stroke-dasharray", "4, 16")
			.attr("opacity", (link: any) => getDefaultDetailedLinkOpacity(link, 0.7));

		trafficLink
			.append("animate")
			.attr("attributeName", "stroke-dashoffset")
			.attr("from", "20")
			.attr("to", "0")
			.attr("dur", "1s")
			.attr("repeatCount", "indefinite");

		const nodeSelection = container
			.append("g")
			.selectAll("g")
			.data(validNodes)
			.join("g")
			.attr("class", "cursor-pointer group")
			.attr("opacity", (node) => {
				if (!hasSearchMatches) return 1;
				return matchingNodeIds.has(node.id) ||
					matchingClusterNames.has(node.clusterName)
					? 1
					: 0.18;
			})
			.on("click", (_event, node) => onNodeClick(node))
			.call(
				d3
					.drag<SVGGElement, GraphNode>()
					.on("start", dragstarted)
					.on("drag", dragged)
					.on("end", dragended) as any,
			);

		nodeSelection
			.append("circle")
			.attr("r", (node) =>
				node.status === "CRITICAL" ? 32 : node.status === "WARNING" ? 28 : 24,
			)
			.attr("fill", (node) =>
				matchingNodeIds.has(node.id) ? "#3a2f08" : "#1a1a1a",
			)
			.attr("stroke", (node) => {
				if (matchingNodeIds.has(node.id)) return "#facc15";
				if (node.status === "CRITICAL") return STATUS_COLORS.CRITICAL;
				if (node.status === "WARNING") return STATUS_COLORS.WARNING;
				return "#345bf2";
			})
			.attr("stroke-width", (node) =>
				matchingNodeIds.has(node.id) ? 5 : node.status === "CRITICAL" ? 4 : 2,
			)
			.attr("filter", (node) =>
				matchingNodeIds.has(node.id) ? "drop-shadow(0 0 14px #facc15)" : null,
			)
			.attr("class", "node-circle transition-all duration-300");

		// Label inferior persistente (truncado para no ensuciar)
		nodeSelection
			.append("text")
			.attr("dy", "3.5em")
			.attr("text-anchor", "middle")
			.attr("fill", "#a3a3a3")
			.attr("font-size", "10px")
			.attr("class", "node-label pointer-events-none")
			.text((node) =>
				node.label.length > 15
					? node.label.substring(0, 12) + "..."
					: node.label,
			);

		nodeSelection
			.append("text")
			.attr("dy", "-2.6em")
			.attr("text-anchor", "middle")
			.attr("fill", "#fbbf24")
			.attr("font-size", "9px")
			.attr("font-weight", 800)
			.attr("class", "link-count-badge pointer-events-none")
			.text((node) => {
				const linkCount = linkCountByNodeId.get(node.id) || 0;
				return linkCount > 4 ? `+${linkCount} links` : "";
			});

		nodeSelection
			.append("text")
			.attr("dy", "-3.8em")
			.attr("text-anchor", "middle")
			.attr("fill", "#fb7185")
			.attr("font-size", "9px")
			.attr("font-weight", 800)
			.attr("paint-order", "stroke")
			.attr("stroke", "#0f172a")
			.attr("stroke-width", 3)
			.attr("class", "geo-outlier-badge pointer-events-none")
			.text((node: any) =>
				selectedCluster === node.clusterName && node.isGeoOutlier
					? "geo outlier"
					: "",
			);

		const enforceContainment = () => {
			validNodes.forEach((node: any) => {
				if (!node.clusterName) return;
				const contained = clampPointToCluster(node.clusterName, node.x, node.y);
				if (contained.x === node.x && contained.y === node.y) return;
				node.x = contained.x;
				node.y = contained.y;
				node.vx = 0;
				node.vy = 0;
			});
		};

		const renderPositions = () => {
			enforceContainment();
			clusterSelection?.attr(
				"transform",
				([, center]) => `translate(${center.x},${center.y})`,
			);
			clusterLinkSelection
				.selectAll(
					"path.cluster-link-base, path.cluster-link-standby-flow, path.cluster-link-bilateral-flow",
				)
				.attr("d", (link) => {
					const source = clusterCenters[link.source];
					const target = clusterCenters[link.target];
					return source && target ? curvedPath(source, target, 0.12) : "";
				});
			linkSelection.attr("d", (link: any) => {
				const source = getRenderedEndpoint(link.source);
				const target = getRenderedEndpoint(link.target);
				return source && target ? curvedPath(source, target, 0.16) : "";
			});
			trafficLink.attr("d", (link: any) => {
				const source = getRenderedEndpoint(link.source);
				const target = getRenderedEndpoint(link.target);
				return source && target ? curvedPath(source, target, 0.16) : "";
			});
			nodeSelection.attr(
				"transform",
				(node: any) => `translate(${node.x},${node.y})`,
			);
		};

		const moveClusterWithMembers = (name: string, dx: number, dy: number) => {
			if (dx === 0 && dy === 0) return;
			const center = clusterCenters[name];
			if (!center) return;
			const boundedDelta = getBoundedClusterDelta(
				center,
				dx,
				dy,
				clusterBounds,
			);
			if (boundedDelta.dx === 0 && boundedDelta.dy === 0) return;
			center.x += boundedDelta.dx;
			center.y += boundedDelta.dy;
			const previousOffset = clusterOffsetRef.current.get(name) || {
				dx: 0,
				dy: 0,
			};
			clusterOffsetRef.current.set(name, {
				dx: previousOffset.dx + boundedDelta.dx,
				dy: previousOffset.dy + boundedDelta.dy,
			});
			validNodes.forEach((node: any) => {
				if (node.clusterName !== name) return;
				node.targetX += boundedDelta.dx;
				node.targetY += boundedDelta.dy;
				const contained = clampPointToCluster(
					name,
					(node.x ?? node.targetX) + boundedDelta.dx,
					(node.y ?? node.targetY) + boundedDelta.dy,
				);
				node.x = contained.x;
				node.y = contained.y;
				node.vx = 0;
				node.vy = 0;
				nodeStateRef.current.set(node.id, {
					x: node.x,
					y: node.y,
					vx: 0,
					vy: 0,
				});
			});
		};

		const resolveClusterCollisions = (activeName: string) => {
			for (let pass = 0; pass < 5; pass++) {
				let moved = false;
				const entries = Object.entries(clusterCenters);
				for (let i = 0; i < entries.length; i++) {
					for (let j = i + 1; j < entries.length; j++) {
						const [nameA, centerA] = entries[i];
						const [nameB, centerB] = entries[j];
						const minDistance = centerA.radius + centerB.radius + 28;
						const dx = centerB.x - centerA.x;
						const dy = centerB.y - centerA.y;
						const distance = Math.hypot(dx, dy) || 1;
						if (distance >= minDistance) continue;
						const ux = dx / distance;
						const uy = dy / distance;
						const overlap = minDistance - distance;
						if (nameA === activeName) {
							moveClusterWithMembers(nameB, ux * overlap, uy * overlap);
						} else if (nameB === activeName) {
							moveClusterWithMembers(nameA, -ux * overlap, -uy * overlap);
						} else {
							moveClusterWithMembers(
								nameA,
								(-ux * overlap) / 2,
								(-uy * overlap) / 2,
							);
							moveClusterWithMembers(
								nameB,
								(ux * overlap) / 2,
								(uy * overlap) / 2,
							);
						}
						moved = true;
					}
				}
				if (!moved) break;
			}
		};

		clusterSelection?.call(
			d3
				.drag<
					SVGGElement,
					[
						string,
						{
							x: number;
							y: number;
							radius: number;
							count: number;
							hasGeo: boolean;
						},
					]
				>()
				.on("start", (event) => {
					event.sourceEvent?.stopPropagation();
				})
				.on("drag", (event, [name]) => {
					moveClusterWithMembers(name, event.dx, event.dy);
					resolveClusterCollisions(name);
					renderPositions();
					simulation.alpha(0.08).restart();
				}) as any,
		);

		// Hover interactions
		nodeSelection
			.on("mouseover", (_event, d) => {
				const connectedNodeIds = new Set<string>([d.id]);
				validLinks.forEach((link: any) => {
					const sourceId = getLinkEndpointId(link.source);
					const targetId = getLinkEndpointId(link.target);
					if (sourceId === d.id) connectedNodeIds.add(targetId);
					if (targetId === d.id) connectedNodeIds.add(sourceId);
				});
				const isConnectedLink = (link: any) => {
					const sourceId = getLinkEndpointId(link.source);
					const targetId = getLinkEndpointId(link.target);
					return sourceId === d.id || targetId === d.id;
				};

				nodeSelection.attr("opacity", (node) =>
					connectedNodeIds.has(node.id) ? 1 : 0.18,
				);
				nodeSelection
					.select("circle")
					.attr("stroke-width", (node) => {
						if (node.id === d.id) return 6;
						if (connectedNodeIds.has(node.id)) return 4;
						return node.status === "CRITICAL" ? 4 : 2;
					})
					.attr("filter", (node) =>
						connectedNodeIds.has(node.id)
							? "drop-shadow(0 0 8px currentColor)"
							: null,
					);
				nodeSelection
					.select(".node-label")
					.attr("fill", (node) =>
						connectedNodeIds.has(node.id) ? "white" : "#a3a3a3",
					)
					.attr("font-weight", (node) =>
						connectedNodeIds.has(node.id) ? "bold" : "normal",
					)
					.text((node) =>
						connectedNodeIds.has(node.id)
							? node.label
							: node.label.length > 15
								? node.label.substring(0, 12) + "..."
								: node.label,
					);

				linkSelection.attr("opacity", (link: any) =>
					isConnectedLink(link) ? 0.9 : 0.08,
				);
				trafficLink.attr("opacity", (link: any) =>
					isConnectedLink(link) ? 0.95 : 0.08,
				);
			})
			.on("mouseout", () => {
				nodeSelection.attr("opacity", (node) => {
					if (!hasSearchMatches) return 1;
					return matchingNodeIds.has(node.id) ||
						matchingClusterNames.has(node.clusterName)
						? 1
						: 0.18;
				});
				nodeSelection
					.select("circle")
					.attr("stroke", (node) => {
						if (matchingNodeIds.has(node.id)) return "#facc15";
						if (node.status === "CRITICAL") return STATUS_COLORS.CRITICAL;
						if (node.status === "WARNING") return STATUS_COLORS.WARNING;
						return "#345bf2";
					})
					.attr("stroke-width", (node) =>
						matchingNodeIds.has(node.id)
							? 5
							: node.status === "CRITICAL"
								? 4
								: 2,
					)
					.attr("filter", (node) =>
						matchingNodeIds.has(node.id)
							? "drop-shadow(0 0 14px #facc15)"
							: null,
					);
				nodeSelection
					.select(".node-label")
					.attr("fill", "#a3a3a3")
					.attr("font-weight", "normal")
					.text((node) =>
						node.label.length > 15
							? node.label.substring(0, 12) + "..."
							: node.label,
					);
				linkSelection.attr("opacity", (link: any) =>
					getDefaultDetailedLinkOpacity(link, 0.6),
				);
				trafficLink.attr("opacity", (link: any) =>
					getDefaultDetailedLinkOpacity(link, 0.7),
				);
			});

		simulation.on("tick", () => {
			enforceContainment();
			renderPositions();

			// SAVE STATE: Persistent Cartesian Plane
			validNodes.forEach((n: any) => {
				nodeStateRef.current.set(n.id, { x: n.x, y: n.y, vx: n.vx, vy: n.vy });
			});
		});

		function clampToCluster(subject: any, x: number, y: number) {
			if (!subject.clusterName) return { x, y };
			return clampPointToCluster(subject.clusterName, x, y);
		}

		function dragstarted(event: any) {
			if (!event.active) simulation.alphaTarget(0.3).restart();
			event.subject.fx = event.subject.x;
			event.subject.fy = event.subject.y;
		}
		function dragged(event: any) {
			const next = clampToCluster(event.subject, event.x, event.y);
			event.subject.fx = next.x;
			event.subject.fy = next.y;
			event.subject.x = next.x;
			event.subject.y = next.y;
			renderPositions();
		}
		function dragended(event: any) {
			if (!event.active) simulation.alphaTarget(0);
			const next = clampToCluster(
				event.subject,
				event.subject.x,
				event.subject.y,
			);
			event.subject.x = next.x;
			event.subject.y = next.y;
			event.subject.vx = 0;
			event.subject.vy = 0;
			event.subject.fx = null;
			event.subject.fy = null;
			nodeStateRef.current.set(event.subject.id, {
				x: next.x,
				y: next.y,
				vx: 0,
				vy: 0,
			});
		}

		return () => {
			simulation.stop();
			svg.on(".zoom", null);
		};
	}, [
		links,
		nodes,
		onNodeClick,
		groupByLocation,
		selectedCluster,
		graphSearch,
	]);

	return (
		<div className="w-full h-full relative overflow-hidden bg-surface-950 grid-bg flex">
			{/* Filter Sidebar */}
			<div className="w-64 bg-neutral-900/80 backdrop-blur border-r border-white/5 p-6 flex flex-col space-y-6 z-20 overflow-y-auto custom-scrollbar">
				<div>
					<h3 className="text-xs font-black text-neutral-500 uppercase tracking-widest mb-4">
						Discovery Filters
					</h3>

					<div className="space-y-4">
						<label className="block">
							<span className="text-[10px] font-bold text-neutral-400 uppercase mb-1 block">
								Graph Search
							</span>
							<div className="relative">
								<input
									type="text"
									className="w-full bg-neutral-950 border border-yellow-500/20 rounded-lg pl-8 pr-8 py-2 text-xs text-white outline-none focus:border-yellow-400 transition-colors"
									placeholder="Search any CI field..."
									value={graphSearch}
									onChange={(e) => setGraphSearch(e.target.value)}
								/>
								<span className="material-symbols-outlined absolute left-2 top-1/2 -translate-y-1/2 text-sm text-yellow-400">
									search
								</span>
								{graphSearch && (
									<button
										type="button"
										onClick={() => setGraphSearch("")}
										className="absolute right-2 top-1/2 -translate-y-1/2 text-neutral-500 hover:text-yellow-300"
									>
										×
									</button>
								)}
							</div>
						</label>

						<label className="block">
							<span className="text-[10px] font-bold text-neutral-400 uppercase mb-1 block">
								Group by Location
							</span>
							<button
								onClick={() => setGroupByLocation(!groupByLocation)}
								className={`w-full flex items-center justify-between px-3 py-2 rounded-lg border transition-all ${groupByLocation ? "bg-brand-500/10 border-brand-500 text-brand-400" : "bg-neutral-950 border-white/5 text-neutral-500"}`}
							>
								<span className="text-[10px] font-black uppercase tracking-tighter">
									{groupByLocation ? "Enabled" : "Disabled"}
								</span>
								<span className="material-symbols-outlined text-sm">
									{groupByLocation ? "group_work" : "blur_off"}
								</span>
							</button>
						</label>

						{selectedFilterCount > 0 && (
							<div
								className="flex flex-wrap gap-1"
								aria-label="Selected graph filters"
							>
								{filterLayers.length > 0 && (
									<span className="rounded-full border border-brand-500/20 bg-brand-500/10 px-2 py-1 text-[9px] font-black uppercase text-brand-300">
										Tech: {renderFilterSummary(filterLayers, "All")}
									</span>
								)}
								{filterLocations.length > 0 && (
									<span className="rounded-full border border-brand-500/20 bg-brand-500/10 px-2 py-1 text-[9px] font-black uppercase text-brand-300">
										Location: {renderFilterSummary(filterLocations, "All")}
									</span>
								)}
								{filterOwners.length > 0 && (
									<span className="rounded-full border border-brand-500/20 bg-brand-500/10 px-2 py-1 text-[9px] font-black uppercase text-brand-300">
										Owner: {renderFilterSummary(filterOwners, "All")}
									</span>
								)}
							</div>
						)}

						<section aria-label="Technology filters" className="rounded-xl border border-white/5 bg-neutral-950/60">
							<button
								type="button"
								onClick={() => toggleFilterSection("technology")}
								className="flex w-full items-center justify-between px-3 py-2 text-left"
								aria-expanded={expandedFilters.technology}
								aria-controls="graph-filter-technology"
							>
								<span className="text-[10px] font-bold text-neutral-400 uppercase">
									Technology
								</span>
								<span className="text-[10px] text-neutral-500">
									{renderFilterSummary(filterLayers, "All")}
								</span>
							</button>
							{expandedFilters.technology && (
								<div id="graph-filter-technology" className="space-y-2 px-3 pb-3">
									<div className="flex items-center gap-2">
										<button
											type="button"
											onClick={() =>
												setSelection(
													(categories ?? []).map((c) => c.name),
													setFilterLayers,
												)
											}
											className="text-[9px] font-black uppercase text-brand-400 hover:text-brand-300"
										>
											Select all
										</button>
										<button
											type="button"
											onClick={() => setFilterLayers([])}
											className="text-[9px] font-black uppercase text-neutral-500 hover:text-white"
										>
											Clear
										</button>
									</div>
									<label className="sr-only" htmlFor="graph-filter-technology-search">
										Search technologies
									</label>
									<input
										id="graph-filter-technology-search"
										type="search"
										className="w-full bg-neutral-950 border border-white/5 rounded-lg px-3 py-2 text-xs text-white outline-none focus:border-brand-500 transition-colors"
										placeholder="Search technologies..."
										value={searchTechnology}
										onChange={(e) => setSearchTechnology(e.target.value)}
									/>
									<div className="max-h-32 overflow-y-auto rounded-lg border border-white/5 bg-neutral-950 p-2 space-y-1 custom-scrollbar">
										{filteredTechnologies.map((c) => (
											<label
												key={c.name}
												className="flex items-center gap-2 text-xs text-neutral-300 hover:text-white"
											>
												<input
													type="checkbox"
													checked={filterLayers.includes(c.name)}
													onChange={() => toggleSelection(c.name, setFilterLayers)}
													className="accent-brand-500"
												/>
												<span>{c.name}</span>
											</label>
										))}
										{filteredTechnologies.length === 0 && (
											<span className="text-[10px] text-neutral-600">No layers</span>
										)}
									</div>
								</div>
							)}
						</section>

						<section aria-label="Location filters" className="rounded-xl border border-white/5 bg-neutral-950/60">
							<button
								type="button"
								onClick={() => toggleFilterSection("location")}
								className="flex w-full items-center justify-between px-3 py-2 text-left"
								aria-expanded={expandedFilters.location}
								aria-controls="graph-filter-location"
							>
								<span className="text-[10px] font-bold text-neutral-400 uppercase">
									Location
								</span>
								<span className="text-[10px] text-neutral-500">
									{renderFilterSummary(filterLocations, "All")}
								</span>
							</button>
							{expandedFilters.location && (
								<div id="graph-filter-location" className="space-y-2 px-3 pb-3">
									<div className="flex items-center gap-2">
										<button
											type="button"
											onClick={() => setSelection(allLocations, setFilterLocations)}
											className="text-[9px] font-black uppercase text-brand-400 hover:text-brand-300"
										>
											Select all
										</button>
										<button
											type="button"
											onClick={() => setFilterLocations([])}
											className="text-[9px] font-black uppercase text-neutral-500 hover:text-white"
										>
											Clear
										</button>
									</div>
									<label className="sr-only" htmlFor="graph-filter-location-search">
										Search locations
									</label>
									<input
										id="graph-filter-location-search"
										type="search"
										className="w-full bg-neutral-950 border border-white/5 rounded-lg px-3 py-2 text-xs text-white outline-none focus:border-brand-500 transition-colors"
										placeholder="Search locations..."
										value={searchLocation}
										onChange={(e) => setSearchLocation(e.target.value)}
									/>
									<div className="max-h-36 overflow-y-auto rounded-lg border border-white/5 bg-neutral-950 p-2 space-y-1 custom-scrollbar">
										{filteredLocations.map((loc) => (
											<label
												key={loc}
												className="flex items-center gap-2 text-xs text-neutral-300 hover:text-white"
											>
												<input
													type="checkbox"
													checked={filterLocations.includes(loc)}
													onChange={() => toggleSelection(loc, setFilterLocations)}
													className="accent-brand-500"
												/>
												<span>{loc}</span>
											</label>
										))}
										{filteredLocations.length === 0 && (
											<span className="text-[10px] text-neutral-600">No locations</span>
										)}
									</div>
								</div>
							)}
						</section>

						<section aria-label="Owner filters" className="rounded-xl border border-white/5 bg-neutral-950/60">
							<button
								type="button"
								onClick={() => toggleFilterSection("owner")}
								className="flex w-full items-center justify-between px-3 py-2 text-left"
								aria-expanded={expandedFilters.owner}
								aria-controls="graph-filter-owner"
							>
								<span className="text-[10px] font-bold text-neutral-400 uppercase">
									Owner
								</span>
								<span className="text-[10px] text-neutral-500">
									{renderFilterSummary(filterOwners, "All")}
								</span>
							</button>
							{expandedFilters.owner && (
								<div id="graph-filter-owner" className="space-y-2 px-3 pb-3">
									<div className="flex items-center gap-2">
										<button
											type="button"
											onClick={() =>
												setSelection(
													(owners ?? []).map((o) => o.name),
													setFilterOwners,
												)
											}
											className="text-[9px] font-black uppercase text-brand-400 hover:text-brand-300"
										>
											Select all
										</button>
										<button
											type="button"
											onClick={() => setFilterOwners([])}
											className="text-[9px] font-black uppercase text-neutral-500 hover:text-white"
										>
											Clear
										</button>
									</div>
									<label className="sr-only" htmlFor="graph-filter-owner-search">
										Search owners
									</label>
									<input
										id="graph-filter-owner-search"
										type="search"
										className="w-full bg-neutral-950 border border-white/5 rounded-lg px-3 py-2 text-xs text-white outline-none focus:border-brand-500 transition-colors"
										placeholder="Search owners..."
										value={searchOwner}
										onChange={(e) => setSearchOwner(e.target.value)}
									/>
									<div className="max-h-32 overflow-y-auto rounded-lg border border-white/5 bg-neutral-950 p-2 space-y-1 custom-scrollbar">
										{filteredOwners.map((o) => (
											<label
												key={o.name}
												className="flex items-center gap-2 text-xs text-neutral-300 hover:text-white"
											>
												<input
													type="checkbox"
													checked={filterOwners.includes(o.name)}
													onChange={() => toggleSelection(o.name, setFilterOwners)}
													className="accent-brand-500"
												/>
												<span>{o.name}</span>
											</label>
										))}
										{filteredOwners.length === 0 && (
											<span className="text-[10px] text-neutral-600">No owners</span>
										)}
									</div>
								</div>
							)}
						</section>

						<button
							type="button"
							onClick={() => {
								setFilterLayers([]);
								setFilterLocations([]);
								setFilterOwners([]);
								setSearchTechnology("");
								setSearchLocation("");
								setSearchOwner("");
								setGraphSearch("");
							}}
							className="w-full py-2 text-[10px] font-black text-neutral-500 hover:text-white transition-colors uppercase tracking-widest"
						>
							Reset All
						</button>
					</div>
				</div>

				<div className="pt-6 border-t border-white/5">
					<div className="flex items-center gap-2 mb-2">
						<div className="w-2 h-2 rounded-full bg-brand-500 shadow-[0_0_8px_rgba(52,91,242,0.5)]"></div>
						<span className="text-[10px] font-bold text-neutral-300 uppercase">
							Visible Nodes: {nodes.length}
						</span>
					</div>
				</div>
			</div>

			{/* Graph Canvas */}
			<div className="flex-1 relative">
				<svg ref={svgRef} className="w-full h-full" />
				<AnimatedLinksLayer svgRef={svgRef} links={links} />

				{isLoading && (
					<div className="absolute inset-0 flex items-center justify-center bg-black/20 backdrop-blur-sm z-10">
						<div className="flex flex-col items-center gap-4">
							<div className="w-12 h-12 border-4 border-brand-500/20 border-t-brand-500 rounded-full animate-spin"></div>
							<span className="text-xs font-black text-brand-500 uppercase tracking-widest">
								Calculating Topology...
							</span>
						</div>
					</div>
				)}

				<div className="absolute bottom-4 left-4 flex flex-col gap-2 p-3 glass rounded-lg text-xs pointer-events-none select-none">
					<div className="flex items-center gap-2">
						<div className="w-3 h-3 bg-brand-500 rounded-full"></div>{" "}
						Operational
					</div>
					<div className="flex items-center gap-2">
						<div className="w-3 h-3 bg-orange-500 rounded-full"></div> Degraded
					</div>
					<div className="flex items-center gap-2">
						<div className="w-3 h-3 bg-red-500 rounded-full"></div> Critical
					</div>
					<div className="h-px bg-white/10 my-1"></div>
					<p className="text-[8px] text-neutral-500 uppercase font-black">
						Controls
					</p>
					<p className="text-[9px] text-neutral-400">
						Wheel: Zoom | Drag: Pan | Click: Detail
					</p>
				</div>
			</div>
		</div>
	);
};

export default GraphCMDB;
