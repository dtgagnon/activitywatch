"""
Data models for the ActivityWatch LLM Worker.

Defines the schemas for categorized events and classification results.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, Literal, Optional


class Category(str, Enum):
    """Top-level categories for events."""

    CLIENT_WORK = "Client Work"
    HOBBY = "Hobby"
    ENTERTAINMENT = "Entertainment"
    UNCATEGORIZED = "Uncategorized"


class ClientSubcategory(str, Enum):
    """Subcategories for Client Work."""

    STS_CONTRACT = "STS Contract"
    QUALIRA_AWP = "Qualira (AWP)"
    XODUS_MEDICAL = "Xodus Medical"
    HAND_CONSULTANTS = "Hand Consultants"
    DTG_ENGINEERING = "DTG Engineering"
    DOCS_SPREADSHEETS = "Docs & Spreadsheets"
    CODE_IDE = "Code & IDE"
    COMMS = "Comms"
    ADMIN_BILLING = "Admin & Billing"


class HobbySubcategory(str, Enum):
    """Subcategories for Hobby."""

    PROGRAMMING = "Programming"
    MACHINING_CAD = "Machining & CAD"
    VIDEO_LEARNING = "Video-Learning"
    COMMS = "Comms"


class EntertainmentSubcategory(str, Enum):
    """Subcategories for Entertainment."""

    GAMING = "Gaming"
    VIDEO = "Video"
    SOCIAL = "Social"


ClassificationSource = Literal["llm", "rule", "cache"]


@dataclass
class EnrichedFeatures:
    """Enriched metadata extracted from raw events."""

    app: str
    title: str
    domain: Optional[str] = None
    path_root: Optional[str] = None
    url: Optional[str] = None


@dataclass
class CategoryResult:
    """Result of categorization process."""

    category: Category
    subcategory: Optional[str] = None
    client: Optional[str] = None
    confidence: float = 0.0
    source: ClassificationSource = "rule"
    rationale: str = ""

    def __post_init__(self):
        """Validate the result."""
        if self.confidence < 0.0 or self.confidence > 1.0:
            raise ValueError(f"Confidence must be between 0.0 and 1.0, got {self.confidence}")
        if self.rationale and len(self.rationale) > 140:
            raise ValueError(f"Rationale must be ≤140 chars, got {len(self.rationale)}")


@dataclass
class CategorizedEvent:
    """
    Schema for events in the aw-llm-categories bucket.

    Matches the output bucket schema defined in goal.md:
    {
      "timestamp": "<from original>",
      "duration": <from original>,
      "data": {
        "category": "Client Work|Hobby|Entertainment|Uncategorized",
        "subcategory": "<one of allowed or null>",
        "client": "<client name or null>",
        "confidence": 0.00-1.00,
        "source": "llm|rule|cache",
        "rationale": "≤140 chars",
        "features": { "app": "...", "title": "...", "domain": "..." }
      }
    }
    """

    timestamp: datetime
    duration: timedelta
    category: Category
    subcategory: Optional[str]
    client: Optional[str]
    confidence: float
    source: ClassificationSource
    rationale: str
    features: EnrichedFeatures

    def to_aw_event_data(self) -> Dict[str, Any]:
        """
        Convert to ActivityWatch event data dict.

        Returns:
            Dict suitable for insertion into AW bucket
        """
        return {
            "timestamp": self.timestamp.isoformat(),
            "duration": self.duration.total_seconds(),
            "data": {
                "category": self.category.value,
                "subcategory": self.subcategory,
                "client": self.client,
                "confidence": self.confidence,
                "source": self.source,
                "rationale": self.rationale,
                "features": {
                    "app": self.features.app,
                    "title": self.features.title,
                    "domain": self.features.domain,
                    "path_root": self.features.path_root,
                },
            },
        }

    @classmethod
    def from_result(
        cls,
        timestamp: datetime,
        duration: timedelta,
        result: CategoryResult,
        features: EnrichedFeatures,
    ) -> "CategorizedEvent":
        """
        Create a CategorizedEvent from classification result and features.

        Args:
            timestamp: Event timestamp
            duration: Event duration
            result: Classification result
            features: Enriched features

        Returns:
            CategorizedEvent instance
        """
        return cls(
            timestamp=timestamp,
            duration=duration,
            category=result.category,
            subcategory=result.subcategory,
            client=result.client,
            confidence=result.confidence,
            source=result.source,
            rationale=result.rationale,
            features=features,
        )


@dataclass
class CacheEntry:
    """Cache entry for storing classification results."""

    cache_key: str
    category: str
    subcategory: Optional[str]
    client: Optional[str]
    confidence: float
    source: str
    rationale: str
    created_at: datetime
    last_used: datetime
    use_count: int = 0

    def to_result(self) -> CategoryResult:
        """Convert cache entry back to CategoryResult."""
        return CategoryResult(
            category=Category(self.category),
            subcategory=self.subcategory,
            client=self.client,
            confidence=self.confidence,
            source="cache",  # Override source to indicate cache hit
            rationale=self.rationale,
        )
