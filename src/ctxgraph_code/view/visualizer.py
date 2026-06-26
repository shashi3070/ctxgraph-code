from __future__ import annotations

import json

from ctxgraph_code.graph.storage import Storage


def render_view(storage: Storage) -> str:
    nodes = storage.get_all_nodes()
    edges = storage.get_all_edges()

    file_nodes = [n for n in nodes if n.type == "file"]
    symbol_nodes = [n for n in nodes if n.type != "file"]

    graph_data: dict = {
        "nodes": [],
        "links": [],
    }

    file_node_ids = {n.id for n in file_nodes}

    for node in file_nodes:
        graph_data["nodes"].append(
            {
                "id": node.id,
                "label": _short_path(node.path or node.name),
                "type": "file",
                "summary": (node.summary or "")[:100],
                "importance": node.importance,
            }
        )

    for node in symbol_nodes:
        graph_data["nodes"].append(
            {
                "id": node.id,
                "label": node.name,
                "type": node.type,
                "summary": (node.summary or "")[:100],
                "importance": node.importance,
            }
        )

    seen_links = set()
    for edge in edges:
        if edge.source_id in file_node_ids or edge.target_id in file_node_ids:
            key = (edge.source_id, edge.target_id)
            if key not in seen_links:
                seen_links.add(key)
                graph_data["links"].append(
                    {
                        "source": edge.source_id,
                        "target": edge.target_id,
                        "relation": edge.relation,
                    }
                )

    json_data = json.dumps(graph_data, indent=2)
    template = _get_html_template()
    return template.replace("/* GRAPH_DATA */", json_data)


def _short_path(path: str) -> str:
    parts = path.split("/")
    if len(parts) > 3:
        return "/".join(parts[:2] + ["..."] + parts[-1:])
    return path


def _get_html_template() -> str:
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ctxgraph-code - Knowledge Graph</title>
<script src="https://d3js.org/d3.v7.min.js"></script>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0d1117; color: #c9d1d9; overflow: hidden; }
#container { width: 100vw; height: 100vh; position: relative; }
svg { width: 100%; height: 100%; }
#toolbar { position: absolute; top: 16px; left: 16px; z-index: 10; display: flex; gap: 8px; align-items: center; background: #161b22; padding: 12px 16px; border-radius: 8px; border: 1px solid #30363d; }
#toolbar input { background: #0d1117; border: 1px solid #30363d; color: #c9d1d9; padding: 6px 12px; border-radius: 4px; width: 220px; font-size: 13px; }
#toolbar select { background: #0d1117; border: 1px solid #30363d; color: #c9d1d9; padding: 6px 8px; border-radius: 4px; font-size: 13px; }
#toolbar label { font-size: 13px; color: #8b949e; }
#legend { position: absolute; bottom: 16px; left: 16px; z-index: 10; background: #161b22; padding: 12px; border-radius: 8px; border: 1px solid #30363d; font-size: 12px; display: flex; gap: 16px; }
.legend-item { display: flex; align-items: center; gap: 6px; }
.legend-dot { width: 10px; height: 10px; border-radius: 50%; }
#tooltip { position: absolute; z-index: 20; background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 12px; font-size: 13px; max-width: 400px; pointer-events: none; display: none; box-shadow: 0 4px 12px rgba(0,0,0,0.4); }
#tooltip .tt-name { font-weight: 600; color: #58a6ff; margin-bottom: 4px; }
#tooltip .tt-type { color: #8b949e; font-size: 11px; margin-bottom: 4px; }
#tooltip .tt-summary { color: #c9d1d9; font-size: 12px; }
#stats { position: absolute; bottom: 16px; right: 16px; z-index: 10; background: #161b22; padding: 8px 12px; border-radius: 8px; border: 1px solid #30363d; font-size: 11px; color: #8b949e; }
.link { stroke-opacity: 0.4; }
.link.imports { stroke: #58a6ff; }
.link.calls { stroke: #3fb950; }
.link.defines { stroke: #d29922; }
.link.extends { stroke: #bc8cff; }
.node { cursor: pointer; transition: opacity 0.2s; }
.node:hover { opacity: 0.8; }
.node-label { font-size: 11px; fill: #8b949e; pointer-events: none; text-shadow: 0 1px 2px #0d1117, 0 -1px 2px #0d1117, 1px 0 2px #0d1117, -1px 0 2px #0d1117; }
.node.highlighted .node-label { fill: #c9d1d9; font-weight: 600; }
.link.highlighted { stroke-opacity: 0.8; }
</style>
</head>
<body>
<div id="container">
  <div id="toolbar">
    <label>Search:</label>
    <input type="text" id="search" placeholder="Search nodes..." oninput="filterGraph(this.value)">
    <label>Filter:</label>
    <select id="filterType" onchange="filterByType(this.value)">
      <option value="all">All</option>
      <option value="file">Files</option>
      <option value="class">Classes</option>
      <option value="function">Functions</option>
    </select>
  </div>
  <div id="legend">
    <div class="legend-item"><div class="legend-dot" style="background:#58a6ff"></div> File</div>
    <div class="legend-item"><div class="legend-dot" style="background:#d29922"></div> Class</div>
    <div class="legend-item"><div class="legend-dot" style="background:#3fb950"></div> Function</div>
    <div class="legend-item"><svg width="20" height="2"><line x1="0" y1="1" x2="20" y2="1" stroke="#58a6ff" stroke-width="1.5" stroke-dasharray="4,2"/></svg> Import</div>
    <div class="legend-item"><svg width="20" height="2"><line x1="0" y1="1" x2="20" y2="1" stroke="#3fb950" stroke-width="1.5" stroke-dasharray="2,2"/></svg> Call</div>
  </div>
  <div id="stats"></div>
  <div id="tooltip">
    <div class="tt-name"></div>
    <div class="tt-type"></div>
    <div class="tt-summary"></div>
  </div>
<svg width="100%" height="100%"></svg>
</div>
<script>
document.addEventListener("DOMContentLoaded", () => {
const graphData = /* GRAPH_DATA */;
const width = window.innerWidth;
const height = window.innerHeight;

const svg = d3.select("svg");
svg.attr("width", width).attr("height", height);
svg.attr("viewBox", `0 0 ${width} ${height}`);

const g = svg.append("g");

const zoom = d3.zoom()
  .scaleExtent([0.1, 4])
  .on("zoom", (event) => g.attr("transform", event.transform));

svg.call(zoom);

const colorMap = { file: "#58a6ff", class: "#d29922", function: "#3fb950", module: "#bc8cff" };

const simulation = d3.forceSimulation(graphData.nodes)
  .force("link", d3.forceLink(graphData.links).id(d => d.id).distance(d => {
    return d.relation === "imports" ? 100 : 80;
  }))
  .force("charge", d3.forceManyBody().strength(-200))
  .force("center", d3.forceCenter(width / 2, height / 2))
  .force("collision", d3.forceCollide(20));

const link = g.append("g")
  .selectAll("line")
  .data(graphData.links)
  .join("line")
  .attr("class", d => `link ${d.relation}`)
  .attr("stroke-width", 1.5);

const node = g.append("g")
  .selectAll("g")
  .data(graphData.nodes)
  .join("g")
  .attr("class", "node")
  .call(d3.drag()
    .on("start", (event, d) => {
      if (!event.active) simulation.alphaTarget(0.3).restart();
      d.fx = d.x;
      d.fy = d.y;
    })
    .on("drag", (event, d) => {
      d.fx = event.x;
      d.fy = event.y;
    })
    .on("end", (event, d) => {
      if (!event.active) simulation.alphaTarget(0);
      d.fx = null;
      d.fy = null;
    })
  );

node.append("circle")
  .attr("r", d => 5 + (d.importance || 0.5) * 8)
  .attr("fill", d => colorMap[d.type] || "#8b949e")
  .attr("stroke", "#161b22")
  .attr("stroke-width", 1.5);

node.append("text")
  .attr("class", "node-label")
  .text(d => d.label)
  .attr("dx", d => 10 + (d.importance || 0.5) * 5)
  .attr("dy", 4);

node.on("mouseover", function(event, d) {
  const tt = d3.select("#tooltip");
  tt.style("display", "block");
  tt.select(".tt-name").text(d.label);
  tt.select(".tt-type").text(`Type: ${d.type}`);
  tt.select(".tt-summary").text(d.summary || "");

  const connected = new Set();
  graphData.links.forEach(l => {
    const sid = typeof l.source === 'object' ? l.source.id : l.source;
    const tid = typeof l.target === 'object' ? l.target.id : l.target;
    if (sid === d.id) connected.add(tid);
    if (tid === d.id) connected.add(sid);
  });

  d3.selectAll(".node").each(function(n) {
    if (n.id === d.id || connected.has(n.id)) {
      d3.select(this).classed("highlighted", true);
      d3.select(this).select("circle").attr("opacity", 1);
      d3.select(this).select("text").attr("opacity", 1);
    } else {
      d3.select(this).select("circle").attr("opacity", 0.15);
      d3.select(this).select("text").attr("opacity", 0.15);
    }
  });

  d3.selectAll(".link").each(function(l) {
    const sid = typeof l.source === 'object' ? l.source.id : l.source;
    const tid = typeof l.target === 'object' ? l.target.id : l.target;
    if (sid === d.id || tid === d.id) {
      d3.select(this).classed("highlighted", true);
    }
  });
})
.on("mousemove", function(event) {
  d3.select("#tooltip")
    .style("left", (event.pageX + 12) + "px")
    .style("top", (event.pageY - 10) + "px");
})
.on("mouseout", function() {
  d3.select("#tooltip").style("display", "none");
  d3.selectAll(".node").each(function(n) {
    d3.select(this).classed("highlighted", false);
    d3.select(this).select("circle").attr("opacity", 1);
    d3.select(this).select("text").attr("opacity", 1);
  });
  d3.selectAll(".link").classed("highlighted", false);
});

simulation.on("tick", () => {
  link
    .attr("x1", d => d.source.x)
    .attr("y1", d => d.source.y)
    .attr("x2", d => d.target.x)
    .attr("y2", d => d.target.y);
  node.attr("transform", d => `translate(${d.x},${d.y})`);
});

d3.select("#stats").text(`Nodes: ${graphData.nodes.length} | Edges: ${graphData.links.length}`);

window.filterGraph = function(query) {
  const q = query.toLowerCase();
  d3.selectAll(".node").each(function(d) {
    const match = !q || d.label.toLowerCase().includes(q) || (d.summary && d.summary.toLowerCase().includes(q));
    d3.select(this).style("display", match ? null : "none");
  });
};

window.filterByType = function(type) {
  d3.selectAll(".node").each(function(d) {
    const match = type === "all" || d.type === type;
    d3.select(this).style("display", match ? null : "none");
  });
};

window.addEventListener("resize", () => {
  const w = window.innerWidth;
  const h = window.innerHeight;
  svg.attr("width", w).attr("height", h);
  svg.attr("viewBox", `0 0 ${w} ${h}`);
});
});
</script>
</body>
</html>"""
