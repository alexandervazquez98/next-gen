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

const GEO_OUTLIER_DISTANCE_KM = 50;

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
