import time
import logging
import httpx

logger = logging.getLogger(__name__)

LASTFM_API_URL = "https://ws.audioscrobbler.com/2.0/"


class LastFMClient:
    """Tiny wrapper over Last.fm track.getInfo with basic rate-limiting."""

    def __init__(self, api_key: str, min_delay: float = 0.25):
        self.api_key = api_key
        # lastfm terms ask for not more than ~5 req/sec average
        self.min_delay = min_delay
        self._last_request_time = 0.0
        self._http = httpx.Client(
            timeout=12.0,
            headers={"User-Agent": "spoticharts/0.2 (genre drift research)"}
        )

    def _throttle(self):
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < self.min_delay:
            time.sleep(self.min_delay - elapsed)
        self._last_request_time = time.monotonic()

    def get_track_info(self, artist: str, track: str) -> dict | None:
        self._throttle()
        # print(f"fetching lastfm: {artist} - {track}")
        params = {
            "method": "track.getInfo",
            "api_key": self.api_key,
            "artist": artist,
            "track": track,
            "autocorrect": 1,
            "format": "json",
        }

        retries = 2
        while retries >= 0:
            try:
                resp = self._http.get(LASTFM_API_URL, params=params)
                if resp.status_code == 429 or resp.status_code >= 500:
                    logger.warning("lastfm returned %d, backing off", resp.status_code)
                    time.sleep(1.5)
                    retries -= 1
                    continue
                break
            except httpx.RequestError as exc:
                logger.warning("lastfm connection error for %s - %s: %s", artist, track, exc)
                retries -= 1
                time.sleep(0.5)
        else:
            return None

        if resp.status_code != 200:
            return None

        try:
            data = resp.json()
        except Exception:
            return None

        if "error" in data:
            # code 6 is track not found, code 7 is invalid resource
            if data.get("error") not in (6, 7):
                logger.warning("lastfm api error %s: %s (%s - %s)", data.get("error"), data.get("message"), artist, track)
            return None

        raw_track = data.get("track")
        if not raw_track:
            return None

        return self._normalize_track(raw_track)

    def _normalize_track(self, raw: dict) -> dict:
        listeners = 0
        playcount = 0
        try:
            listeners = int(raw.get("listeners") or 0)
            playcount = int(raw.get("playcount") or 0)
        except (ValueError, TypeError):
            pass

        # Last.fm returns a dict instead of list if there is only 1 tag,
        # or an empty string/dict if no tags exist at all.
        tags = []
        toplevel_tags = raw.get("toptags", {})
        if isinstance(toplevel_tags, dict):
            tag_data = toplevel_tags.get("tag", [])
            if isinstance(tag_data, dict):
                tag_data = [tag_data]
            elif not isinstance(tag_data, list):
                tag_data = []

            for item in tag_data:
                if isinstance(item, dict) and "name" in item:
                    name = item["name"].strip().lower()
                    # TODO: filter out useless meme tags like 'seen live' or 'favorite'
                    if name and len(name) <= 64:
                        tags.append(name)

        return {
            "listeners": listeners,
            "playcount": playcount,
            "tags": tags,
            "mbid": raw.get("mbid") or None,
        }

    def close(self):
        self._http.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
