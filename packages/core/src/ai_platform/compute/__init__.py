"""Pluggable compute backends — the seam between submitting a job and
running it.

Storage is already pluggable (`ai_platform.workspace.bootstrap` picks
`local` or `b2`). Compute is the same idea applied to "how does work
travel from the API to a worker process".

Today: the worker polls the job repo. Tomorrow: Celery (or anything
else with a queue). Both look identical to the API caller — they
implement the same `ComputeBackend` protocol.
"""
from ai_platform.compute.base import ComputeBackend
from ai_platform.compute.bootstrap import bootstrap_compute

__all__ = ["ComputeBackend", "bootstrap_compute"]
