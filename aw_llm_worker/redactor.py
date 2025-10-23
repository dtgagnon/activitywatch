"""
PII redaction for event data before LLM processing.

Strips emails, query strings, long IDs, and other sensitive data.
"""

import re
from typing import Optional
from urllib.parse import urlparse, urlunparse

from aw_llm_worker.models import EnrichedFeatures


# Regex patterns for PII detection
EMAIL_PATTERN = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b')
LONG_ID_PATTERN = re.compile(r'\b[a-f0-9]{32,}\b|\b[A-Za-z0-9_-]{20,}\b')
UUID_PATTERN = re.compile(
    r'\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b'
)
# Common tokens and session IDs in URLs
TOKEN_PATTERNS = [
    r'[?&](token|access_token|auth|jwt|session|sid)=[^&]+',
    r'[?&](api_key|apikey|key)=[^&]+',
]


def strip_email(text: str) -> str:
    """
    Remove email addresses from text.

    Args:
        text: Input text

    Returns:
        Text with emails replaced by [EMAIL]
    """
    return EMAIL_PATTERN.sub('[EMAIL]', text)


def strip_long_ids(text: str) -> str:
    """
    Remove long hexadecimal IDs and random strings.

    Args:
        text: Input text

    Returns:
        Text with IDs replaced by [ID]
    """
    text = UUID_PATTERN.sub('[UUID]', text)
    text = LONG_ID_PATTERN.sub('[ID]', text)
    return text


def strip_url_params(url: Optional[str]) -> Optional[str]:
    """
    Remove query parameters and fragments from URL.

    Keeps only scheme, netloc, and path. Removes query strings that may
    contain tokens, session IDs, or tracking parameters.

    Args:
        url: Full URL with potential query params

    Returns:
        URL without query params/fragments, or None if input was None
    """
    if not url:
        return None

    try:
        parsed = urlparse(url)
        # Keep only scheme, netloc, and path
        clean_url = urlunparse((
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            '',  # params
            '',  # query
            '',  # fragment
        ))
        return clean_url
    except Exception:
        # If URL parsing fails, return None to be safe
        return None


def truncate_title(title: str, max_length: int = 120) -> str:
    """
    Truncate title to maximum length.

    Args:
        title: Original title
        max_length: Maximum length (default 120)

    Returns:
        Truncated title with '...' appended if shortened
    """
    if len(title) <= max_length:
        return title
    return title[:max_length - 3] + '...'


def redact_features(features: EnrichedFeatures) -> EnrichedFeatures:
    """
    Redact PII from enriched features.

    Applies all redaction rules:
    - Strip emails from title
    - Strip long IDs from title
    - Remove URL query parameters
    - Truncate title to 120 chars

    Args:
        features: Original enriched features

    Returns:
        New EnrichedFeatures with redacted data
    """
    # Redact title
    title = features.title
    title = strip_email(title)
    title = strip_long_ids(title)
    title = truncate_title(title)

    # Redact URL
    url = strip_url_params(features.url)

    # Domain should already be clean (no query params)
    # path_root may contain sensitive info, but we keep it for client matching

    return EnrichedFeatures(
        app=features.app,
        title=title,
        domain=features.domain,
        path_root=features.path_root,
        url=url,
    )


def prepare_for_llm(features: EnrichedFeatures) -> dict:
    """
    Prepare redacted features for LLM input.

    Creates a minimal dict suitable for LLM classification with
    only essential, non-sensitive fields.

    Args:
        features: Redacted enriched features

    Returns:
        Dict with app, domain, title, path_root for LLM
    """
    return {
        "app": features.app,
        "domain": features.domain,
        "title": features.title,
        "path_root": features.path_root,
    }
