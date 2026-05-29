import * as d3 from 'd3';
import type { GraphNode } from '../types';
import type { LinkData } from './RelationshipManager';

export const VISUAL_EDITOR_VIEWBOX_WIDTH = 1600;
export const VISUAL_EDITOR_VIEWBOX_HEIGHT = 1000;
const COORDINATE_PADDING = 120;

type AnchorNode = GraphNode & {
  anchorX: number;
  anchorY: number;
  mapX: number;
  mapY: number;
  layer: string;
};

export type PositionedVisualNode = AnchorNode;

const nodeLabel = (node: GraphNode) => node.label || node.id;
const nodeLayer = (node: GraphNode) => node.category ?? node.type;
const hasNumber = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);

const rawCoordinateForNode = (node: GraphNode, fallbackIndex: number) => {
  if (hasNumber(node.x) && hasNumber(node.y)) return { x: node.x, y: node.y };
  if (hasNumber(node.location?.long) && hasNumber(node.location?.lat)) {
    return {
      x: VISUAL_EDITOR_VIEWBOX_WIDTH / 2 + (node.location.long + 117) * 3000,
      y: VISUAL_EDITOR_VIEWBOX_HEIGHT / 2 - (node.location.lat - 32.5) * 3000,
    };
  }

  const angle = (fallbackIndex / Math.max(1, 12)) * Math.PI * 2 - Math.PI / 2;
  const radius = 240 + Math.floor(fallbackIndex / 12) * 90;
  return {
    x: VISUAL_EDITOR_VIEWBOX_WIDTH / 2 + Math.cos(angle) * radius,
    y: VISUAL_EDITOR_VIEWBOX_HEIGHT / 2 + Math.sin(angle) * radius,
  };
};

export const buildAnchoredVisualLayout = (visibleNodes: GraphNode[], visibleLinks: LinkData[] = []): PositionedVisualNode[] => {
  const orderedNodes = [...visibleNodes].sort((a, b) => a.id.localeCompare(b.id));
  const rawNodes = orderedNodes.map((node, index) => ({
    node,
    layer: nodeLayer(node),
    ...rawCoordinateForNode(node, index),
  }));
  if (rawNodes.length === 0) return [];

  const xExtent = d3.extent(rawNodes, (item) => item.x);
  const yExtent = d3.extent(rawNodes, (item) => item.y);
  const xScale = d3
    .scaleLinear()
    .domain(xExtent[0] === xExtent[1] ? [xExtent[0] ?? 0, (xExtent[0] ?? 0) + 1] : [xExtent[0] ?? 0, xExtent[1] ?? 1])
    .range([COORDINATE_PADDING, VISUAL_EDITOR_VIEWBOX_WIDTH - COORDINATE_PADDING]);
  const yScale = d3
    .scaleLinear()
    .domain(yExtent[0] === yExtent[1] ? [yExtent[0] ?? 0, (yExtent[0] ?? 0) + 1] : [yExtent[0] ?? 0, yExtent[1] ?? 1])
    .range([COORDINATE_PADDING, VISUAL_EDITOR_VIEWBOX_HEIGHT - COORDINATE_PADDING]);

  const layoutNodes: PositionedVisualNode[] = rawNodes.map(({ node, layer, x, y }) => ({
    ...node,
    layer,
    anchorX: xScale(x),
    anchorY: yScale(y),
    mapX: xScale(x),
    mapY: yScale(y),
  }));

  const simulationNodes = layoutNodes.map((node) => ({ ...node, x: node.anchorX, y: node.anchorY }));
  const simulationNodeIds = new Set(simulationNodes.map((node) => node.id));
  const simulationLinks = visibleLinks
    .filter((link) => simulationNodeIds.has(link.source) && simulationNodeIds.has(link.target))
    .map((link) => ({ source: link.source, target: link.target }));

  const simulation = d3
    .forceSimulation(simulationNodes)
    .force('charge', d3.forceManyBody<PositionedVisualNode & { x: number; y: number }>().strength(-140))
    .force('collision', d3.forceCollide<PositionedVisualNode & { x: number; y: number }>().radius(54))
    .force('link', d3.forceLink<PositionedVisualNode & { x: number; y: number }, { source: string; target: string }>(simulationLinks).id((node) => node.id).distance(150).strength(0.12))
    .force('x', d3.forceX<PositionedVisualNode & { x: number; y: number }>((node) => node.anchorX).strength(0.18))
    .force('y', d3.forceY<PositionedVisualNode & { x: number; y: number }>((node) => node.anchorY).strength(0.18))
    .stop();

  simulation.tick(100);
  simulation.stop();

  const simulatedById = new Map(simulationNodes.map((node) => [node.id, node]));
  return layoutNodes.map((node) => {
    const simulated = simulatedById.get(node.id);
    return {
      ...node,
      mapX: simulated?.x ?? node.mapX,
      mapY: simulated?.y ?? node.mapY,
      label: nodeLabel(node),
    };
  });
};
