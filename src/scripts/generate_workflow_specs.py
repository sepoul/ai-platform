#!/usr/bin/env python
"""Quick playground script — prints the workflow spec for registered graphs."""

import sys
sys.path.insert(0, "src")

from mathai.math_qa.workflow import math_qa_graph

GRAPHS = {
    "math_qa": math_qa_graph,
}


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else None

    for job_type, graph in GRAPHS.items():
        if target and job_type != target:
            continue
        print(f"Graph: {job_type}")
        print(f"  Nodes: {[n.__name__ for n in graph.node_defs]}")
        print()


if __name__ == "__main__":
    main()
