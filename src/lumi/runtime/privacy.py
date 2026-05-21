"""PII masking + pseudonymization for cloud LLM calls.

The promise: nothing identifying leaves the device. Before any HTTP request
to Anthropic/OpenAI/Gemini, transcripts pass through `Pseudonymizer.mask()`:
PII patterns are replaced with stable pseudonyms (`<PERSON_1>`, `<EMAIL_1>`,
…) and the mapping is kept in memory. When the cloud reply comes back,
`unmask()` swaps the pseudonyms back to real values so the user never sees
the placeholder versions.

What we mask:
  - Email addresses
  - Phone numbers (US/intl common formats)
  - Credit card numbers (Luhn-checked to avoid false positives)
  - IPv4 addresses
  - US Social Security numbers (NNN-NN-NNNN)
  - US ZIP codes (5 and 9-digit)
  - API-key-shaped strings (sk-…, sk-ant-…, ghp_…, AIza…)
  - The user's name (from onboarding) and any explicit names they've
    added to the personal-vocabulary list
  - Generic person names via optional Presidio NER (falls back to regex-only
    when presidio isn't installed)

Pseudonyms are stable within a single mapping: every occurrence of the
same email gets the same `<EMAIL_1>` so the cloud LLM can refer back to it
coherently. Across sessions the mapping resets — fresh pseudonyms each turn.

The audit log stores the MASKED transcript too, so even our own on-disk logs
never keep raw PII.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

from ..log import get_logger

log = get_logger(__name__)


# ── Regex patterns ──────────────────────────────────────────────────────────


_EMAIL_RE = re.compile(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b")

# Loose phone — matches US, common intl. Avoids matching short digit runs.
_PHONE_RE = re.compile(
    r"(?<!\d)"
    r"(?:\+?\d{1,3}[-.\s]?)?"          # optional country
    r"(?:\(?\d{2,4}\)?[-.\s]?)?"       # optional area
    r"\d{3}[-.\s]?\d{4}"               # last 7
    r"(?!\d)"
)

# US SSN — strict, 3-2-4 with dashes only.
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")

# US ZIP — 5 or 5-4.
_ZIP_RE = re.compile(r"(?<!\d)\d{5}(?:-\d{4})?(?!\d)")

# IPv4.
_IPV4_RE = re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b")

# Credit card — 13-19 digits with optional grouping. Filtered through Luhn
# after the regex match to avoid masking timestamps, IDs, etc.
_CC_RE = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")

# API-key shaped strings — common provider prefixes.
_APIKEY_RE = re.compile(
    r"\b(?:"
    r"sk-(?:ant-)?[A-Za-z0-9_-]{20,}"            # OpenAI / Anthropic
    r"|ghp_[A-Za-z0-9]{20,}"                     # GitHub PAT
    r"|gho_[A-Za-z0-9]{20,}"                     # GitHub OAuth
    r"|AIza[A-Za-z0-9_-]{30,}"                   # Google
    r"|xox[abprs]-[A-Za-z0-9-]{20,}"             # Slack
    r")\b"
)


def _luhn_ok(s: str) -> bool:
    digits = [int(c) for c in s if c.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


# ── Pseudonymizer ───────────────────────────────────────────────────────────


@dataclass
class Pseudonymizer:
    """Stable mask/unmask for a single conversation context.

    `extra_names` are user-provided strings to also mask as PERSON tokens —
    typically the owner_name from onboarding plus any names they've added
    to a personal-vocabulary list later.
    """

    extra_names: list[str] = field(default_factory=list)
    use_presidio: bool = True            # try Presidio NER if available
    mapping: dict[str, str] = field(default_factory=dict)   # pseudonym → real value
    _reverse: dict[str, str] = field(default_factory=dict)  # real → pseudonym
    _counters: dict[str, int] = field(default_factory=dict)

    # ── public ────────────────────────────────────────────────────────────

    def mask(self, text: str) -> str:
        """Return `text` with PII replaced by stable pseudonyms.

        Updates `self.mapping` (pseudonym → real) so later cloud replies
        referencing pseudonyms can be unmasked. Idempotent for the same
        Pseudonymizer instance — re-masking gives the same pseudonyms.
        """
        if not text:
            return text

        # API keys first — these can otherwise be partially eaten by other patterns
        text = _APIKEY_RE.sub(lambda m: self._token("API_KEY", m.group(0)), text)
        text = _EMAIL_RE.sub(lambda m: self._token("EMAIL", m.group(0)), text)
        text = _SSN_RE.sub(lambda m: self._token("SSN", m.group(0)), text)
        text = _IPV4_RE.sub(lambda m: self._token("IP", m.group(0)), text)
        text = _ZIP_RE.sub(lambda m: self._token("ZIP", m.group(0)), text)

        # Credit cards: regex finds candidates, Luhn filters them.
        def _cc_sub(m: re.Match) -> str:
            return self._token("CARD", m.group(0)) if _luhn_ok(m.group(0)) else m.group(0)
        text = _CC_RE.sub(_cc_sub, text)

        # Phones — after CC because they can overlap on raw digit strings.
        def _phone_sub(m: re.Match) -> str:
            # Avoid double-replacing something we already turned into <…_N>
            return self._token("PHONE", m.group(0)) if "<" not in m.group(0) else m.group(0)
        text = _PHONE_RE.sub(_phone_sub, text)

        # Names: explicit user-provided names (longest first to avoid partial matches),
        # then optional Presidio NER for general person detection.
        for name in sorted(self.extra_names, key=len, reverse=True):
            if not name or len(name) < 2:
                continue
            pattern = re.compile(rf"\b{re.escape(name)}\b", flags=re.IGNORECASE)
            text = pattern.sub(lambda _m: self._token("PERSON", name), text)

        if self.use_presidio:
            text = self._mask_with_presidio(text)

        return text

    def unmask(self, text: str) -> str:
        """Swap pseudonyms back to real values in `text`. Safe for partial
        matches — only replaces tokens that exist in the mapping."""
        if not text or not self.mapping:
            return text
        # Sort longest-first so `<EMAIL_10>` is replaced before `<EMAIL_1>`.
        for pseudonym in sorted(self.mapping, key=len, reverse=True):
            text = text.replace(pseudonym, self.mapping[pseudonym])
        return text

    def reset(self) -> None:
        self.mapping.clear()
        self._reverse.clear()
        self._counters.clear()

    # ── internals ─────────────────────────────────────────────────────────

    def _token(self, kind: str, value: str) -> str:
        """Return a stable pseudonym for `value`. Same value → same pseudonym."""
        if value in self._reverse:
            return self._reverse[value]
        self._counters[kind] = self._counters.get(kind, 0) + 1
        pseudonym = f"<{kind}_{self._counters[kind]}>"
        self.mapping[pseudonym] = value
        self._reverse[value] = pseudonym
        return pseudonym

    def _mask_with_presidio(self, text: str) -> str:
        """Optional NER-based name masking. Silent no-op if Presidio missing."""
        try:
            from presidio_analyzer import AnalyzerEngine  # noqa: PLC0415

            analyzer = _get_presidio_analyzer()
            if analyzer is None:
                return text
            results = analyzer.analyze(text=text, entities=["PERSON"], language="en")
            # Apply replacements right-to-left so earlier indices stay valid.
            for r in sorted(results, key=lambda r: r.start, reverse=True):
                original = text[r.start:r.end]
                # Skip if it overlaps an existing pseudonym placeholder
                if "<" in original or original in self._reverse:
                    continue
                pseudonym = self._token("PERSON", original)
                text = text[:r.start] + pseudonym + text[r.end:]
        except ImportError:
            return text
        except Exception as exc:
            log.debug("privacy.presidio_failed", error=str(exc))
        return text


# Lazy singleton — Presidio takes ~5s to spin up the spaCy model.
_presidio_analyzer = None


def _get_presidio_analyzer():
    global _presidio_analyzer
    if _presidio_analyzer is False:                  # cached "unavailable"
        return None
    if _presidio_analyzer is not None:
        return _presidio_analyzer
    try:
        from presidio_analyzer import AnalyzerEngine  # noqa: PLC0415

        _presidio_analyzer = AnalyzerEngine()
        log.info("privacy.presidio_ready")
        return _presidio_analyzer
    except Exception as exc:
        _presidio_analyzer = False
        log.info("privacy.presidio_unavailable", error=str(exc))
        return None


# ── Convenience helpers ─────────────────────────────────────────────────────


def mask_messages(
    messages: Iterable[dict], pseudonymizer: Pseudonymizer
) -> list[dict]:
    """Mask the `content` field of every message in a chat-format list."""
    out: list[dict] = []
    for m in messages:
        masked = dict(m)
        if isinstance(m.get("content"), str):
            masked["content"] = pseudonymizer.mask(m["content"])
        out.append(masked)
    return out
