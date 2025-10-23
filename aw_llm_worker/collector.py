"""
Collector for polling ActivityWatch buckets.

Fetches events from aw-watcher-window, aw-watcher-web, and filters by duration.
"""

import logging
import socket
from datetime import datetime, timedelta, timezone
from typing import List

from aw_client import ActivityWatchClient
from aw_core.models import Event

from aw_llm_worker.config import Config

logger = logging.getLogger(__name__)


class EventCollector:
    """
    Collects events from ActivityWatch source buckets.
    """

    def __init__(self, config: Config):
        """
        Initialize collector with AW client.

        Args:
            config: Configuration
        """
        self.config = config
        self.hostname = socket.gethostname()

        # Initialize AW client
        self.client = ActivityWatchClient(
            client_name="aw-llm-worker",
            host=config.aw_host,
            port=config.aw_port,
            testing=config.aw_testing,
        )

    def __enter__(self):
        """Context manager entry."""
        self.client.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.client.disconnect()

    def get_bucket_ids(self) -> List[str]:
        """
        Get available source bucket IDs for this hostname.

        Returns:
            List of bucket IDs that exist
        """
        try:
            all_buckets = self.client.get_buckets()
            source_prefixes = self.config.source_buckets

            # Find buckets matching source prefixes for this hostname
            bucket_ids = []
            for prefix in source_prefixes:
                bucket_id = f"{prefix}_{self.hostname}"
                if bucket_id in all_buckets:
                    bucket_ids.append(bucket_id)
                    logger.debug(f"Found source bucket: {bucket_id}")
                else:
                    logger.warning(f"Source bucket not found: {bucket_id}")

            return bucket_ids

        except Exception as e:
            logger.error(f"Failed to get bucket IDs: {e}")
            return []

    def collect_events(
        self,
        since_minutes: int = None,
        start: datetime = None,
        end: datetime = None,
    ) -> List[Event]:
        """
        Collect events from source buckets within time window.

        Args:
            since_minutes: Minutes to look back (overrides start/end)
            start: Start time (default: lookback_minutes from config)
            end: End time (default: now)

        Returns:
            List of events meeting duration criteria
        """
        # Determine time window
        if since_minutes is not None:
            end = datetime.now(timezone.utc)
            start = end - timedelta(minutes=since_minutes)
        elif start is None or end is None:
            end = datetime.now(timezone.utc)
            start = end - timedelta(minutes=self.config.lookback_minutes)

        logger.info(f"Collecting events from {start} to {end}")

        # Get bucket IDs
        bucket_ids = self.get_bucket_ids()
        if not bucket_ids:
            logger.warning("No source buckets found")
            return []

        # Collect from all buckets
        all_events = []
        for bucket_id in bucket_ids:
            try:
                events = self.client.get_events(
                    bucket_id=bucket_id,
                    start=start,
                    end=end,
                )
                logger.debug(f"Collected {len(events)} events from {bucket_id}")
                all_events.extend(events)

            except Exception as e:
                logger.error(f"Failed to collect from {bucket_id}: {e}")
                continue

        # Filter by duration
        min_duration = timedelta(seconds=self.config.min_duration_sec)
        filtered_events = [
            event for event in all_events
            if event.duration >= min_duration
        ]

        logger.info(
            f"Collected {len(filtered_events)} events "
            f"(filtered from {len(all_events)})"
        )

        # Sort by timestamp
        filtered_events.sort(key=lambda e: e.timestamp)

        return filtered_events

    def has_afk_data(self) -> bool:
        """
        Check if AFK bucket exists.

        Returns:
            True if AFK bucket exists
        """
        try:
            all_buckets = self.client.get_buckets()
            afk_bucket = f"aw-watcher-afk_{self.hostname}"
            return afk_bucket in all_buckets
        except Exception:
            return False

    def filter_afk_events(
        self,
        events: List[Event],
        start: datetime,
        end: datetime,
    ) -> List[Event]:
        """
        Filter out AFK periods from events.

        Args:
            events: Events to filter
            start: Start time for AFK query
            end: End time for AFK query

        Returns:
            Events with AFK periods removed
        """
        if not self.has_afk_data():
            logger.debug("No AFK data available, skipping filter")
            return events

        try:
            afk_bucket = f"aw-watcher-afk_{self.hostname}"
            afk_events = self.client.get_events(
                bucket_id=afk_bucket,
                start=start,
                end=end,
            )

            # Filter events that overlap with AFK=true periods
            active_events = []
            for event in events:
                is_afk = False

                for afk_event in afk_events:
                    # Check if event overlaps with AFK period
                    afk_start = afk_event.timestamp
                    afk_end = afk_event.timestamp + afk_event.duration
                    event_start = event.timestamp
                    event_end = event.timestamp + event.duration

                    # Check for overlap
                    if (event_start < afk_end and event_end > afk_start):
                        # Check if AFK status is true
                        if afk_event.data.get("status") == "afk":
                            is_afk = True
                            break

                if not is_afk:
                    active_events.append(event)

            logger.debug(
                f"Filtered {len(events) - len(active_events)} AFK events"
            )
            return active_events

        except Exception as e:
            logger.error(f"Failed to filter AFK events: {e}")
            return events  # Return unfiltered on error
