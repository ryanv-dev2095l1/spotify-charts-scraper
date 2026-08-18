import csv
import io
import logging
import time
from datetime import date
from typing import Iterator, Optional
import httpx
from spoticharts.models import ChartType, RawChartEntry

log = logging.getLogger(__name__)

BASE_URL = "https://charts-spotify-com-service.spotify.com/public/v2/stats/charts/regional"
# fallback cdn endpoint for older direct csv downloads
CDN_BASE_URL = "https://spotifycharts.com/regional"


class SpotifyChartClient:
    """Fetches raw CSV chart dumps from Spotify's public chart endpoints."""

    def __init__(self, timeout: float = 20.0, max_retries: int = 3):
        self._client = httpx.Client(
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,text/csv,*/*;q=0.8",
            },
            timeout=timeout,
            follow_redirects=True,
        )
        self.max_retries = max_retries

    def fetch_chart(
        self,
        region: str,
        target_date: date,
        chart_type: ChartType = ChartType.DAILY,
    ) -> list[RawChartEntry]:
        freq_str = chart_type.value
        date_str = target_date.isoformat()
        url = f"{CDN_BASE_URL}/{region}/{freq_str}/{date_str}/download"

        for attempt in range(self.max_retries):
            try:
                # print(f"DEBUG: fetching {url}")
                resp = self._client.get(url)
                
                if resp.status_code == 429:
                    retry_after = int(resp.headers.get("Retry-After", 2 ** (attempt + 1)))
                    log.warning("rate limited on spotify charts, sleeping %ds", retry_after)
                    time.sleep(retry_after)
                    continue

                if resp.status_code in (404, 400):
                    # Spotify drops 404 for dates before tracking started in that region
                    log.info("no data available for %s on %s", region, date_str)
                    return []

                resp.raise_for_status()
                return self._parse_dump(resp.text, region, target_date, chart_type)
            except (httpx.ConnectError, httpx.ReadTimeout) as e:
                if attempt == self.max_retries - 1:
                    raise
                log.warning("request failed (%s), retrying...", e)
                time.sleep(1.5 * (attempt + 1))

        return []

    def _parse_dump(
        self,
        raw_csv: str,
        region: str,
        chart_date: date,
        chart_type: ChartType,
    ) -> list[RawChartEntry]:
        lines = raw_csv.splitlines()
        if not lines:
            return []

        # spotify csvs often start with a disclaimer row e.g. "Note that these figures..."
        # before the actual header row
        start_idx = 0
        for i, line in enumerate(lines[:5]):
            lowered = line.lower()
            if "rank" in lowered and ("artist" in lowered or "track name" in lowered or "uri" in lowered):
                start_idx = i
                break

        cleaned_content = "\n".join(lines[start_idx:])
        reader = csv.DictReader(io.StringIO(cleaned_content))
        entries = []

        for row in reader:
            # normalise keys because spotify changed "Track Name" -> "track_name" in 2023
            clean_row = {k.strip().lower().replace(" ", "_"): v.strip() for k, v in row.items() if k}
            
            uri = clean_row.get("uri", "") or clean_row.get("url", "")
            track_id = ""
            if uri:
                track_id = uri.split(":")[-1].split("/")[-1]
            
            if not track_id:
                continue

            # FIXME: spotify sometimes puts empty strings in stream counts for weekly viral dumps
            raw_streams = clean_row.get("streams", "").replace(",", "")
            streams_val = int(raw_streams) if raw_streams.isdigit() else None

            rank_val = int(clean_row.get("rank", 0)) if clean_row.get("rank", "").isdigit() else 0
            if rank_val == 0:
                continue

            entries.append(
                RawChartEntry(
                    rank=rank_val,
                    track_name=clean_row.get("track_name", clean_row.get("title", "Unknown")),
                    artist_names=clean_row.get("artist", clean_row.get("artist_names", "Unknown")),
                    streams=streams_val,
                    spotify_id=track_id,
                    chart_date=chart_date,
                    region=region,
                    chart_type=chart_type,
                    previous_rank=int(clean_row["previous_rank"]) if clean_row.get("previous_rank", "").isdigit() else None,
                    peak_rank=int(clean_row["peak_rank"]) if clean_row.get("peak_rank", "").isdigit() else None,
                    days_on_chart=int(clean_row["days_on_chart"]) if clean_row.get("days_on_chart", "").isdigit() else None,
                )
            )

        return entries

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def close(self):
        self._client.close()
