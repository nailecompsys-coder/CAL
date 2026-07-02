"""
Scheduling rules engine. Evaluates configurable rules and returns structured conflicts.
Config is stored in SchedulingRuleConfig (DB); rules can be enabled/disabled and tuned.
"""
from .engine import evaluate, get_rule_config
from .registry import ALL_RULES, Conflict, RuleDef

__all__ = [
    "Conflict",
    "RuleDef",
    "ALL_RULES",
    "evaluate",
    "get_rule_config",
]
