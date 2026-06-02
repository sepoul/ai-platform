"""Human-review gates for math_qa — shared across both planes.

The gate list is consumed by both:
  - the control plane (`JobControl.gates`) — to type the review request,
  - the execution plane (`ExecutionPolicy.gates`) — to gate the graph run,
so it lives in core (NodeGate + the review schema are already in core).
"""
from __future__ import annotations

from ai_platform.jobs.execution_policy import NodeGate
from mathai.math_qa.models import UserComment

# Human review fires after the LaTeX render so the user reviews text + math
# together. Gate node name is a string here (no engine import).
MATH_QA_GATES = [NodeGate(node_name="GenerateLatexStep", review_type=UserComment)]
