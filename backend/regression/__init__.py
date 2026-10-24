#
# Regression tests — recorded calls, replayed against an agent (D-18).
#
#   recorded call  ->  test (caller turns + expectations)
#   test + agent   ->  text replay through the real Flows graph and LLM, a few times
#                  ->  checks: where it ended and what it collected (code),
#                      and rules about what the agent said (a grader model)
#
# Any version, or the unsaved draft, can be run against an agent's tests, so a
# change can be checked against every call that once went wrong.
#

from .grader import MEDICAL_SAFETY_CHECK, grade_with_openai
from .replay import replay
from .runner import run
from .scenario import clean, evaluate, from_call

__all__ = ["MEDICAL_SAFETY_CHECK", "clean", "evaluate", "from_call", "grade_with_openai", "replay", "run"]
