"""Rule-based fallback classifier.

Provides deterministic categorization when LLM confidence is too low or the
LLM is unavailable.
"""

from __future__ import annotations

from typing import Iterable, Optional, Set

from aw_llm_worker.config import Config
from aw_llm_worker.models import (
    Category,
    CategoryResult,
    EnrichedFeatures,
    EntertainmentSubcategory,
    HobbySubcategory,
)


def _normalize(value: Optional[str]) -> str:
    """Normalize a string for case-insensitive comparisons."""

    return (value or "").strip().lower()


def _normalized_set(values: Iterable[str]) -> Set[str]:
    """Return a set of normalized strings ignoring empty entries."""

    return {item.strip().lower() for item in values if item}


def _matches_domain(domain: str, candidates: Set[str]) -> bool:
    """Check whether the given domain matches any candidate domain."""

    if not domain or not candidates:
        return False

    normalized = _normalize(domain)
    stripped = normalized[4:] if normalized.startswith("www.") else normalized

    if stripped in candidates or normalized in candidates:
        return True

    return any(
        stripped.endswith(f".{candidate}") or normalized.endswith(f".{candidate}")
        for candidate in candidates
    )


def _contains_keyword(text: str, keywords: Iterable[str]) -> bool:
    """Determine if any keyword appears in the provided text."""

    if not text:
        return False

    lowered_text = text.lower()
    return any(keyword.lower() in lowered_text for keyword in keywords if keyword)


def classify_by_rules(features: EnrichedFeatures, config: Config) -> CategoryResult:
    """Classify enriched features using deterministic rules.

    Args:
        features: Redacted event metadata.
        config: Application configuration containing rule definitions.

    Returns:
        CategoryResult produced by evaluating the configured rules in priority order.
    """

    rules = config.rules or {}

    video_domains = _normalized_set(rules.get("video_domains", []))
    social_domains = _normalized_set(rules.get("social_domains", []))
    gaming_keywords = rules.get("gaming_keywords", [])
    machining_keywords = rules.get("machining_keywords", [])
    hobby_prog_keywords = rules.get("hobby_prog_keywords", [])

    domain = features.domain or ""
    title = features.title or ""

    if _matches_domain(domain, video_domains):
        return CategoryResult(
            category=Category.ENTERTAINMENT,
            subcategory=EntertainmentSubcategory.VIDEO.value,
            confidence=0.60,
            source="rule",
            rationale="Video domain match",
        )

    if _matches_domain(domain, social_domains):
        return CategoryResult(
            category=Category.ENTERTAINMENT,
            subcategory=EntertainmentSubcategory.SOCIAL.value,
            confidence=0.60,
            source="rule",
            rationale="Social domain match",
        )

    if _contains_keyword(title, gaming_keywords):
        return CategoryResult(
            category=Category.ENTERTAINMENT,
            subcategory=EntertainmentSubcategory.GAMING.value,
            confidence=0.55,
            source="rule",
            rationale="Gaming keyword in title",
        )

    if _contains_keyword(title, machining_keywords):
        return CategoryResult(
            category=Category.HOBBY,
            subcategory=HobbySubcategory.MACHINING_CAD.value,
            confidence=0.55,
            source="rule",
            rationale="Machining keyword in title",
        )

    if _contains_keyword(title, hobby_prog_keywords) or _contains_keyword(
        domain, hobby_prog_keywords
    ):
        return CategoryResult(
            category=Category.HOBBY,
            subcategory=HobbySubcategory.PROGRAMMING.value,
            confidence=0.50,
            source="rule",
            rationale="Programming keyword match",
        )

    return CategoryResult(
        category=Category.UNCATEGORIZED,
        subcategory=None,
        confidence=0.30,
        source="rule",
        rationale="No rule matched",
    )
