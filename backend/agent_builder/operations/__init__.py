"""Agent operations: every change to an agent, as plain data.

Importing the area modules registers their operations (see registry.py).
"""

from . import agent, edge, node  # noqa: F401  (imported for registration)
from .registry import OPERATIONS, OperationDef, OperationError, apply_op, describe_op

__all__ = ["OPERATIONS", "OperationDef", "OperationError", "apply_op", "describe_op"]
