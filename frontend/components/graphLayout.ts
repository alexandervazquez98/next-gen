export type ClusterBounds = {
	width: number;
	height: number;
	padding?: number;
};

export type ClusterCircle = {
	x: number;
	y: number;
	radius: number;
};

export type ClusterCenter = ClusterCircle & {
	count?: number;
	hasGeo?: boolean;
};

export type GeoPoint = {
	lat?: number;
	long?: number;
};

export type GeoQualityNode = {
	id: string;
	location?: GeoPoint;
};

export type ClusterGeoQuality = {
	validCoordinateCount: number;
	missingCoordinateCount: number;
	outlierNodeIds: Set<string>;
	medianCoordinate: { lat: number; long: number } | null;
};

export type GeoProjectionPoint = {
	id: string;
	lat: number;
	long: number;
};

export type GeoProjectionOptions = {
	width: number;
	height: number;
	paddingX?: number;
	paddingY?: number;
	reservedRightWidth?: number;
};

const GEO_OUTLIER_DISTANCE_KM = 50;
const MIN_GEO_DOMAIN_DEGREES = 0.02;
export const GRAPH_NODE_COLLISION_RADIUS = 38;

const clamp = (value: number, min: number, max: number) => {
	if (min > max) return (min + max) / 2;
	return Math.min(max, Math.max(min, value));
};

const median = (values: number[]) => {
	const sorted = values.slice().sort((a, b) => a - b);
	const mid = Math.floor(sorted.length / 2);
	return sorted.length % 2 === 0
		? (sorted[mid - 1] + sorted[mid]) / 2
		: sorted[mid];
};

const expandDomain = (min: number, max: number, minimumSpan: number) => {
	const span = max - min;
	if (span >= minimumSpan) return { min, max };
	const center = (min + max) / 2;
	const halfSpan = minimumSpan / 2;
	return { min: center - halfSpan, max: center + halfSpan };
};

export const isValidGeoCoordinate = (lat: unknown, lon: unknown) =>
	typeof lat === "number" &&
	typeof lon === "number" &&
	Number.isFinite(lat) &&
	Number.isFinite(lon) &&
	lat >= -90 &&
	lat <= 90 &&
	lon >= -180 &&
	lon <= 180;

const distanceKm = (
	from: { lat: number; long: number },
	to: { lat: number; long: number },
) => {
	const earthRadiusKm = 6371;
	const toRadians = (degrees: number) => (degrees * Math.PI) / 180;
	const dLat = toRadians(to.lat - from.lat);
	const dLon = toRadians(to.long - from.long);
	const lat1 = toRadians(from.lat);
	const lat2 = toRadians(to.lat);
	const a =
		Math.sin(dLat / 2) ** 2 +
		Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2;
	return earthRadiusKm * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
};

export const summarizeClusterGeoQuality = <T extends GeoQualityNode>(
	nodes: T[],
): ClusterGeoQuality => {
	const validCoordinates = nodes
		.map((node) => ({
			id: node.id,
			lat: node.location?.lat,
			long: node.location?.long,
		}))
		.filter(({ lat, long }) => isValidGeoCoordinate(lat, long)) as Array<{
		id: string;
		lat: number;
		long: number;
	}>;
	const validCoordinateCount = validCoordinates.length;
	const missingCoordinateCount = nodes.length - validCoordinateCount;
	const medianCoordinate =
		validCoordinateCount > 0
			? {
					lat: median(validCoordinates.map((coordinate) => coordinate.lat)),
					long: median(validCoordinates.map((coordinate) => coordinate.long)),
				}
			: null;
	const outlierNodeIds = new Set<string>();

	if (medianCoordinate && validCoordinateCount >= 3) {
		validCoordinates.forEach((coordinate) => {
			if (distanceKm(coordinate, medianCoordinate) > GEO_OUTLIER_DISTANCE_KM) {
				outlierNodeIds.add(coordinate.id);
			}
		});
	}

	return {
		validCoordinateCount,
		missingCoordinateCount,
		outlierNodeIds,
		medianCoordinate,
	};
};

export const projectGeoPointsToCanvas = (
	points: GeoProjectionPoint[],
	{
		width,
		height,
		paddingX = Math.max(130, width * 0.08),
		paddingY = Math.max(120, height * 0.1),
		reservedRightWidth = 0,
	}: GeoProjectionOptions,
) => {
	const result = new Map<string, { x: number; y: number }>();
	if (points.length === 0) return result;

	const minX = paddingX;
	const maxX = Math.max(minX, width - paddingX - reservedRightWidth);
	const minY = paddingY;
	const maxY = Math.max(minY, height - paddingY);
	const lats = points.map((point) => point.lat);
	const longs = points.map((point) => point.long);
	const latDomain = expandDomain(
		Math.min(...lats),
		Math.max(...lats),
		MIN_GEO_DOMAIN_DEGREES,
	);
	const longDomain = expandDomain(
		Math.min(...longs),
		Math.max(...longs),
		MIN_GEO_DOMAIN_DEGREES,
	);

	points.forEach((point) => {
		result.set(point.id, {
			x:
				minX +
				((point.long - longDomain.min) / (longDomain.max - longDomain.min)) *
					(maxX - minX),
			y:
				maxY -
				((point.lat - latDomain.min) / (latDomain.max - latDomain.min)) *
					(maxY - minY),
		});
	});

	return result;
};

export const estimateClusterRadius = (count: number) => {
	const safeCount = Math.max(1, count);
	const capacityRadius =
		48 + Math.sqrt(safeCount) * GRAPH_NODE_COLLISION_RADIUS * 1.45;
	return Math.min(520, Math.max(110, capacityRadius));
};

export const getClusterInnerRadius = (clusterRadius: number) =>
	Math.max(0, clusterRadius - GRAPH_NODE_COLLISION_RADIUS - 12);

export const getClusterNodeTarget = <T extends ClusterCircle>(
	center: T,
	index: number,
	total: number,
) => {
	if (total <= 1) return { x: center.x, y: center.y };

	const innerRadius = getClusterInnerRadius(center.radius);
	const goldenAngle = Math.PI * (3 - Math.sqrt(5));
	const normalizedIndex = index + 0.5;
	const radius = Math.sqrt(normalizedIndex / total) * innerRadius;
	const angle = index * goldenAngle - Math.PI / 2;

	return {
		x: center.x + Math.cos(angle) * radius,
		y: center.y + Math.sin(angle) * radius,
	};
};

export const clampClusterCenterToBounds = <T extends ClusterCircle>(
	center: T,
	{ width, height, padding = 24 }: ClusterBounds,
): T => {
	const minX = center.radius + padding;
	const maxX = width - center.radius - padding;
	const minY = center.radius + padding;
	const maxY = height - center.radius - padding;

	return {
		...center,
		x: clamp(center.x, minX, maxX),
		y: clamp(center.y, minY, maxY),
	};
};

export const resolveClusterOverlaps = <T extends ClusterCenter>(
	centers: Record<string, T>,
	bounds: ClusterBounds,
	{
		padding = 18,
		iterations = 8,
	}: { padding?: number; iterations?: number } = {},
): Record<string, T> => {
	const resolved = Object.fromEntries(
		Object.entries(centers).map(([name, center]) => [name, { ...center }]),
	) as Record<string, T>;
	const names = Object.keys(resolved);

	for (let iteration = 0; iteration < iterations; iteration += 1) {
		let moved = false;
		for (let i = 0; i < names.length; i += 1) {
			for (let j = i + 1; j < names.length; j += 1) {
				const a = resolved[names[i]];
				const b = resolved[names[j]];
				const minDistance = a.radius + b.radius + padding;
				let dx = b.x - a.x;
				let dy = b.y - a.y;
				let distance = Math.hypot(dx, dy);

				if (distance >= minDistance) continue;
				if (distance === 0) {
					const angle = ((i + j + iteration + 1) * Math.PI) / 4;
					dx = Math.cos(angle);
					dy = Math.sin(angle);
					distance = 1;
				}

				const push = (minDistance - distance) / 2;
				const ux = dx / distance;
				const uy = dy / distance;
				resolved[names[i]] = clampClusterCenterToBounds(
					{ ...a, x: a.x - ux * push, y: a.y - uy * push },
					bounds,
				);
				resolved[names[j]] = clampClusterCenterToBounds(
					{ ...b, x: b.x + ux * push, y: b.y + uy * push },
					bounds,
				);
				moved = true;
			}
		}
		if (!moved) break;
	}

	return resolved;
};

export const getBoundedClusterDelta = (
	center: ClusterCircle,
	dx: number,
	dy: number,
	bounds: ClusterBounds,
) => {
	const bounded = clampClusterCenterToBounds(
		{ ...center, x: center.x + dx, y: center.y + dy },
		bounds,
	);

	return {
		dx: bounded.x - center.x,
		dy: bounded.y - center.y,
	};
};
