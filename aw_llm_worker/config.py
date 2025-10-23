"""
Configuration management with hot-reload support.

Loads configuration from YAML files and watches for changes.
"""

import logging
import os
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)


class Config:
    """
    Configuration container with hot-reload support.

    Loads from YAML and provides typed access to config values.
    """

    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize configuration.

        Args:
            config_path: Path to config file (default: ./config.yaml)
        """
        self._config_path = Path(config_path or "config.yaml").expanduser()
        self._config: Dict[str, Any] = {}
        self._lock = Lock()
        self._load()

    def _load(self) -> None:
        """Load configuration from YAML file."""
        try:
            if not self._config_path.exists():
                logger.warning(
                    f"Config file not found: {self._config_path}, using defaults"
                )
                self._config = self._get_defaults()
                return

            with open(self._config_path, "r") as f:
                loaded = yaml.safe_load(f)
                if not loaded:
                    logger.warning("Empty config file, using defaults")
                    self._config = self._get_defaults()
                    return

                with self._lock:
                    self._config = loaded
                logger.info(f"Loaded configuration from {self._config_path}")
        except Exception as e:
            logger.error(f"Failed to load config: {e}, using defaults")
            self._config = self._get_defaults()

    def reload(self) -> None:
        """Reload configuration from file."""
        logger.info("Reloading configuration...")
        self._load()

    def _get_defaults(self) -> Dict[str, Any]:
        """Get default configuration."""
        return {
            "clients": {},
            "rules": {
                "hobby_prog_keywords": [],
                "machining_keywords": [],
                "edu_keywords": [],
                "video_domains": [],
                "social_domains": [],
                "gaming_keywords": [],
            },
            "thresholds": {
                "min_duration_sec": 10,
                "llm_confidence_min": 0.70,
                "cache_ttl_days": 7,
                "poll_interval_sec": 60,
                "lookback_minutes": 15,
            },
            "llm": {
                "provider": "ollama",
                "ollama": {
                    "host": "http://localhost:11434",
                    "model": "llama3",
                    "timeout": 30,
                },
                "openai": {
                    "model": "gpt-4o-mini",
                    "timeout": 30,
                },
                "temperature": 0.0,
                "max_tokens": 256,
            },
            "activitywatch": {
                "host": "localhost",
                "port": 5600,
                "testing": False,
                "source_buckets": [
                    "aw-watcher-window",
                    "aw-watcher-web",
                    "aw-watcher-afk",
                ],
                "output_bucket_prefix": "aw-llm-categories",
            },
            "logging": {
                "level": "INFO",
                "format": "json",
                "output": "stdout",
            },
            "cache": {
                "db_path": "~/.local/share/aw-llm-worker/cache.db",
                "max_entries": 10000,
                "cleanup_interval_hours": 24,
            },
        }

    def get(self, key: str, default: Any = None) -> Any:
        """
        Get config value by dot-notation key.

        Args:
            key: Dot-notation key (e.g., "thresholds.min_duration_sec")
            default: Default value if key not found

        Returns:
            Config value or default
        """
        with self._lock:
            parts = key.split(".")
            value = self._config
            for part in parts:
                if isinstance(value, dict) and part in value:
                    value = value[part]
                else:
                    return default
            return value

    @property
    def clients(self) -> Dict[str, Dict[str, List[str]]]:
        """Get client definitions."""
        return self.get("clients", {})

    @property
    def rules(self) -> Dict[str, List[str]]:
        """Get rule-based classification hints."""
        return self.get("rules", {})

    @property
    def min_duration_sec(self) -> int:
        """Get minimum event duration in seconds."""
        return self.get("thresholds.min_duration_sec", 10)

    @property
    def llm_confidence_min(self) -> float:
        """Get minimum LLM confidence threshold."""
        return self.get("thresholds.llm_confidence_min", 0.70)

    @property
    def cache_ttl_days(self) -> int:
        """Get cache TTL in days."""
        return self.get("thresholds.cache_ttl_days", 7)

    @property
    def poll_interval_sec(self) -> int:
        """Get poll interval in seconds."""
        return self.get("thresholds.poll_interval_sec", 60)

    @property
    def lookback_minutes(self) -> int:
        """Get lookback window in minutes."""
        return self.get("thresholds.lookback_minutes", 15)

    @property
    def llm_provider(self) -> str:
        """Get LLM provider name."""
        return self.get("llm.provider", "ollama")

    @property
    def llm_config(self) -> Dict[str, Any]:
        """Get LLM configuration for current provider."""
        provider = self.llm_provider
        base_config = self.get(f"llm.{provider}", {})
        base_config["temperature"] = self.get("llm.temperature", 0.0)
        base_config["max_tokens"] = self.get("llm.max_tokens", 256)
        return base_config

    @property
    def aw_host(self) -> str:
        """Get ActivityWatch host."""
        return self.get("activitywatch.host", "localhost")

    @property
    def aw_port(self) -> int:
        """Get ActivityWatch port."""
        return self.get("activitywatch.port", 5600)

    @property
    def aw_testing(self) -> bool:
        """Get ActivityWatch testing mode."""
        return self.get("activitywatch.testing", False)

    @property
    def source_buckets(self) -> List[str]:
        """Get source bucket names."""
        return self.get("activitywatch.source_buckets", [])

    @property
    def output_bucket_prefix(self) -> str:
        """Get output bucket prefix."""
        return self.get("activitywatch.output_bucket_prefix", "aw-llm-categories")

    @property
    def cache_db_path(self) -> Path:
        """Get cache database path."""
        path_str = self.get("cache.db_path", "~/.local/share/aw-llm-worker/cache.db")
        return Path(path_str).expanduser()

    @property
    def cache_max_entries(self) -> int:
        """Get maximum cache entries."""
        return self.get("cache.max_entries", 10000)

    @property
    def cache_cleanup_interval_hours(self) -> int:
        """Get cache cleanup interval in hours."""
        return self.get("cache.cleanup_interval_hours", 24)


# Global config instance
_config: Optional[Config] = None


def get_config(config_path: Optional[str] = None) -> Config:
    """
    Get the global configuration instance.

    Args:
        config_path: Path to config file (only used on first call)

    Returns:
        Config instance
    """
    global _config
    if _config is None:
        _config = Config(config_path)
    return _config


def reload_config() -> None:
    """Reload the global configuration."""
    global _config
    if _config:
        _config.reload()
