"""
ActivityWatch LLM Categorizer

A sidecar application that ingests ActivityWatch events, enriches them,
classifies them into pre-named buckets via LLM + rules, and writes back
to a new AW bucket.
"""

__version__ = "0.1.0"
__author__ = "Daniel Gagnon"

from aw_llm_worker.models import CategorizedEvent, CategoryResult

__all__ = ["CategorizedEvent", "CategoryResult", "__version__"]
