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

const clamp = (value: number, min: number, max: number) => {
	if (min > max) return (min + max) / 2;
	return Math.min(max, Math.max(min, value));
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
