"""
SQLite-backed cache for classification results with TTL.

Caches CategoryResult by SHA1 hash of (app, domain, title, path_root).
"""

import hashlib
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Integer,
    String,
    create_engine,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session, sessionmaker

from aw_llm_worker.models import CacheEntry, CategoryResult, EnrichedFeatures

logger = logging.getLogger(__name__)

Base = declarative_base()


class CacheRecord(Base):
    """SQLAlchemy model for cache entries."""

    __tablename__ = "cache"

    cache_key = Column(String, primary_key=True)
    category = Column(String, nullable=False)
    subcategory = Column(String, nullable=True)
    client = Column(String, nullable=True)
    confidence = Column(Float, nullable=False)
    source = Column(String, nullable=False)
    rationale = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=False)
    last_used = Column(DateTime, nullable=False)
    use_count = Column(Integer, default=0)


class ClassificationCache:
    """
    Cache for storing and retrieving classification results.

    Uses SQLite with SHA1 keys and TTL expiration.
    """

    def __init__(
        self,
        db_path: Path,
        ttl_days: int = 7,
        max_entries: int = 10000,
    ):
        """
        Initialize cache.

        Args:
            db_path: Path to SQLite database file
            ttl_days: Time-to-live in days for cache entries
            max_entries: Maximum number of entries before cleanup
        """
        self.db_path = db_path
        self.ttl_days = ttl_days
        self.max_entries = max_entries

        # Ensure directory exists
        db_path.parent.mkdir(parents=True, exist_ok=True)

        # Create engine and session
        self.engine = create_engine(f"sqlite:///{db_path}")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

        logger.info(f"Cache initialized at {db_path} with TTL={ttl_days} days")

    @staticmethod
    def compute_key(features: EnrichedFeatures) -> str:
        """
        Compute SHA1 hash key from enriched features.

        Key is based on: app|domain|title|path_root

        Args:
            features: Enriched features

        Returns:
            SHA1 hex digest
        """
        components = [
            features.app or "",
            features.domain or "",
            features.title or "",
            features.path_root or "",
        ]
        key_string = "|".join(components)
        return hashlib.sha1(key_string.encode("utf-8")).hexdigest()

    def get(self, features: EnrichedFeatures) -> Optional[CategoryResult]:
        """
        Retrieve cached result for features.

        Args:
            features: Enriched features to lookup

        Returns:
            CategoryResult if found and not expired, None otherwise
        """
        cache_key = self.compute_key(features)
        session = self.Session()

        try:
            record = session.query(CacheRecord).filter_by(cache_key=cache_key).first()

            if not record:
                return None

            # Check if expired
            age = datetime.now() - record.created_at
            if age > timedelta(days=self.ttl_days):
                logger.debug(f"Cache entry expired: {cache_key}")
                session.delete(record)
                session.commit()
                return None

            # Update last_used and use_count
            record.last_used = datetime.now()
            record.use_count += 1
            session.commit()

            logger.debug(
                f"Cache hit: {cache_key} (age={age.days}d, uses={record.use_count})"
            )

            # Convert to CategoryResult
            entry = CacheEntry(
                cache_key=record.cache_key,
                category=record.category,
                subcategory=record.subcategory,
                client=record.client,
                confidence=record.confidence,
                source=record.source,
                rationale=record.rationale,
                created_at=record.created_at,
                last_used=record.last_used,
                use_count=record.use_count,
            )
            return entry.to_result()

        finally:
            session.close()

    def put(
        self,
        features: EnrichedFeatures,
        result: CategoryResult,
    ) -> None:
        """
        Store classification result in cache.

        Args:
            features: Enriched features (key)
            result: Classification result (value)
        """
        cache_key = self.compute_key(features)
        session = self.Session()

        try:
            now = datetime.now()

            # Check if already exists
            record = session.query(CacheRecord).filter_by(cache_key=cache_key).first()

            if record:
                # Update existing
                record.category = result.category.value
                record.subcategory = result.subcategory
                record.client = result.client
                record.confidence = result.confidence
                record.source = result.source
                record.rationale = result.rationale
                record.last_used = now
                logger.debug(f"Cache updated: {cache_key}")
            else:
                # Insert new
                record = CacheRecord(
                    cache_key=cache_key,
                    category=result.category.value,
                    subcategory=result.subcategory,
                    client=result.client,
                    confidence=result.confidence,
                    source=result.source,
                    rationale=result.rationale,
                    created_at=now,
                    last_used=now,
                    use_count=0,
                )
                session.add(record)
                logger.debug(f"Cache inserted: {cache_key}")

            session.commit()

            # Check if cleanup needed
            count = session.query(CacheRecord).count()
            if count > self.max_entries:
                logger.info(f"Cache size {count} exceeds max {self.max_entries}, cleaning up")
                self.cleanup(session)

        finally:
            session.close()

    def cleanup(self, session: Optional[Session] = None) -> int:
        """
        Remove expired and least-used entries.

        Args:
            session: Optional existing session

        Returns:
            Number of entries removed
        """
        should_close = False
        if session is None:
            session = self.Session()
            should_close = True

        try:
            # Delete expired entries
            cutoff = datetime.now() - timedelta(days=self.ttl_days)
            expired = session.query(CacheRecord).filter(
                CacheRecord.created_at < cutoff
            ).all()

            for record in expired:
                session.delete(record)

            expired_count = len(expired)

            # If still over max, remove least recently used
            count = session.query(CacheRecord).count()
            if count > self.max_entries:
                to_remove = count - int(self.max_entries * 0.8)  # Remove down to 80%
                old_records = (
                    session.query(CacheRecord)
                    .order_by(CacheRecord.last_used)
                    .limit(to_remove)
                    .all()
                )

                for record in old_records:
                    session.delete(record)

                expired_count += len(old_records)

            session.commit()
            logger.info(f"Cache cleanup removed {expired_count} entries")
            return expired_count

        finally:
            if should_close:
                session.close()

    def stats(self) -> dict:
        """
        Get cache statistics.

        Returns:
            Dict with count, avg_age, hit_rate estimates
        """
        session = self.Session()
        try:
            records = session.query(CacheRecord).all()
            if not records:
                return {
                    "total_entries": 0,
                    "avg_age_days": 0,
                    "avg_use_count": 0,
                    "oldest_entry_days": 0,
                }

            now = datetime.now()
            ages = [(now - r.created_at).days for r in records]
            use_counts = [r.use_count for r in records]

            return {
                "total_entries": len(records),
                "avg_age_days": sum(ages) / len(ages) if ages else 0,
                "avg_use_count": sum(use_counts) / len(use_counts) if use_counts else 0,
                "oldest_entry_days": max(ages) if ages else 0,
            }
        finally:
            session.close()
