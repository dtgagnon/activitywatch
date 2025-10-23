"""
Strong hint matching for high-confidence client identification.

Bypasses LLM when domain/path/keyword matches indicate clear client work.
"""

import logging
from typing import Dict, List, Optional, Tuple

from aw_llm_worker.config import Config
from aw_llm_worker.models import Category, CategoryResult, ClientSubcategory, EnrichedFeatures

logger = logging.getLogger(__name__)


def check_domain_match(
    domain: Optional[str],
    client_domains: List[str],
) -> bool:
    """
    Check if domain matches any client domain.

    Args:
        domain: Domain to check
        client_domains: List of client domains

    Returns:
        True if match found
    """
    if not domain:
        return False

    domain_lower = domain.lower()
    for client_domain in client_domains:
        if client_domain.lower() in domain_lower:
            return True
    return False


def check_keyword_match(
    text: str,
    keywords: List[str],
) -> bool:
    """
    Check if any keyword appears in text (case-insensitive).

    Args:
        text: Text to search
        keywords: List of keywords

    Returns:
        True if any keyword found
    """
    text_lower = text.lower()
    for keyword in keywords:
        if keyword.lower() in text_lower:
            return True
    return False


def check_path_match(
    path: Optional[str],
    client_paths: List[str],
) -> bool:
    """
    Check if path starts with any client path prefix.

    Args:
        path: Path to check
        client_paths: List of client path prefixes

    Returns:
        True if match found
    """
    if not path:
        return False

    for client_path in client_paths:
        if path.startswith(client_path):
            return True
    return False


def match_client(
    features: EnrichedFeatures,
    config: Config,
) -> Optional[Tuple[str, str]]:
    """
    Attempt to match features to a specific client.

    Returns tuple of (client_name, match_reason) if confident match found.

    Args:
        features: Enriched features
        config: Configuration with client definitions

    Returns:
        (client_name, reason) tuple if match found, None otherwise
    """
    clients = config.clients

    for client_name, client_config in clients.items():
        domains = client_config.get("domains", [])
        keywords = client_config.get("keywords", [])
        paths = client_config.get("paths", [])

        # Check domain match (highest priority)
        if check_domain_match(features.domain, domains):
            return (client_name, f"Domain match: {features.domain}")

        # Check path match (second priority, strong signal for local work)
        if check_path_match(features.path_root, paths):
            return (client_name, f"Path match: {features.path_root}")

        # Check keyword in title (lower priority, needs more context)
        # Only consider if multiple keywords or keyword + domain partial match
        if check_keyword_match(features.title, keywords):
            # Additional check: if domain is also somewhat related
            domain_related = (
                features.domain
                and any(
                    part in features.domain.lower()
                    for part in client_name.lower().split()
                )
            )
            if domain_related:
                return (client_name, f"Keywords + domain context")

    return None


def classify_strong_hint(
    features: EnrichedFeatures,
    config: Config,
) -> Optional[CategoryResult]:
    """
    Attempt high-confidence classification via strong hints.

    Returns CategoryResult if confident client match found, bypassing LLM.
    Sets confidence=0.98 and source="rule".

    Args:
        features: Enriched features
        config: Configuration

    Returns:
        CategoryResult if strong match found, None otherwise
    """
    match = match_client(features, config)

    if match:
        client_name, reason = match
        logger.info(f"Strong hint match: {client_name} - {reason}")

        # Determine subcategory based on app/domain/title hints
        subcategory = _infer_subcategory(features, client_name)

        return CategoryResult(
            category=Category.CLIENT_WORK,
            subcategory=subcategory,
            client=client_name,
            confidence=0.98,
            source="rule",
            rationale=f"Strong client match: {reason}",
        )

    return None


def _infer_subcategory(
    features: EnrichedFeatures,
    client_name: str,
) -> str:
    """
    Infer appropriate subcategory for client work.

    Uses heuristics based on app type and content.

    Args:
        features: Enriched features
        client_name: Matched client name

    Returns:
        Subcategory string (one of ClientSubcategory values or client name)
    """
    title_lower = features.title.lower()
    app_lower = features.app.lower()

    # Check for docs/spreadsheets
    if any(
        keyword in title_lower or keyword in (features.domain or "")
        for keyword in ["doc", "sheet", "excel", "word", "slides", "presentation"]
    ):
        return ClientSubcategory.DOCS_SPREADSHEETS.value

    # Check for code/IDE
    if any(
        keyword in app_lower
        for keyword in ["code", "vim", "emacs", "ide", "studio", "intellij"]
    ):
        return ClientSubcategory.CODE_IDE.value

    # Check for communication
    if any(
        keyword in app_lower or keyword in title_lower
        for keyword in ["mail", "slack", "teams", "zoom", "meet", "calendar"]
    ):
        return ClientSubcategory.COMMS.value

    # Check for admin/billing keywords
    if any(
        keyword in title_lower
        for keyword in ["invoice", "billing", "payment", "quickbooks", "accounting"]
    ):
        return ClientSubcategory.ADMIN_BILLING.value

    # Default to specific client name (e.g., "STS Contract", "Qualira (AWP)")
    # Check if client_name matches one of our defined subcategories
    for subcategory in ClientSubcategory:
        if subcategory.value == client_name:
            return subcategory.value

    # If client name doesn't match predefined subcategories, return it directly
    return client_name
