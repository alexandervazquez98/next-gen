import * as d3 from 'd3';
import type { GraphNode } from '../types';
import type { LinkData } from './RelationshipManager';

export const VISUAL_EDITOR_VIEWBOX_WIDTH = 2200;
export const VISUAL_EDITOR_VIEWBOX_HEIGHT = 1400;
const COORDINATE_PADDING = 180;
const LOCAL_NODE_SPACING = 86;

type AnchorNode = GraphNode & {
  anchorX: number;
  anchorY: number;
  mapX: number;
  mapY: number;
  layer: string;
  clusterId: string;
  clusterLabel: string;
  clusterX: number;
  clusterY: number;
  clusterCount: number;
};

export type PositionedVisualNode = AnchorNode;

export interface VisualRelationshipCluster {
  id: string;
  label: string;
  x: number;
  y: number;
  count: number;
}

export interface VisualRelationshipLayout {
  nodes: PositionedVisualNode[];
  clusters: VisualRelationshipCluster[];
}

const nodeLabel = (node: GraphNode) => node.label || node.id;
const nodeLayer = (node: GraphNode) => node.category ?? node.type;
const hasNumber = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);

export const clusterIdForNode = (node: GraphNode) =>
  node.location_name?.trim() || node.category?.trim() || node.type || 'Unassigned';

const rawCoordinateForNode = (node: GraphNode, fallbackIndex: number) => {
  if (hasNumber(node.x) && hasNumber(node.y)) return { x: node.x, y: node.y };
  if (hasNumber(node.location?.long) && hasNumber(node.location?.lat)) {
    return {
      x: VISUAL_EDITOR_VIEWBOX_WIDTH / 2 + (node.location.long + 117) * 3000,
      y: VISUAL_EDITOR_VIEWBOX_HEIGHT / 2 - (node.location.lat - 32.5) * 3000,
    };
  }

  const angle = (fallbackIndex / Math.max(1, 12)) * Math.PI * 2 - Math.PI / 2;
  const radius = 260 + Math.floor(fallbackIndex / 12) * 120;
  return {
    x: VISUAL_EDITOR_VIEWBOX_WIDTH / 2 + Math.cos(angle) * radius,
    y: VISUAL_EDITOR_VIEWBOX_HEIGHT / 2 + Math.sin(angle) * radius,
  };
};

const localOffset = (index: number) => {
  if (index === 0) return { x: 0, y: 0 };
  const ring = Math.ceil(index / 8);
  const slot = (index - 1) % 8;
  const angle = slot * (Math.PI / 4);
  const radius = ring * LOCAL_NODE_SPACING;
  return { x: Math.cos(angle) * radius, y: Math.sin(angle) * radius };
};

export const buildVisualRelationshipLayout = (visibleNodes: GraphNode[], visibleLinks: LinkData[] = []): VisualRelationshipLayout => {
  const orderedNodes = [...visibleNodes].sort((a, b) => a.id.localeCompare(b.id));
  if (orderedNodes.length === 0) return { nodes: [], clusters: [] };

  const rawNodes = orderedNodes.map((node, index) => ({
    node,
    layer: nodeLayer(node),
    clusterId: clusterIdForNode(node),
    ...rawCoordinateForNode(node, index),
  }));

  const clusterBuckets = new Map<string, typeof rawNodes>();
  for (const rawNode of rawNodes) {
    clusterBuckets.set(rawNode.clusterId, [...(clusterBuckets.get(rawNode.clusterId) ?? []), rawNode]);
  }

  const rawClusters = Array.from(clusterBuckets.entries())
    .map(([id, bucket], index) => {
      const xMean = d3.mean(bucket, (item) => item.x);
      const yMean = d3.mean(bucket, (item) => item.y);
      const fallback = rawCoordinateForNode(bucket[0].node, index);
      return {
        id,
        label: id,
        count: bucket.length,
        rawX: xMean ?? fallback.x,
        rawY: yMean ?? fallback.y,
      };
    })
    .sort((a, b) => a.id.localeCompare(b.id));

  const xExtent = d3.extent(rawClusters, (cluster) => cluster.rawX);
  const yExtent = d3.extent(rawClusters, (cluster) => cluster.rawY);
  const xScale = d3
    .scaleLinear()
    .domain(xExtent[0] === xExtent[1] ? [xExtent[0] ?? 0, (xExtent[0] ?? 0) + 1] : [xExtent[0] ?? 0, xExtent[1] ?? 1])
    .range([COORDINATE_PADDING, VISUAL_EDITOR_VIEWBOX_WIDTH - COORDINATE_PADDING]);
  const yScale = d3
    .scaleLinear()
    .domain(yExtent[0] === yExtent[1] ? [yExtent[0] ?? 0, (yExtent[0] ?? 0) + 1] : [yExtent[0] ?? 0, yExtent[1] ?? 1])
    .range([COORDINATE_PADDING, VISUAL_EDITOR_VIEWBOX_HEIGHT - COORDINATE_PADDING]);

  const clusters = rawClusters.map((cluster) => ({
    id: cluster.id,
    label: cluster.label,
    count: cluster.count,
    x: xScale(cluster.rawX),
    y: yScale(cluster.rawY),
  }));
  const clusterMap = new Map(clusters.map((cluster) => [cluster.id, cluster]));
  const clusterNodeIndex = new Map<string, number>();

  const layoutNodes: PositionedVisualNode[] = rawNodes.map(({ node, layer, clusterId }) => {
    const cluster = clusterMap.get(clusterId)!;
    const indexInCluster = clusterNodeIndex.get(clusterId) ?? 0;
    clusterNodeIndex.set(clusterId, indexInCluster + 1);
    const offset = localOffset(indexInCluster);
    const anchorX = cluster.x + offset.x;
    const anchorY = cluster.y + offset.y;

    return {
      ...node,
      layer,
      clusterId,
      clusterLabel: cluster.label,
      clusterX: cluster.x,
      clusterY: cluster.y,
      clusterCount: cluster.count,
      anchorX,
      anchorY,
      mapX: anchorX,
      mapY: anchorY,
    };
  });

  const simulationNodes = layoutNodes.map((node) => ({ ...node, x: node.anchorX, y: node.anchorY }));
  const simulationNodeIds = new Set(simulationNodes.map((node) => node.id));
  const simulationLinks = visibleLinks
    .filter((link) => simulationNodeIds.has(link.source) && simulationNodeIds.has(link.target))
    .map((link) => ({ source: link.source, target: link.target }));

  const simulation = d3
    .forceSimulation(simulationNodes)
    .force('charge', d3.forceManyBody<PositionedVisualNode & { x: number; y: number }>().strength(-320))
    .force('collision', d3.forceCollide<PositionedVisualNode & { x: number; y: number }>().radius(62))
    .force('link', d3.forceLink<PositionedVisualNode & { x: number; y: number }, { source: string; target: string }>(simulationLinks).id((node) => node.id).distance(190).strength(0.08))
    .force('x', d3.forceX<PositionedVisualNode & { x: number; y: number }>((node) => node.anchorX).strength(0.1))
    .force('y', d3.forceY<PositionedVisualNode & { x: number; y: number }>((node) => node.anchorY).strength(0.1))
    .stop();

  simulation.tick(120);
  simulation.stop();

  const simulatedById = new Map(simulationNodes.map((node) => [node.id, node]));
  return {
    clusters,
    nodes: layoutNodes.map((node) => {
      const simulated = simulatedById.get(node.id);
      return {
        ...node,
        mapX: simulated?.x ?? node.mapX,
        mapY: simulated?.y ?? node.mapY,
        label: nodeLabel(node),
      };
    }),
  };
};

export const buildAnchoredVisualLayout = (visibleNodes: GraphNode[], visibleLinks: LinkData[] = []) =>
  buildVisualRelationshipLayout(visibleNodes, visibleLinks).nodes;
