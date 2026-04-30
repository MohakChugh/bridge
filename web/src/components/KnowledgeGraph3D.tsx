import React, { useRef, useState, useCallback, useMemo, useEffect } from "react";
import ForceGraph3D, { type ForceGraphMethods, type NodeObject } from "react-force-graph-3d";
import * as THREE from "three";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface GraphNode {
  id: number;
  text: string;
  collection?: string;
  tags?: string[];
  summary?: string;
  document_name?: string;
}

interface GraphEdge {
  source: number;
  target: number;
  relation: string;
}

interface Cluster {
  id: string;
  name: string;
  color: string;
  nodeIds: Set<number>;
}

export interface KnowledgeGraph3DProps {
  nodes: GraphNode[];
  edges: GraphEdge[];
  clusters: Cluster[];
  clusterMap: Map<number, string>;
  degreeMap: Map<number, number>;
  highlightCluster: string | null;
  onNodeSelect: (node: any) => void;
}

// Internal types used by react-force-graph
interface FGNode extends GraphNode {
  x?: number;
  y?: number;
  z?: number;
  __clusterColor?: string;
  __degree?: number;
}

interface FGLink {
  source: number | FGNode;
  target: number | FGNode;
  relation: string;
  __sourceClusterColor?: string;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const BG_COLOR = "#0a0a0f";
const DEFAULT_NODE_COLOR = "#6366f1";
const DIM_OPACITY = 0.08;
const CAMERA_TRANSITION_MS = 800;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function nodeSize(degree: number): number {
  return Math.cbrt(degree + 1) * 2 + 1;
}

/** Build a color->clusterColor lookup from clusters array */
function buildClusterColorMap(clusters: Cluster[]): Map<string, string> {
  const map = new Map<string, string>();
  for (const c of clusters) {
    map.set(c.id, c.color);
  }
  return map;
}

/** Truncate text for tooltip display */
function truncate(text: string, max: number): string {
  if (text.length <= max) return text;
  return text.slice(0, max - 1) + "…";
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function KnowledgeGraph3D({
  nodes,
  edges,
  clusters,
  clusterMap,
  degreeMap,
  highlightCluster,
  onNodeSelect,
}: KnowledgeGraph3DProps) {
  const graphRef = useRef<ForceGraphMethods<FGNode, FGLink>>();
  const containerRef = useRef<HTMLDivElement>(null);
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 });
  const [hoveredNode, setHoveredNode] = useState<FGNode | null>(null);
  const [tooltip, setTooltip] = useState<{
    x: number;
    y: number;
    node: FGNode;
  } | null>(null);

  // Track 1-hop neighbor set for highlighting
  const [hoverNeighbors, setHoverNeighbors] = useState<Set<number>>(new Set());

  // ---- Resize observer ----
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry) {
        setDimensions({
          width: entry.contentRect.width,
          height: entry.contentRect.height,
        });
      }
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // ---- Adjacency list (memoised) ----
  const adjacency = useMemo(() => {
    const adj = new Map<number, Set<number>>();
    for (const e of edges) {
      if (!adj.has(e.source)) adj.set(e.source, new Set());
      if (!adj.has(e.target)) adj.set(e.target, new Set());
      adj.get(e.source)!.add(e.target);
      adj.get(e.target)!.add(e.source);
    }
    return adj;
  }, [edges]);

  // ---- Cluster color lookup (memoised) ----
  const clusterColorMap = useMemo(
    () => buildClusterColorMap(clusters),
    [clusters],
  );

  // ---- Build graph data ----
  const graphData = useMemo(() => {
    const fgNodes: FGNode[] = nodes.map((n) => {
      const clusterId = clusterMap.get(n.id);
      const color = clusterId
        ? clusterColorMap.get(clusterId) ?? DEFAULT_NODE_COLOR
        : DEFAULT_NODE_COLOR;
      return {
        ...n,
        __clusterColor: color,
        __degree: degreeMap.get(n.id) ?? 0,
      };
    });

    const fgLinks: FGLink[] = edges.map((e) => {
      const srcClusterId = clusterMap.get(e.source);
      const srcColor = srcClusterId
        ? clusterColorMap.get(srcClusterId) ?? DEFAULT_NODE_COLOR
        : DEFAULT_NODE_COLOR;
      return {
        source: e.source,
        target: e.target,
        relation: e.relation,
        __sourceClusterColor: srcColor,
      };
    });

    return { nodes: fgNodes, links: fgLinks };
  }, [nodes, edges, clusterMap, clusterColorMap, degreeMap]);

  // ---- Determine visibility state for a node ----
  const isNodeHighlighted = useCallback(
    (node: FGNode): boolean => {
      // If there is a hovered node, highlight the hovered node + its 1-hop neighbors
      if (hoveredNode) {
        return (
          node.id === hoveredNode.id || hoverNeighbors.has(node.id as number)
        );
      }
      // If a cluster is externally highlighted, highlight only that cluster's nodes
      if (highlightCluster) {
        const cluster = clusters.find((c) => c.id === highlightCluster);
        return cluster ? cluster.nodeIds.has(node.id as number) : false;
      }
      // Nothing highlighted -- everything visible
      return true;
    },
    [hoveredNode, hoverNeighbors, highlightCluster, clusters],
  );

  // ---- Custom Three.js node object ----
  const nodeThreeObject = useCallback(
    (node: NodeObject<FGNode>) => {
      const n = node as FGNode;
      const degree = n.__degree ?? 0;
      const radius = nodeSize(degree);
      const color = n.__clusterColor ?? DEFAULT_NODE_COLOR;
      const highlighted = isNodeHighlighted(n);
      const opacity = highlighted ? 1 : DIM_OPACITY;

      // Main sphere
      const geometry = new THREE.SphereGeometry(radius, 16, 12);
      const material = new THREE.MeshLambertMaterial({
        color: new THREE.Color(color),
        emissive: new THREE.Color(color),
        emissiveIntensity: highlighted ? 0.6 : 0.15,
        transparent: true,
        opacity,
      });
      const mesh = new THREE.Mesh(geometry, material);

      // Outer glow sphere
      const glowGeometry = new THREE.SphereGeometry(radius * 1.6, 16, 12);
      const glowMaterial = new THREE.MeshBasicMaterial({
        color: new THREE.Color(color),
        transparent: true,
        opacity: highlighted ? 0.15 : 0.02,
        depthWrite: false,
      });
      const glowMesh = new THREE.Mesh(glowGeometry, glowMaterial);

      const group = new THREE.Group();
      group.add(mesh);
      group.add(glowMesh);

      return group;
    },
    [isNodeHighlighted],
  );

  // ---- Link color (source cluster color at reduced opacity) ----
  const linkColor = useCallback(
    (link: object) => {
      const l = link as FGLink;
      const baseColor = l.__sourceClusterColor ?? DEFAULT_NODE_COLOR;
      // Determine if link should be highlighted
      if (hoveredNode) {
        const srcId =
          typeof l.source === "object" ? (l.source as FGNode).id : l.source;
        const tgtId =
          typeof l.target === "object" ? (l.target as FGNode).id : l.target;
        const isConnected =
          srcId === hoveredNode.id || tgtId === hoveredNode.id;
        if (isConnected) {
          // Full brightness link
          return baseColor;
        }
        // Dim
        const c = new THREE.Color(baseColor);
        return `rgba(${Math.round(c.r * 255)}, ${Math.round(c.g * 255)}, ${Math.round(c.b * 255)}, 0.03)`;
      }
      if (highlightCluster) {
        const srcId =
          typeof l.source === "object" ? (l.source as FGNode).id : l.source;
        const cluster = clusters.find((c) => c.id === highlightCluster);
        if (cluster && cluster.nodeIds.has(srcId as number)) {
          return baseColor;
        }
        const c = new THREE.Color(baseColor);
        return `rgba(${Math.round(c.r * 255)}, ${Math.round(c.g * 255)}, ${Math.round(c.b * 255)}, 0.03)`;
      }
      return baseColor;
    },
    [hoveredNode, highlightCluster, clusters],
  );

  // ---- Link width ----
  const linkWidth = useCallback(
    (link: object) => {
      if (!hoveredNode) return 0.3;
      const l = link as FGLink;
      const srcId =
        typeof l.source === "object" ? (l.source as FGNode).id : l.source;
      const tgtId =
        typeof l.target === "object" ? (l.target as FGNode).id : l.target;
      return srcId === hoveredNode.id || tgtId === hoveredNode.id ? 1.2 : 0.15;
    },
    [hoveredNode],
  );

  // ---- Handlers ----
  const handleNodeHover = useCallback(
    (node: NodeObject<FGNode> | null) => {
      const n = node as FGNode | null;
      setHoveredNode(n);
      if (n) {
        const neighbors = adjacency.get(n.id as number) ?? new Set<number>();
        setHoverNeighbors(neighbors);
        // Position tooltip from 3D -> screen coords
        if (graphRef.current && n.x != null && n.y != null && n.z != null) {
          const screenCoords = graphRef.current.graph2ScreenCoords(
            n.x,
            n.y,
            n.z,
          );
          setTooltip({ x: screenCoords.x, y: screenCoords.y, node: n });
        }
      } else {
        setHoverNeighbors(new Set());
        setTooltip(null);
      }
    },
    [adjacency],
  );

  const handleNodeClick = useCallback(
    (node: NodeObject<FGNode>) => {
      const n = node as FGNode;
      onNodeSelect(n);
      // Fly camera to node
      if (graphRef.current && n.x != null && n.y != null && n.z != null) {
        const distance = 60;
        const distRatio = 1 + distance / Math.hypot(n.x, n.y, n.z || 1);
        graphRef.current.cameraPosition(
          {
            x: n.x * distRatio,
            y: n.y * distRatio,
            z: n.z * distRatio,
          },
          { x: n.x, y: n.y, z: n.z },
          CAMERA_TRANSITION_MS,
        );
      }
    },
    [onNodeSelect],
  );

  const handleBackgroundRightClick = useCallback(() => {
    // Reset camera to overview
    if (graphRef.current) {
      graphRef.current.zoomToFit(CAMERA_TRANSITION_MS, 50);
    }
  }, []);

  const handleBackgroundDoubleClick = useCallback(() => {
    // Also reset camera on double-click
    if (graphRef.current) {
      graphRef.current.zoomToFit(CAMERA_TRANSITION_MS, 50);
    }
  }, []);

  // ---- Configure d3 forces after mount ----
  useEffect(() => {
    if (!graphRef.current) return;
    const fg = graphRef.current;

    const charge = fg.d3Force("charge");
    if (charge && typeof charge.strength === "function") {
      charge.strength(-200);
    }

    const link = fg.d3Force("link");
    if (link && typeof link.distance === "function") {
      link.distance(50);
    }

    const center = fg.d3Force("center");
    if (center && typeof center.strength === "function") {
      center.strength(0.05);
    }
  }, [graphData]);

  // ---- Node label (HTML overlay on hover) ----
  const nodeLabel = useCallback((node: object) => {
    const n = node as FGNode;
    const tagsStr =
      n.tags && n.tags.length > 0 ? n.tags.slice(0, 5).join(", ") : "";
    return `
      <div style="
        background: rgba(10, 10, 15, 0.92);
        border: 1px solid rgba(100, 100, 255, 0.25);
        border-radius: 8px;
        padding: 10px 14px;
        max-width: 320px;
        font-family: 'Inter', system-ui, sans-serif;
        color: #e2e2f0;
        font-size: 12px;
        line-height: 1.5;
        backdrop-filter: blur(8px);
        box-shadow: 0 4px 24px rgba(0,0,0,0.6), 0 0 12px rgba(99,102,241,0.15);
      ">
        <div style="font-weight: 600; font-size: 13px; color: #fff; margin-bottom: 4px;">
          ${truncate(n.text, 120)}
        </div>
        ${n.collection ? `<div style="color: #a5b4fc; font-size: 11px; margin-bottom: 2px;">${n.collection}</div>` : ""}
        ${n.document_name ? `<div style="color: #94a3b8; font-size: 11px; margin-bottom: 2px;">${truncate(n.document_name, 60)}</div>` : ""}
        ${tagsStr ? `<div style="color: #7dd3fc; font-size: 10px; margin-top: 4px;">${tagsStr}</div>` : ""}
        ${n.summary ? `<div style="color: #94a3b8; font-size: 10px; margin-top: 4px; border-top: 1px solid rgba(100,100,255,0.15); padding-top: 4px;">${truncate(n.summary, 180)}</div>` : ""}
      </div>
    `;
  }, []);

  // ---- Link directional particles for a living feel ----
  const linkDirectionalParticles = useCallback(
    (link: object) => {
      if (!hoveredNode) return 0;
      const l = link as FGLink;
      const srcId =
        typeof l.source === "object" ? (l.source as FGNode).id : l.source;
      const tgtId =
        typeof l.target === "object" ? (l.target as FGNode).id : l.target;
      return srcId === hoveredNode.id || tgtId === hoveredNode.id ? 3 : 0;
    },
    [hoveredNode],
  );

  return (
    <div
      ref={containerRef}
      style={{
        width: "100%",
        height: "100%",
        position: "relative",
        background: BG_COLOR,
        overflow: "hidden",
        borderRadius: "8px",
      }}
    >
      <ForceGraph3D
        ref={graphRef as any}
        width={dimensions.width}
        height={dimensions.height}
        graphData={graphData}
        backgroundColor={BG_COLOR}
        nodeId="id"
        linkSource="source"
        linkTarget="target"
        // Node rendering
        nodeThreeObject={nodeThreeObject}
        nodeLabel={nodeLabel}
        // Link rendering
        linkColor={linkColor}
        linkWidth={linkWidth}
        linkOpacity={0.15}
        linkDirectionalParticles={linkDirectionalParticles}
        linkDirectionalParticleSpeed={0.006}
        linkDirectionalParticleWidth={1.5}
        linkDirectionalParticleColor={(link: object) => {
          const l = link as FGLink;
          return l.__sourceClusterColor ?? DEFAULT_NODE_COLOR;
        }}
        // Physics
        warmupTicks={100}
        cooldownTime={15000}
        d3AlphaDecay={0.01}
        d3VelocityDecay={0.3}
        // Interaction
        onNodeClick={handleNodeClick}
        onNodeHover={handleNodeHover}
        onBackgroundRightClick={handleBackgroundRightClick}
        onBackgroundClick={handleBackgroundDoubleClick}
        enableNavigationControls={true}
        enableNodeDrag={true}
        showNavInfo={false}
      />

      {/* Subtle vignette overlay */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          pointerEvents: "none",
          background:
            "radial-gradient(ellipse at center, transparent 50%, rgba(10,10,15,0.6) 100%)",
        }}
      />

      {/* Legend (cluster colors) */}
      {clusters.length > 0 && (
        <div
          style={{
            position: "absolute",
            bottom: 16,
            left: 16,
            display: "flex",
            flexDirection: "column",
            gap: 4,
            padding: "10px 12px",
            background: "rgba(10, 10, 15, 0.8)",
            borderRadius: 8,
            border: "1px solid rgba(100, 100, 255, 0.12)",
            backdropFilter: "blur(8px)",
            maxHeight: 200,
            overflowY: "auto",
            fontSize: 11,
            color: "#c4c4d8",
            fontFamily: "'Inter', system-ui, sans-serif",
          }}
        >
          {clusters.slice(0, 12).map((c) => (
            <div
              key={c.id}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 6,
                opacity:
                  highlightCluster && highlightCluster !== c.id ? 0.35 : 1,
                transition: "opacity 0.2s",
              }}
            >
              <span
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: "50%",
                  background: c.color,
                  boxShadow: `0 0 6px ${c.color}60`,
                  flexShrink: 0,
                }}
              />
              <span style={{ whiteSpace: "nowrap" }}>
                {truncate(c.name, 28)}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Node count HUD */}
      <div
        style={{
          position: "absolute",
          top: 12,
          right: 16,
          fontSize: 11,
          color: "#6366f1",
          fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
          background: "rgba(10, 10, 15, 0.7)",
          padding: "4px 10px",
          borderRadius: 6,
          border: "1px solid rgba(99, 102, 241, 0.15)",
          letterSpacing: "0.05em",
        }}
      >
        {nodes.length} nodes &middot; {edges.length} edges
      </div>

      {/* Controls hint */}
      <div
        style={{
          position: "absolute",
          bottom: 16,
          right: 16,
          fontSize: 10,
          color: "#4b5563",
          fontFamily: "'Inter', system-ui, sans-serif",
          textAlign: "right",
          lineHeight: 1.6,
        }}
      >
        orbit: drag &middot; zoom: scroll
        <br />
        click node: fly to &middot; click bg: reset
      </div>
    </div>
  );
}

export default KnowledgeGraph3D;
