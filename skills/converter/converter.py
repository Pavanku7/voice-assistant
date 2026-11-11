"""
ConverterSkill — unit and currency conversion.

Units (length, weight, temperature, volume) are converted locally with a small
factor table — instant, offline, exact. Currency uses the free, key-free
``open.er-api.com`` exchange-rate endpoint via ``asyncio.to_thread``.

If the utterance can't be parsed into "<amount> <from> to <to>", the skill asks
the AI provider to handle it, so unusual phrasings still get an answer.

Requirements addressed: 7.2, 7.5, 7.6, 7.8
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import urllib.request
from typing import Any, Optional, Tuple

from meryna_platform.models import SkillContext, SkillResponse
from skills.base import Skill

logger = logging.getLogger("meryna.skills.converter")

_RATE_URL = "https://open.er-api.com/v6/latest/"
_TIMEOUT = 8

# Length/weight/volume: factor to a base unit. Grouped by dimension so we only
# convert within the same dimension.
_LINEAR = {
    # length -> metres
    "length": {
        "mm": 0.001, "millimeter": 0.001, "millimetre": 0.001, "millimeters": 0.001,
        "cm": 0.01, "centimeter": 0.01, "centimetre": 0.01, "centimeters": 0.01,
        "m": 1.0, "meter": 1.0, "metre": 1.0, "meters": 1.0, "metres": 1.0,
        "km": 1000.0, "kilometer": 1000.0, "kilometre": 1000.0, "kilometers": 1000.0, "kilometres": 1000.0,
        "in": 0.0254, "inch": 0.0254, "inches": 0.0254,
        "ft": 0.3048, "foot": 0.3048, "feet": 0.3048,
        "yd": 0.9144, "yard": 0.9144, "yards": 0.9144,
        "mi": 1609.344, "mile": 1609.344, "miles": 1609.344,
    },
    # weight -> grams
    "weight": {
        "mg": 0.001, "milligram": 0.001, "milligrams": 0.001,
        "g": 1.0, "gram": 1.0, "grams": 1.0,
        "kg": 1000.0, "kilogram": 1000.0, "kilograms": 1000.0, "kilo": 1000.0, "kilos": 1000.0,
        "oz": 28.3495, "ounce": 28.3495, "ounces": 28.3495,
        "lb": 453.592, "lbs": 453.592, "pound": 453.592, "pounds": 453.592,
        "ton": 1_000_000.0, "tonne": 1_000_000.0, "tons": 1_000_000.0, "tonnes": 1_000_000.0,
    },
    # volume -> millilitres
    "volume": {
        "ml": 1.0, "milliliter": 1.0, "millilitre": 1.0, "milliliters": 1.0,
        "l": 1000.0, "liter": 1000.0, "litre": 1000.0, "liters": 1000.0, "litres": 1000.0,
        "cup": 240.0, "cups": 240.0,
        "tbsp": 15.0, "tablespoon": 15.0, "tablespoons": 15.0,
        "tsp": 5.0, "teaspoon": 5.0, "teaspoons": 5.0,
        "gal": 3785.41, "gallon": 3785.41, "gallons": 3785.41,
        "pint": 473.176, "pints": 473.176,
    },
}

# Currency words/symbols -> ISO code.
_CURRENCIES = {
    "dollar": "USD", "dollars": "USD", "usd": "USD", "$": "USD",
    "rupee": "INR", "rupees": "INR", "inr": "INR", "rs": "INR", "₹": "INR",
    "euro": "EUR", "euros": "EUR", "eur": "EUR", "€": "EUR",
    "pound": "GBP", "pounds": "GBP", "gbp": "GBP", "£": "GBP",
    "yen": "JPY", "jpy": "JPY", "¥": "JPY",
    "nepali rupee": "NPR", "npr": "NPR",
    "pakistani rupee": "PKR", "pkr": "PKR",
    "australian dollar": "AUD", "aud": "AUD",
    "canadian dollar": "CAD", "cad": "CAD",
}


class ConverterSkill(Skill):
    """Converts units and currencies."""

    def __init__(self, ai_provider: Any) -> None:
        super().__init__(ai_provider)

    @property
    def name(self) -> str:
        return "converter-skill"

    @property
    def version(self) -> str:
        return "1.0.0"

    async def execute(self, context: SkillContext) -> SkillResponse:
        text = (context.utterance or "").strip()
        parsed = self._parse(text)
        if parsed is None:
            return await self._ai_fallback(text, context)

        amount, src, dst = parsed

        # Temperature is special (offsets, not just factors).
        temp = self._convert_temperature(amount, src, dst)
        if temp is not None:
            return SkillResponse(text=temp)

        # Linear units (length/weight/volume).
        linear = self._convert_linear(amount, src, dst)
        if linear is not None:
            return SkillResponse(text=linear)

        # Currency.
        src_cur = _CURRENCIES.get(src)
        dst_cur = _CURRENCIES.get(dst)
        if src_cur and dst_cur:
            try:
                out = await asyncio.to_thread(
                    self._convert_currency, amount, src_cur, dst_cur
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Currency conversion failed: %s", exc)
                out = None
            if out is not None:
                return SkillResponse(text=out)
            return SkillResponse(
                text=(
                    "I couldn't fetch live exchange rates just now. "
                    "Please try again in a moment."
                )
            )

        # Parsed a shape but units didn't match a known dimension.
        return await self._ai_fallback(text, context)

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse(text: str) -> Optional[Tuple[float, str, str]]:
        """Extract (amount, from_unit, to_unit) from the utterance, or None."""
        s = text.lower().strip().rstrip("?.!")
        # "how many X is/are N Y"  -> N Y to X
        m = re.search(
            r"how many\s+([a-z$₹€£¥]+)\s+(?:is|are)\s+(\d+(?:\.\d+)?)\s+([a-z$₹€£¥]+)",
            s,
        )
        if m:
            return float(m.group(2)), m.group(3), m.group(1)

        # "convert N X to/into Y"  /  "N X in Y"  /  "what is N X in Y"
        m = re.search(
            r"(\d+(?:\.\d+)?)\s*([a-z$₹€£¥]+)\s+(?:to|into|in)\s+([a-z$₹€£¥]+)",
            s,
        )
        if m:
            return float(m.group(1)), m.group(2), m.group(3)
        return None

    # ------------------------------------------------------------------
    # Conversions
    # ------------------------------------------------------------------

    @staticmethod
    def _dimension_of(unit: str) -> Optional[str]:
        for dim, table in _LINEAR.items():
            if unit in table:
                return dim
        return None

    def _convert_linear(self, amount: float, src: str, dst: str) -> Optional[str]:
        dim_src = self._dimension_of(src)
        dim_dst = self._dimension_of(dst)
        if dim_src is None or dim_dst is None or dim_src != dim_dst:
            return None
        table = _LINEAR[dim_src]
        base = amount * table[src]
        result = base / table[dst]
        return f"{self._fmt(amount)} {src} is {self._fmt(result)} {dst}."

    @staticmethod
    def _convert_temperature(amount: float, src: str, dst: str) -> Optional[str]:
        temp_words = {
            "c": "C", "celsius": "C", "centigrade": "C",
            "f": "F", "fahrenheit": "F",
            "k": "K", "kelvin": "K",
        }
        s = temp_words.get(src)
        d = temp_words.get(dst)
        if not s or not d:
            return None
        # To Celsius first.
        if s == "C":
            c = amount
        elif s == "F":
            c = (amount - 32) * 5 / 9
        else:  # K
            c = amount - 273.15
        # From Celsius to target.
        if d == "C":
            out = c
        elif d == "F":
            out = c * 9 / 5 + 32
        else:
            out = c + 273.15
        names = {"C": "degrees Celsius", "F": "degrees Fahrenheit", "K": "Kelvin"}
        return (
            f"{ConverterSkill._fmt(amount)} {names[s]} is "
            f"{ConverterSkill._fmt(round(out, 2))} {names[d]}."
        )

    def _convert_currency(self, amount: float, src: str, dst: str) -> Optional[str]:
        url = _RATE_URL + src
        req = urllib.request.Request(url, headers={"User-Agent": "Meryna/1.0"})
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        rates = data.get("rates") or {}
        rate = rates.get(dst)
        if rate is None:
            return None
        result = amount * float(rate)
        return (
            f"{self._fmt(amount)} {src} is about {self._fmt(round(result, 2))} {dst}."
        )

    async def _ai_fallback(self, text: str, context: SkillContext) -> SkillResponse:
        if self._ai_provider is None:
            return SkillResponse(
                text=(
                    "I couldn't understand that conversion. Try something like "
                    "'convert 10 kilometers to miles'."
                )
            )
        prompt = (
            "Do this unit or currency conversion and give a short spoken answer "
            "with the result. Reply in the user's language.\n\n"
            f"Request: {text}"
        )
        try:
            reply = await self._ai_provider.generate_text(
                prompt=prompt,
                conversation_history=context.conversation_history,
            )
            reply = (reply or "").strip()
            return SkillResponse(
                text=reply or "I couldn't work out that conversion."
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Converter AI fallback failed: %s", exc)
            return SkillResponse(text="I couldn't work out that conversion.")

    @staticmethod
    def _fmt(value: float) -> str:
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(round(value, 4)) if isinstance(value, float) else str(value)
