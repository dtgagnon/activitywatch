"""
ActivityWatch LLM Worker - Main CLI and processing loop.

CLI commands:
- run: Main processing loop
- label: Manual correction and cache seeding
- stats: Statistics and performance metrics
"""

import logging
import sys
from datetime import datetime, timedelta
from time import sleep
from typing import Optional

import click

from aw_llm_worker.cache import ClassificationCache
from aw_llm_worker.collector import EventCollector
from aw_llm_worker.config import get_config
from aw_llm_worker.enricher import enrich_event
from aw_llm_worker.llm import classify_with_llm
from aw_llm_worker.models import CategorizedEvent, Category, CategoryResult
from aw_llm_worker.redactor import prepare_for_llm, redact_features
from aw_llm_worker.rules import classify_by_rules
from aw_llm_worker.strong_hints import classify_strong_hint
from aw_llm_worker.writer import CategoryWriter

logger = logging.getLogger(__name__)


def setup_logging(level: str = "INFO"):
    """Setup logging configuration."""
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def process_event(
    event,
    config,
    cache: ClassificationCache,
) -> Optional[CategorizedEvent]:
    """
    Process a single event through the classification pipeline.

    Pipeline:
    1. Enrich → extract metadata
    2. Redact → remove PII
    3. Cache check
    4. Strong hints → high-confidence client matching
    5. LLM → call if ambiguous
    6. Rules fallback → deterministic if LLM fails or low confidence
    7. Cache result

    Args:
        event: Raw ActivityWatch event
        config: Configuration
        cache: Classification cache

    Returns:
        CategorizedEvent or None if processing fails
    """
    try:
        # 1. Enrich
        features = enrich_event(event)

        # 2. Redact
        redacted_features = redact_features(features)

        # 3. Cache check
        cached_result = cache.get(redacted_features)
        if cached_result:
            logger.debug("Cache hit")
            return CategorizedEvent.from_result(
                timestamp=event.timestamp,
                duration=event.duration,
                result=cached_result,
                features=redacted_features,
            )

        # 4. Strong hints
        strong_result = classify_strong_hint(redacted_features, config)
        if strong_result:
            logger.debug(f"Strong hint match: {strong_result.client}")
            cache.put(redacted_features, strong_result)
            return CategorizedEvent.from_result(
                timestamp=event.timestamp,
                duration=event.duration,
                result=strong_result,
                features=redacted_features,
            )

        # 5. LLM
        llm_result = classify_with_llm(redacted_features, config)
        if llm_result and llm_result.confidence >= config.llm_confidence_min:
            logger.debug(
                f"LLM classification: {llm_result.category.value}/"
                f"{llm_result.subcategory} (conf={llm_result.confidence:.2f})"
            )
            cache.put(redacted_features, llm_result)
            return CategorizedEvent.from_result(
                timestamp=event.timestamp,
                duration=event.duration,
                result=llm_result,
                features=redacted_features,
            )

        # 6. Rules fallback
        logger.debug("Falling back to rules")
        rule_result = classify_by_rules(redacted_features, config)
        cache.put(redacted_features, rule_result)

        return CategorizedEvent.from_result(
            timestamp=event.timestamp,
            duration=event.duration,
            result=rule_result,
            features=redacted_features,
        )

    except Exception as e:
        logger.error(f"Failed to process event: {e}", exc_info=True)
        return None


@click.group()
@click.option("--config", default="config.yaml", help="Path to config file")
@click.option("--log-level", default="INFO", help="Logging level")
@click.pass_context
def cli(ctx, config, log_level):
    """ActivityWatch LLM Worker - Categorize events with LLM + rules."""
    setup_logging(log_level)
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config
    ctx.obj["config"] = get_config(config)


@cli.command()
@click.option("--since", default=None, type=int, help="Minutes to look back")
@click.option("--continuous", is_flag=True, help="Run continuously")
@click.pass_context
def run(ctx, since, continuous):
    """
    Run the main processing loop.

    Collects events, enriches, classifies, and writes to output bucket.
    """
    config = ctx.obj["config"]

    logger.info("Starting aw-llm-worker")
    logger.info(f"LLM Provider: {config.llm_provider}")
    logger.info(f"Min duration: {config.min_duration_sec}s")
    logger.info(f"LLM confidence threshold: {config.llm_confidence_min}")

    # Initialize components
    cache = ClassificationCache(
        db_path=config.cache_db_path,
        ttl_days=config.cache_ttl_days,
        max_entries=config.cache_max_entries,
    )

    try:
        with EventCollector(config) as collector, CategoryWriter(config) as writer:
            if continuous:
                logger.info(
                    f"Running continuously with {config.poll_interval_sec}s interval"
                )
                while True:
                    process_batch(collector, writer, cache, config, since)
                    sleep(config.poll_interval_sec)
            else:
                process_batch(collector, writer, cache, config, since)

    except KeyboardInterrupt:
        logger.info("Shutting down...")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


def process_batch(collector, writer, cache, config, since=None):
    """Process a batch of events."""
    try:
        # Collect events
        events = collector.collect_events(since_minutes=since)

        if not events:
            logger.info("No events to process")
            return

        logger.info(f"Processing {len(events)} events")

        # Process each event
        categorized_events = []
        stats = {
            "total": len(events),
            "cached": 0,
            "strong_hint": 0,
            "llm": 0,
            "rules": 0,
            "failed": 0,
        }

        for event in events:
            cat_event = process_event(event, config, cache)
            if cat_event:
                categorized_events.append(cat_event)

                # Track stats
                if cat_event.source == "cache":
                    stats["cached"] += 1
                elif cat_event.source == "rule":
                    if cat_event.confidence >= 0.9:
                        stats["strong_hint"] += 1
                    else:
                        stats["rules"] += 1
                elif cat_event.source == "llm":
                    stats["llm"] += 1
            else:
                stats["failed"] += 1

        # Write to AW
        if categorized_events:
            writer.write_events(categorized_events)

        # Log summary
        logger.info(
            f"Batch complete: {stats['cached']} cached, {stats['strong_hint']} strong hints, "
            f"{stats['llm']} LLM, {stats['rules']} rules, {stats['failed']} failed"
        )

    except Exception as e:
        logger.error(f"Batch processing error: {e}", exc_info=True)


@cli.command()
@click.argument("cache_key")
@click.argument("category")
@click.argument("subcategory", required=False)
@click.option("--client", default=None, help="Client name")
@click.pass_context
def label(ctx, cache_key, category, subcategory, client):
    """
    Manually label an event and seed cache.

    CACHE_KEY: SHA1 hash or 'last' for most recent
    CATEGORY: Client Work, Hobby, Entertainment, or Uncategorized
    SUBCATEGORY: Appropriate subcategory
    """
    config = ctx.obj["config"]
    cache = ClassificationCache(
        db_path=config.cache_db_path,
        ttl_days=config.cache_ttl_days,
    )

    try:
        cat = Category(category)
    except ValueError:
        click.echo(f"Invalid category: {category}")
        click.echo("Valid categories: Client Work, Hobby, Entertainment, Uncategorized")
        sys.exit(1)

    # TODO: Implement manual labeling
    # This would require storing recent events and looking up by cache key
    click.echo("Manual labeling not yet implemented")
    click.echo(f"Would label {cache_key} as {category}/{subcategory}")


@cli.command()
@click.pass_context
def stats(ctx):
    """
    Display statistics and performance metrics.
    """
    config = ctx.obj["config"]
    cache = ClassificationCache(
        db_path=config.cache_db_path,
        ttl_days=config.cache_ttl_days,
    )

    cache_stats = cache.stats()

    click.echo("=== ActivityWatch LLM Worker Statistics ===\n")

    click.echo("Cache:")
    click.echo(f"  Total entries: {cache_stats['total_entries']}")
    click.echo(f"  Average age: {cache_stats['avg_age_days']:.1f} days")
    click.echo(f"  Average use count: {cache_stats['avg_use_count']:.1f}")
    click.echo(f"  Oldest entry: {cache_stats['oldest_entry_days']} days")

    click.echo("\nConfiguration:")
    click.echo(f"  LLM Provider: {config.llm_provider}")
    click.echo(f"  Min duration: {config.min_duration_sec}s")
    click.echo(f"  LLM confidence threshold: {config.llm_confidence_min}")
    click.echo(f"  Cache TTL: {config.cache_ttl_days} days")
    click.echo(f"  Lookback window: {config.lookback_minutes} minutes")

    # Try to get output bucket stats
    try:
        with CategoryWriter(config) as writer:
            event_count = writer.get_event_count()
            click.echo(f"\nOutput bucket:")
            click.echo(f"  Total categorized events: {event_count}")
    except Exception as e:
        click.echo(f"\nCould not get output bucket stats: {e}")


if __name__ == "__main__":
    cli(obj={})
