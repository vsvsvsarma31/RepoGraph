from __future__ import annotations

import json

import click

from .graph import build_knowledge_graph


@click.group(name="repo-graph", invoke_without_command=True)
@click.option("--repo", "repo", required=True, help="Local repository path or HTTPS GitHub URL.")
@click.option("-o", "--output", "--out", default=".", show_default=True, help="Directory for graph.json and graph.html.")
@click.option("--since-days", "--days", default=365, show_default=True, type=int, help="Git history window for co-change edges.")
@click.option("--min-weight", default=1.0, show_default=True, type=float, help="Drop edges below this weight.")
@click.option("--max-nodes", default=5000, show_default=True, type=int, help="Prune to at most this many nodes.")
@click.pass_context
def cli(ctx: click.Context, repo: str, output: str, since_days: int, min_weight: float, max_nodes: int) -> None:
    if ctx.invoked_subcommand is not None:
        return
    try:
        build_knowledge_graph(repo, output_dir=output, since_days=since_days, min_weight=min_weight, max_nodes=max_nodes)
    except Exception as exc:
        click.echo(json.dumps({"error": str(exc), "file": ""}, ensure_ascii=True), err=True)
        raise SystemExit(1)


if __name__ == "__main__":
    cli()
