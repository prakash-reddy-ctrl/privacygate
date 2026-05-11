"""
PrivacyGateAI - Core PII Detection & Masking Engine
Pure regex + pattern-based approach. Zero external ML dependencies.
Fast, deterministic, and production-safe.

In production you can layer in ML models (AWS Comprehend, Azure Text Analytics,
or fine-tuned NER) on top of this base for higher recall on implicit PII.
"""

import re
from dataclasses import dataclass
from typing import Any


# ── PII Pattern Registry ───────────────────────────────────────────────────

PATTERNS: list[tuple[str, str, float]] = [
    ("EMAIL_ADDRESS",    r"[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)+", 0.95),
    ("US_SSN",           r"\b\d{3}[- ]\d{2}[- ]\d{4}\b", 0.95),
    ("CREDIT_CARD",      r"\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|"
                         r"3[47][0-9]{13}|6011[0-9]{12})\b", 0.95),
    ("IP_ADDRESS",       r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}"
                         r"(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b", 0.90),
    ("IBAN_CODE",        r"\b[A-Z]{2}\d{2}[A-Z0-9]{4}\d{7}(?:[A-Z0-9]{0,16})?\b", 0.90),
    ("API_KEY",          r"\bsk[-_][a-zA-Z0-9]{16,}\b", 0.95),
    ("API_KEY",          r"\bpk[-_][a-zA-Z0-9]{16,}\b", 0.95),
    ("API_KEY",          r"Bearer\s+[a-zA-Z0-9\-_.]{20,}", 0.95),
    ("API_KEY",          r"(?:api[-_]?key|secret|token)\s*[:=]\s*['\"]?[a-zA-Z0-9\-_.]{16,}['\"]?", 0.85),
    ("FINANCIAL_AMOUNT", r"\$[\d,]+(?:\.\d{2})?(?:\s*(?:million|billion|thousand|[MBK]))?", 0.75),
    ("PHONE_NUMBER",     r"\+?1?\s*[-.]?\s*\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]\d{4}\b", 0.80),
    ("DATE_OF_BIRTH",    r"(?:DOB|Date of Birth|Born)[:\s]+\d{1,2}[/-]\d{1,2}[/-]\d{2,4}", 0.90),
    ("MEDICAL_ID",       r"(?:MRN|Medical Record)[:\s#]+[A-Z0-9]{6,12}", 0.90),
    ("URL_WITH_CREDS",   r"https?://[^:@\s]+:[^@\s]+@[^\s]+", 0.95),
]

_COMPILED: list[tuple[str, re.Pattern, float]] = [
    (entity_type, re.compile(pattern, re.IGNORECASE), score)
    for entity_type, pattern, score in PATTERNS
]


# ── Data Classes ───────────────────────────────────────────────────────────

@dataclass
class DetectedEntity:
    original: str
    placeholder: str
    entity_type: str
    confidence: float
    start: int = 0
    end: int = 0


@dataclass
class SanitizeResult:
    sanitized_text: str
    entity_map: dict[str, "DetectedEntity"]
    entity_count: int
    entity_types: list[str]


# ── Core Engine ────────────────────────────────────────────────────────────

class PrivacyEngine:
    """
    Detects PII, replaces with placeholders, and restores on demand.
    Thread-safe — no mutable state (session state lives in returned entity_map).
    """

    def sanitize(self, text: str, session_id: str | None = None) -> SanitizeResult:
        """Scan text for PII and replace with consistent placeholders."""
        matches: list[tuple[int, int, str, str, float]] = []

        for entity_type, pattern, score in _COMPILED:
            for m in pattern.finditer(text):
                matches.append((m.start(), m.end(), m.group(), entity_type, score))

        if not matches:
            return SanitizeResult(
                sanitized_text=text, entity_map={}, entity_count=0, entity_types=[]
            )

        # Sort; remove overlaps (keep highest-confidence span)
        matches.sort(key=lambda x: (x[0], -x[4]))
        non_overlapping: list[tuple[int, int, str, str, float]] = []
        last_end = -1
        for m in matches:
            if m[0] >= last_end:
                non_overlapping.append(m)
                last_end = m[1]

        entity_map: dict[str, DetectedEntity] = {}
        value_to_placeholder: dict[str, str] = {}
        type_counters: dict[str, int] = {}
        parts: list[str] = []
        cursor = 0

        for start, end, original, entity_type, score in non_overlapping:
            parts.append(text[cursor:start])

            if original in value_to_placeholder:
                placeholder = value_to_placeholder[original]
            else:
                type_counters[entity_type] = type_counters.get(entity_type, 0) + 1
                placeholder = f"[{entity_type}_{type_counters[entity_type]}]"
                entity_map[placeholder] = DetectedEntity(
                    original=original, placeholder=placeholder,
                    entity_type=entity_type, confidence=score,
                    start=start, end=end,
                )
                value_to_placeholder[original] = placeholder

            parts.append(placeholder)
            cursor = end

        parts.append(text[cursor:])

        return SanitizeResult(
            sanitized_text="".join(parts),
            entity_map=entity_map,
            entity_count=len(entity_map),
            entity_types=list({e.entity_type for e in entity_map.values()}),
        )

    def restore(self, text: str, entity_map: dict[str, "DetectedEntity"]) -> str:
        """Restore placeholder tokens back to original values."""
        restored = text
        for placeholder, entity in entity_map.items():
            restored = restored.replace(placeholder, entity.original)
        return restored

    def audit_entry(self, result: SanitizeResult, session_id: str) -> dict[str, Any]:
        """Compliance-safe audit record — never logs original values."""
        return {
            "session_id": session_id,
            "entity_count": result.entity_count,
            "entity_types": result.entity_types,
            "entities": [
                {"placeholder": k, "type": v.entity_type, "confidence": round(v.confidence, 3)}
                for k, v in result.entity_map.items()
            ],
        }
