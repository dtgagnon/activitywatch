"""Utilities for enriching ActivityWatch events with derived metadata."""

from __future__ import annotations

import logging
import re
from typing import Iterable, Mapping, Optional
from urllib.parse import urlparse

from aw_core.models import Event

from aw_llm_worker.models import EnrichedFeatures

logger = logging.getLogger(__name__)

TITLE_MAX_LENGTH = 120

_DOMAIN_PATTERN = re.compile(
    r"^(?:"  # start of domain
    r"(?:(?:xn--)?[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*"  # subdomains
    r"(?:xn--)?[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"  # root domain
    r"|localhost"  # or localhost
    r")$",
    re.IGNORECASE,
)

_WINDOWS_PATH_PATTERN = re.compile(
    r"(?P<path>[A-Za-z]:\\(?:[^<>:\"/\\|?*\n\r]+\\)*[^<>:\"/\\|?*\n\r]+)"
)
_UNIX_PATH_PATTERN = re.compile(
    r"(?P<path>(?:~|/)(?:[\w.\-+()\[\]{} ]+/)*[\w.\-+()\[\]{} ]+)"
)

_SEGMENT_DELIMITERS = (" — ", " – ", " - ", " | ", " · ")

_PATH_STRIP_CHARS = "\"')[]{}<>.,;"

_APP_ALIASES = {
    "zen": "Zen Browser",
    "zen browser": "Zen Browser",
    "zen.exe": "Zen Browser",
    "code": "VS Code",
    "code - insiders": "VS Code Insiders",
    "code-insiders": "VS Code Insiders",
    "visual studio code": "VS Code",
    "vscode": "VS Code",
    "electron": "Electron",
    "google chrome": "Google Chrome",
    "google-chrome": "Google Chrome",
    "chrome": "Google Chrome",
    "firefox": "Firefox",
    "mozilla firefox": "Firefox",
    "brave": "Brave",
    "chromium": "Chromium",
    "msedge": "Microsoft Edge",
    "microsoft edge": "Microsoft Edge",
    "safari": "Safari",
    "obsidian": "Obsidian",
    "slack": "Slack",
    "discord": "Discord",
    "wezterm": "WezTerm",
    "kitty": "Kitty",
    "alacritty": "Alacritty",
    "terminal": "Terminal",
}

_CODE_APPS = {
    "VS CODE",
    "VS CODE INSIDERS",
    "SUBLIME TEXT",
    "PYCHARM",
    "INTELLIJ IDEA",
    "WEBSTORM",
    "CLION",
    "RIDER",
    "GOLAND",
    "DATAGRIP",
    "ANDROID STUDIO",
    "NEOVIM",
    "VIM",
    "EMACS",
}


def extract_domain(url: Optional[str]) -> Optional[str]:
    """Extract the domain portion (netloc) from a URL.

    Args:
        url: Raw URL string, may be ``None`` or empty.

    Returns:
        Lowercase domain without ``www.`` prefix, or ``None`` if unavailable.
    """

    if not url:
        return None

    candidate = url.strip()
    if not candidate:
        return None

    try:
        parsed = urlparse(candidate)
    except ValueError:  # Malformed URL
        logger.debug("Failed to parse URL for domain extraction: %s", candidate)
        return None

    # Handle URLs missing a scheme but containing a domain
    if not parsed.netloc and parsed.path:
        try:
            parsed = urlparse(f"//{candidate}")
        except ValueError:
            logger.debug("Failed to parse schemeless URL for domain extraction: %s", candidate)
            return None

    netloc = parsed.netloc or ""
    if not netloc:
        return None

    # Remove potential credentials and ports
    host = netloc.split("@")[-1]
    host = host.split(":")[0]
    host = host.lower().strip()
    if host.startswith("www."):
        host = host[4:]

    if not host or not _DOMAIN_PATTERN.match(host):
        return None

    return host


def _split_title_segments(title: str) -> Iterable[str]:
    """Split a title into logical segments using common separators."""

    segments = [title]
    for delimiter in _SEGMENT_DELIMITERS:
        next_segments: list[str] = []
        for segment in segments:
            next_segments.extend(segment.split(delimiter))
        segments = next_segments
    for segment in segments:
        stripped = segment.strip()
        if stripped:
            yield stripped


def _clean_path_candidate(candidate: str) -> Optional[str]:
    """Normalize a matched file-system path segment."""

    cleaned = candidate.strip().strip(_PATH_STRIP_CHARS)
    if cleaned.endswith(("/", "\\")) and len(cleaned) > 3:
        cleaned = cleaned.rstrip("/\\")
    if not cleaned:
        return None
    return cleaned


def extract_path_root(title: str, app: str) -> Optional[str]:
    """Extract the first plausible filesystem path or project root from a title.

    Args:
        title: Window title text.
        app: Application name (typically normalized).

    Returns:
        First matching path string, or ``None`` if none found.
    """

    if not title:
        return None

    segments = list(_split_title_segments(title))
    # For code editors, strip the trailing " - <App>" portion if present.
    upper_app = app.upper()
    if upper_app in _CODE_APPS and segments:
        segments = segments[:-1] if segments[-1].upper() == upper_app else segments

    for segment in segments:
        for pattern in (_WINDOWS_PATH_PATTERN, _UNIX_PATH_PATTERN):
            match = pattern.search(segment)
            if match:
                cleaned = _clean_path_candidate(match.group("path"))
                if cleaned:
                    return cleaned
    return None


def normalize_app(app: str) -> str:
    """Normalize application identifiers into human-readable names."""

    raw = (app or "").strip()
    if not raw:
        return "Unknown App"

    key = raw.lower()
    if key in _APP_ALIASES:
        return _APP_ALIASES[key]

    # Replace delimiters with spaces and collapse multiple spaces
    pretty = re.sub(r"[_-]+", " ", raw)
    pretty = re.sub(r"\s+", " ", pretty).strip()
    if not pretty:
        return "Unknown App"

    return pretty.title()


def _pick_first_str(data: Mapping[str, object], keys: Iterable[str]) -> Optional[str]:
    """Return the first non-empty string value in ``data`` for the given keys."""

    for key in keys:
        value = data.get(key)
        if isinstance(value, str):
            stripped = value.strip()
            if stripped:
                return stripped
    return None


def _truncate_title(title: str) -> str:
    """Ensure titles do not exceed :data:`TITLE_MAX_LENGTH`."""

    if len(title) <= TITLE_MAX_LENGTH:
        return title
    return title[: TITLE_MAX_LENGTH - 3] + "..."


def enrich_event(event: Event) -> EnrichedFeatures:
    """Create :class:`~aw_llm_worker.models.EnrichedFeatures` from an event.

    Args:
        event: ActivityWatch ``Event`` instance.

    Returns:
        Populated :class:`EnrichedFeatures` with normalized metadata.
    """

    data: Mapping[str, object]
    if isinstance(event.data, Mapping):
        data = event.data
    else:
        logger.debug("Event data is not a mapping; defaulting to empty dict: %s", type(event.data))
        data = {}

    raw_app = _pick_first_str(data, ("appname", "app", "application")) or ""
    app_name = normalize_app(raw_app)

    raw_title = _pick_first_str(data, ("title", "window_title", "name"))
    title_for_path = raw_title or ""
    path_root = extract_path_root(title_for_path, app_name)

    title = raw_title.strip() if raw_title else app_name
    title = _truncate_title(title)

    url = _pick_first_str(data, ("url", "uri", "browser_url", "page_url"))
    domain = extract_domain(url)

    return EnrichedFeatures(
        app=app_name,
        title=title,
        domain=domain,
        path_root=path_root,
        url=url,
    )
