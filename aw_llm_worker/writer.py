"""
Writer for categorized events to ActivityWatch bucket.

Creates and writes to aw-llm-categories_{hostname} bucket.
"""

import logging
import socket
from typing import List

from aw_client import ActivityWatchClient
from aw_core.models import Event

from aw_llm_worker.config import Config
from aw_llm_worker.models import CategorizedEvent

logger = logging.getLogger(__name__)


class CategoryWriter:
    """
    Writes categorized events to ActivityWatch bucket.
    """

    def __init__(self, config: Config):
        """
        Initialize writer with AW client.

        Args:
            config: Configuration
        """
        self.config = config
        self.hostname = socket.gethostname()
        self.bucket_id = f"{config.output_bucket_prefix}_{self.hostname}"

        # Initialize AW client
        self.client = ActivityWatchClient(
            client_name="aw-llm-worker",
            host=config.aw_host,
            port=config.aw_port,
            testing=config.aw_testing,
        )

        self._bucket_created = False

    def __enter__(self):
        """Context manager entry."""
        self.client.connect()
        self._ensure_bucket()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.client.disconnect()

    def _ensure_bucket(self) -> None:
        """
        Ensure output bucket exists.

        Creates bucket if it doesn't exist.
        """
        if self._bucket_created:
            return

        try:
            buckets = self.client.get_buckets()
            if self.bucket_id not in buckets:
                logger.info(f"Creating bucket: {self.bucket_id}")
                self.client.create_bucket(
                    bucket_id=self.bucket_id,
                    event_type="categorized",
                )
            else:
                logger.debug(f"Bucket already exists: {self.bucket_id}")

            self._bucket_created = True

        except Exception as e:
            logger.error(f"Failed to ensure bucket: {e}")
            raise

    def write_event(self, categorized_event: CategorizedEvent) -> None:
        """
        Write a single categorized event.

        Args:
            categorized_event: CategorizedEvent to write
        """
        try:
            # Convert to AW Event
            event_data = categorized_event.to_aw_event_data()
            event = Event(
                timestamp=event_data["timestamp"],
                duration=event_data["duration"],
                data=event_data["data"],
            )

            self.client.insert_event(self.bucket_id, event)
            logger.debug(
                f"Wrote event: {categorized_event.category.value}/"
                f"{categorized_event.subcategory} "
                f"(confidence={categorized_event.confidence:.2f})"
            )

        except Exception as e:
            logger.error(f"Failed to write event: {e}")
            raise

    def write_events(self, categorized_events: List[CategorizedEvent]) -> None:
        """
        Write multiple categorized events in batch.

        Args:
            categorized_events: List of CategorizedEvent objects
        """
        if not categorized_events:
            return

        try:
            # Convert all to AW Events
            events = []
            for cat_event in categorized_events:
                event_data = cat_event.to_aw_event_data()
                event = Event(
                    timestamp=event_data["timestamp"],
                    duration=event_data["duration"],
                    data=event_data["data"],
                )
                events.append(event)

            self.client.insert_events(self.bucket_id, events)
            logger.info(f"Wrote {len(events)} events to {self.bucket_id}")

        except Exception as e:
            logger.error(f"Failed to write events: {e}")
            raise

    def get_event_count(self) -> int:
        """
        Get count of events in output bucket.

        Returns:
            Number of events
        """
        try:
            return self.client.get_eventcount(self.bucket_id)
        except Exception as e:
            logger.error(f"Failed to get event count: {e}")
            return 0
