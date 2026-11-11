"""
MathSolverSkill — quick calculations and math word problems.

Two paths:
  1. If the utterance is a plain arithmetic expression (after turning spoken
     words like "times"/"percent of" into operators), it's evaluated with a
     safe AST evaluator — no ``eval``, no network, instant and exact.
  2. Otherwise (word problems, "explain this"), it hands the problem to the AI
     provider with an instruction to show the steps simply.

Requirements addressed: 7.2, 7.5, 7.6
"""

from __future__ import annotations

import ast
import logging
import operator
import re
from typing import Any, Optional

from meryna_platform.models import SkillContext, SkillResponse
from skills.base import Skill

logger = logging.getLogger("meryna.skills.math_solver")

# Allowed operators for the safe evaluator.
_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

# Spoken words → arithmetic symbols.
_WORD_TO_OP = [
    (r"\bplus\b|\badded to\b|\band\b", "+"),
    (r"\bminus\b|\bsubtract(?:ed)?\b|\bless\b", "-"),
    (r"\btimes\b|\bmultiplied by\b|\bmultiply\b|\bx\b", "*"),
    (r"\bdivided by\b|\bover\b", "/"),
    (r"\bto the power of\b|\bpower\b|\braised to\b|\bsquared\b", "**"),
    (r"\bmod(?:ulo)?\b", "%"),
]


class MathSolverSkill(Skill):
    """Solves calculations exactly and explains word problems via AI."""

    def __init__(self, ai_provider: Any) -> None:
        super().__init__(ai_provider)

    @property
    def name(self) -> str:
        return "math-solver-skill"

    @property
    def version(self) -> str:
        return "1.0.0"

    async def execute(self, context: SkillContext) -> SkillResponse:
        text = (context.utterance or "").strip()
        if not text:
            return SkillResponse(text="What would you like me to calculate?")

        # Try a direct, exact calculation first.
        expr = self._to_expression(text)
        if expr is not None:
            try:
                value = self._safe_eval(expr)
                return SkillResponse(text=f"That comes to {self._format(value)}.")
            except Exception as exc:  # noqa: BLE001
                logger.debug("Safe eval failed for %r: %s", expr, exc)

        # Otherwise treat it as a word problem for the AI to explain.
        return await self._ai_solve(text, context)

    # ------------------------------------------------------------------
    # Direct calculation path
    # ------------------------------------------------------------------

    def _to_expression(self, text: str) -> Optional[str]:
        """Turn a spoken/typed sum into an arithmetic expression, or None.

        Returns None when the text clearly isn't a bare calculation (e.g. a
        word problem with lots of prose) so it can be routed to the AI.
        """
        s = text.lower().strip().rstrip("?.!")

        # Handle "X percent of Y" -> "(X/100)*Y" before generic word swaps.
        s = re.sub(
            r"(\d+(?:\.\d+)?)\s*(?:percent|%)\s*of\s*(\d+(?:\.\d+)?)",
            r"(\1/100)*\2",
            s,
        )
        s = re.sub(r"(\d+(?:\.\d+)?)\s*(?:percent|%)", r"(\1/100)", s)

        # Strip common lead-ins.
        s = re.sub(
            r"^(what(?:'s| is)|calculate|compute|solve|how much is|"
            r"how many is|tell me|give me)\s+",
            "",
            s,
        )

        for pattern, sym in _WORD_TO_OP:
            s = re.sub(pattern, f" {sym} ", s)

        # Keep only characters valid in an arithmetic expression.
        cleaned = re.sub(r"[^0-9+\-*/%.()\s]", "", s)
        cleaned = cleaned.strip()

        # Must contain a digit and an operator to count as a calculation.
        if not cleaned or not re.search(r"\d", cleaned):
            return None
        if not re.search(r"[+\-*/%]", cleaned):
            return None
        # Guard against leftover prose fragments (words became empty runs).
        if re.search(r"[a-z]", cleaned):
            return None
        return cleaned

    def _safe_eval(self, expr: str) -> float:
        node = ast.parse(expr, mode="eval").body
        return self._eval_node(node)

    def _eval_node(self, node: ast.AST) -> float:
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(
                node.value, (int, float)
            ):
                raise ValueError("unsupported constant")
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            left = self._eval_node(node.left)
            right = self._eval_node(node.right)
            # Guard against absurd exponents that could hang the process.
            if isinstance(node.op, ast.Pow) and abs(right) > 1000:
                raise ValueError("exponent too large")
            return _OPS[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](self._eval_node(node.operand))
        raise ValueError("unsupported expression")

    @staticmethod
    def _format(value: float) -> str:
        # Show integers without a trailing ".0"; round long decimals.
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        if isinstance(value, float):
            return str(round(value, 6))
        return str(value)

    # ------------------------------------------------------------------
    # Word-problem path
    # ------------------------------------------------------------------

    async def _ai_solve(self, text: str, context: SkillContext) -> SkillResponse:
        if self._ai_provider is None:
            return SkillResponse(
                text=(
                    "I can only do direct calculations right now. Try phrasing "
                    "it like 'what is 45 times 12'."
                )
            )
        prompt = (
            "Solve this math problem and give the answer. Explain the steps "
            "very briefly and simply, as if to a student, in a way that reads "
            "well aloud (no equations with lots of symbols). Reply in the user's "
            f"language.\n\nProblem: {text}"
        )
        try:
            reply = await self._ai_provider.generate_text(
                prompt=prompt,
                conversation_history=context.conversation_history,
            )
            reply = (reply or "").strip()
            return SkillResponse(
                text=reply or "I couldn't work that one out. Could you rephrase it?"
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Math AI solve failed: %s", exc)
            return SkillResponse(
                text="I had trouble solving that. Could you say it again?"
            )
