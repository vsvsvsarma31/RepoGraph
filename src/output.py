from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .pipeline import Node, Edge, _render_html, _summary

try:
    from pyvis.network import Network  # type: ignore
except Exception:  # pragma: no cover
    Network = None  # type: ignore


def _render_pyvis(graph: dict[str, Any], html_path: Path) -> bool:
    if Network is None:
        return False
    net = Network(height="100%", width="100%", bgcolor="#020617", font_color="#e2e8f0", directed=True, cdn_resources="in_line")
    net.toggle_physics(True)
    for node in graph["nodes"]:
        title = json.dumps(node, ensure_ascii=True, indent=2)
        size = 8 if node["type"] == "file" else 10
        color = {"file": "#60a5fa", "function": "#34d399", "class": "#f59e0b", "contributor": "#f472b6", "module": "#a78bfa"}.get(node["type"], "#cbd5e1")
        net.add_node(node["id"], label=node.get("name") or Path(node["path"]).name or node["id"], title=title, color=color, size=size)
    for edge in graph["edges"]:
        color = {"imports": "#93c5fd", "calls": "#34d399", "references": "#f59e0b", "co_change": "#f472b6", "semantic_sim": "#a78bfa"}.get(edge["type"], "#94a3b8")
        net.add_edge(edge["src"], edge["dst"], value=max(1.0, float(edge.get("weight", 1.0))), color=color, title=edge["type"])
    net.write_html(str(html_path), open_browser=False)
    return True


def write_graph(graph: dict[str, Any], output_dir: str | Path) -> tuple[Path, Path]:
    out = Path(output_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "graph.json"
    html_path = out / "graph.html"
    json_path.write_text(json.dumps(graph, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    if not _render_pyvis(graph, html_path):
        html_path.write_text(_render_html(graph), encoding="utf-8")
    return json_path, html_path


def render_summary(graph: dict[str, Any]) -> str:
    nodes = [Node(**{k: node[k] for k in ("id", "type", "path", "lang", "loc")}, extra={k: v for k, v in node.items() if k not in {"id", "type", "path", "lang", "loc"}}) for node in graph["nodes"]]
    edges = [Edge(**edge) for edge in graph["edges"]]
    return _summary(nodes, edges)
