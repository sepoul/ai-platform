"""Single source of truth for the domains this application loads.

Adding a domain is a one-line change here — the API and worker
bootstraps iterate over `DOMAINS` and don't import any domain modules
directly.
"""
from __future__ import annotations

from ai_platform.jobs.domain import DomainRegister
from mathai.domain import register as math_qa_register


DOMAINS: list[DomainRegister] = [math_qa_register]
