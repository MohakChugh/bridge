export interface GraphNode {
  id: number;
  text: string;
  collection?: string;
  document_name?: string;
  tags?: string[];
  summary?: string;
}

export interface GraphEdge {
  source: number;
  target: number;
  relation: string;
}

export interface Cluster {
  id: string;
  name: string;
  color: string;
  nodeIds: Set<number>;
}

export const CLUSTER_PALETTE = [
  "#7c3aed", "#06b6d4", "#f59e0b", "#10b981", "#ef4444", "#8b5cf6",
  "#ec4899", "#14b8a6", "#f97316", "#6366f1", "#84cc16", "#e879f9",
];

export function computeDegrees(nodes: GraphNode[], edges: GraphEdge[]): Map<number, number> {
  const degrees = new Map<number, number>();
  for (const node of nodes) {
    degrees.set(node.id, 0);
  }
  for (const edge of edges) {
    degrees.set(edge.source, (degrees.get(edge.source) ?? 0) + 1);
    degrees.set(edge.target, (degrees.get(edge.target) ?? 0) + 1);
  }
  return degrees;
}

function nameCommunity(nodeIds: Set<number>, nodeMap: Map<number, GraphNode>): string {
  const freq = new Map<string, number>();
  const STOP_WORDS = new Set(["the", "a", "an", "is", "in", "of", "to", "for", "and", "this", "that", "with", "from", "on", "at", "by"]);
  for (const id of nodeIds) {
    const node = nodeMap.get(id);
    if (!node) continue;
    if (node.collection) {
      freq.set(node.collection, (freq.get(node.collection) ?? 0) + 3);
    }
    if (node.document_name) {
      freq.set(node.document_name, (freq.get(node.document_name) ?? 0) + 2);
    }
    if (node.tags) {
      for (const tag of node.tags) {
        if (tag.length > 2 && !STOP_WORDS.has(tag.toLowerCase())) {
          freq.set(tag, (freq.get(tag) ?? 0) + 1);
        }
      }
    }
  }
  if (freq.size === 0) {
    // Fallback: extract first meaningful words from node texts
    const words = new Map<string, number>();
    for (const id of nodeIds) {
      const node = nodeMap.get(id);
      if (!node?.text) continue;
      const firstWords = node.text.split(/[\s\n]+/).slice(0, 3).filter(w => w.length > 3 && !STOP_WORDS.has(w.toLowerCase()));
      for (const w of firstWords) {
        const clean = w.replace(/[^a-zA-Z0-9-]/g, "").toLowerCase();
        if (clean.length > 3) words.set(clean, (words.get(clean) ?? 0) + 1);
      }
    }
    if (words.size > 0) {
      let best = ""; let bestC = 0;
      for (const [w, c] of words) { if (c > bestC) { best = w; bestC = c; } }
      return best;
    }
    return `Group ${nodeIds.size}`;
  }
  let best = "";
  let bestCount = 0;
  for (const [label, count] of freq) {
    if (count > bestCount) {
      best = label;
      bestCount = count;
    }
  }
  return best;
}

export function louvainCommunities(nodes: GraphNode[], edges: GraphEdge[]): Cluster[] {
  const nodeMap = new Map<number, GraphNode>();
  for (const n of nodes) nodeMap.set(n.id, n);

  const adj = new Map<number, { neighbor: number; weight: number }[]>();
  for (const n of nodes) adj.set(n.id, []);
  for (const e of edges) {
    adj.get(e.source)?.push({ neighbor: e.target, weight: 1 });
    adj.get(e.target)?.push({ neighbor: e.source, weight: 1 });
  }

  const m = edges.length;
  if (m === 0) {
    const cluster: Cluster = { id: "c0", name: "All", color: CLUSTER_PALETTE[0], nodeIds: new Set(nodes.map(n => n.id)) };
    return [cluster];
  }
  const m2 = 2 * m;

  const community = new Map<number, number>();
  const nodeIds = nodes.map(n => n.id);
  for (let i = 0; i < nodeIds.length; i++) community.set(nodeIds[i], i);

  const ki = new Map<number, number>();
  for (const n of nodes) {
    ki.set(n.id, adj.get(n.id)?.reduce((s, e) => s + e.weight, 0) ?? 0);
  }

  const sigmaTot = new Map<number, number>();
  for (const [id, c] of community) sigmaTot.set(c, (sigmaTot.get(c) ?? 0) + (ki.get(id) ?? 0));

  let improved = true;
  let iterations = 0;
  while (improved && iterations < 20) {
    improved = false;
    iterations++;
    for (const nodeId of nodeIds) {
      const currentComm = community.get(nodeId)!;
      const kNode = ki.get(nodeId) ?? 0;

      const neighborComms = new Map<number, number>();
      for (const { neighbor, weight } of adj.get(nodeId) ?? []) {
        const nc = community.get(neighbor)!;
        neighborComms.set(nc, (neighborComms.get(nc) ?? 0) + weight);
      }

      const kiIn = neighborComms.get(currentComm) ?? 0;
      const removeCost = kiIn - (sigmaTot.get(currentComm)! - kNode) * kNode / m2;

      let bestComm = currentComm;
      let bestGain = 0;

      for (const [targetComm, kiTarget] of neighborComms) {
        if (targetComm === currentComm) continue;
        const gain = kiTarget - (sigmaTot.get(targetComm) ?? 0) * kNode / m2 - removeCost;
        if (gain > bestGain) {
          bestGain = gain;
          bestComm = targetComm;
        }
      }

      if (bestComm !== currentComm) {
        sigmaTot.set(currentComm, (sigmaTot.get(currentComm) ?? 0) - kNode);
        sigmaTot.set(bestComm, (sigmaTot.get(bestComm) ?? 0) + kNode);
        community.set(nodeId, bestComm);
        improved = true;
      }
    }
  }

  const groups = new Map<number, Set<number>>();
  for (const [id, c] of community) {
    if (!groups.has(c)) groups.set(c, new Set());
    groups.get(c)!.add(id);
  }

  const sorted = [...groups.entries()].sort((a, b) => b[1].size - a[1].size);

  const usedNames = new Map<string, number>();
  return sorted.map(([, memberIds], i) => {
    let name = nameCommunity(memberIds, nodeMap);
    const count = usedNames.get(name) ?? 0;
    usedNames.set(name, count + 1);
    if (count > 0) name = `${name} (${count + 1})`;
    return {
      id: `c${i}`,
      name,
      color: CLUSTER_PALETTE[i % CLUSTER_PALETTE.length],
      nodeIds: memberIds,
    };
  });
}

export function assignClusters(
  nodes: GraphNode[],
  edges: GraphEdge[]
): { clusters: Cluster[]; clusterMap: Map<number, string> } {
  let clusters: Cluster[];

  const collections = new Set(nodes.map(n => n.collection).filter(Boolean));
  if (nodes.length < 10 || collections.size <= 1) {
    const groups = new Map<string, Set<number>>();
    for (const node of nodes) {
      const key = node.collection ?? "default";
      if (!groups.has(key)) groups.set(key, new Set());
      groups.get(key)!.add(node.id);
    }
    const sorted = [...groups.entries()].sort((a, b) => b[1].size - a[1].size);
    clusters = sorted.map(([name, memberIds], i) => ({
      id: `c${i}`,
      name,
      color: CLUSTER_PALETTE[i % CLUSTER_PALETTE.length],
      nodeIds: memberIds,
    }));
  } else {
    clusters = louvainCommunities(nodes, edges);
  }

  const clusterMap = new Map<number, string>();
  for (const cluster of clusters) {
    for (const nodeId of cluster.nodeIds) {
      clusterMap.set(nodeId, cluster.id);
    }
  }

  return { clusters, clusterMap };
}
