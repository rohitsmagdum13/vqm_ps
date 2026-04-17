"""Package: utils/decorators

Logging decorators for VQMS — split into focused modules.

Four decorators that eliminate boilerplate logging across the codebase.
Each handles both sync and async functions transparently.

Re-exports so existing imports like
``from utils.decorators import log_service_call`` keep working.
"""

from utils.decorators.api import log_api_call
from utils.decorators.llm import log_llm_call
from utils.decorators.policy import log_policy_decision
from utils.decorators.service import log_service_call

__all__ = [
    "log_api_call",
    "log_llm_call",
    "log_policy_decision",
    "log_service_call",
]
