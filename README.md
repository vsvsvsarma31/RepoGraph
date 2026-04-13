# Repo Graph

Turn any GitHub repo into an interactive knowledge graph.

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue)](#)
[![License MIT](https://img.shields.io/badge/License-MIT-green)](#)
[![PRs welcome](https://img.shields.io/badge/PRs-welcome-brightgreen)](#)

## What it does
Repo Graph scans a repository, extracts files and symbols, connects them with relationship edges, and writes the result as a graph you can inspect. The output is a structured `graph.json` file plus a self-contained `graph.html` visualization, so you can review both the raw data and the interactive map of the codebase.


## Installation
```bash
git clone https:https://github.com/vsvsvsarma31/RepoGraph
cd repo_graph
pip install -e .
```

## Usage
```bash
# Local repo
repo_graph --repo /path/to/project

# GitHub URL
repo_graph --repo https://github.com/vsvsvsarma31/RepoGraph

# With options
repo_graph --repo . --out graph.json --max-nodes 50000 --min-weight 0.1 --days 90
```

## User Manual
1. Install Python 3.10+ and make sure `git` is available on your PATH.
2. Clone this repository and install it with `pip install -e .`.
3. Point the tool at either a local repository path or a GitHub URL using `--repo`.
4. Choose an output folder with `--out` if you do not want files written to the current directory.
5. Tune `--days`, `--min-weight`, and `--max-nodes` if the graph is too large or too noisy.
6. Open `graph.html` in a browser to explore the graph visually.
7. Use `graph.json` if you want to feed the results into another tool or inspect the raw data.
8. If parsing feels slow, rerun the command on the same repo and let the cache speed things up.
9. If the graph looks crowded, raise `--min-weight` or lower `--max-nodes`.
10. If you need more context, start with a smaller repository and then move up to a larger one.

## Output
- `graph.json` — structured node/edge data
- `graph.html` — self-contained interactive visualization (open in browser)

## Graph structure
| Node types | Edge types |
| --- | --- |
| file | imports |
| function | calls |
| class | references |
| module | co_change |
| contributor | semantic_sim |

## How it works
1. Clone or open the repository and collect source files while skipping generated or vendored directories.
2. Parse each file into files and symbols so the tool can see functions, classes, and imports.
3. Resolve imports into graph edges by matching raw import strings to files and modules.
4. Detect call and reference links by walking the syntax tree for each function or class body.
5. Mine `git log` to find files that changed together and connect them with co-change edges.
6. Embed symbol text with sentence embeddings and connect similar symbols with semantic edges.
7. Prune weak or isolated parts of the graph, then write the final JSON and HTML outputs.

## Requirements
- Python 3.10+
- Git installed and on PATH
- No API keys required - all processing is local

## Dependencies
- tree-sitter
- sentence-transformers
- gitpython
- pyvis
- click

## Project structure
- `repo_graph/main.py` - CLI entry point
- `repo_graph/clone.py` - repo cloning and file enumeration
- `repo_graph/parse.py` - parsing source files into nodes and raw imports
- `repo_graph/resolve.py` - import resolution into edges
- `repo_graph/git_history.py` - co-change and contributor edges
- `repo_graph/semantic.py` - embedding and semantic similarity edges
- `repo_graph/prune.py` - pruning and scaling
- `repo_graph/output.py` - graph.json and graph.html writer
- `repo_graph/cache.py` - content-hash cache
