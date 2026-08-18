import time
import logging
from datetime import date, timedelta
from typing import Iterable, List, Optional, Callable

from spoticharts.client import SpotifyChartsClient, ChartUnavailable
from spoticharts.db import Database
from spoticharts.lastfm import LastFmClient, LastFmError
from spoticharts.models import ChartEntry, TrackInfo

logger = logging.getLogger(__name__)


def daterange(start: date, end: date) -> Iterable[date]:
    curr = start
    while curr <= end:
        yield curr
        curr += timedelta(days=1)


class SyncManager:
    """Coordinates scraping chart dumps and pulling Last.fm tags into SQLite."""

    def __init__(self, db: Database, spotify: SpotifyChartsClient, lastfm: Optional[LastFmClient] = None):
        self.db = db
        self.spotify = spotify
        self.lastfm = lastfm

    def sync_chart(self, region: str, chart_date: date, chart_type: str = "regional-daily") -> int:
        date_str = chart_date.isoformat()
        try:
            entries = self.spotify.get_chart(region=region, chart_date=date_str, chart_type=chart_type)
        except ChartUnavailable:
            return 0

        if not entries:
            return 0

        # spotify csv format changed header capitalization somewhere around 2020
        # client handles mapping, db expects unified keys
        self.db.save_chart_entries(entries)
        return len(entries)

    def backfill_region(
        self,
        region: str,
        start: date,
        end: date,
        delay: float = 0.5,
        progress_cb: Optional[Callable[[date, int], None]] = None,
    ) -> int:
        total = 0
        for day in daterange(start, end):
            day_str = day.isoformat()
            if self.db.has_chart(region, day_str):
                if progress_cb:
                    progress_cb(day, 0)
                continue

            count = self.sync_chart(region, day)
            total += count
            if progress_cb:
                progress_cb(day, count)

            # print(f"DEBUG: fetched {region} {day_str} count={count}")
            if delay > 0:
                time.sleep(delay)
        return total

    def enrich_pending_tracks(self, limit: int = 200, delay: float = 0.25) -> int:
        if not self.lastfm:
            logger.error("cannot enrich: lastfm client not configured")
            return 0

        tracks = self.db.get_tracks_missing_tags(limit=limit)
        if not tracks:
            return 0

        enriched = 0
        for track in tracks:
            try:
                info = self.lastfm.get_track_info(track.artist, track.title)
                # fallback: sometimes track search fails on ft. or remasters, try top artist tags
                tags = info.tags if info else []
                listeners = info.listeners if info else None
                playcount = info.playcount if info else None

                if not tags:
                    artist_tags = self.lastfm.get_artist_tags(track.artist)
                    if artist_tags:
                        tags = artist_tags

                self.db.update_track_metadata(
                    spotify_id=track.spotify_id,
                    tags=tags,
                    listeners=listeners,
                    playcount=playcount,
                    # marks enriched even if empty so we do not re-query indefinitely
                    is_enriched=True,
                )
                enriched += 1
            except LastFmError as e:
                logger.debug(f"lastfm api error for {track.artist} - {track.title}: {e}")
                # TODO: add exponential backoff if getting ratelimited by last.fm
            except Exception as e:
                logger.warning(f"unexpected failure enriching {track.artist} - {track.title}: {e}")

            if delay > 0:
                time.sleep(delay)

        return enriched
