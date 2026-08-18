import sqlite3
from pathlib import Path
from typing import Any, Optional, Sequence


SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS tracks (
    spotify_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    artist TEXT NOT NULL,
    url TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS chart_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    spotify_id TEXT NOT NULL REFERENCES tracks(spotify_id),
    region TEXT NOT NULL,
    chart_type TEXT NOT NULL,
    chart_date TEXT NOT NULL,
    rank INTEGER NOT NULL,
    streams INTEGER,
    UNIQUE(spotify_id, region, chart_type, chart_date)
);

CREATE INDEX IF NOT EXISTS idx_charts_lookup 
ON chart_entries(region, chart_date, chart_type);
"""

MIGRATION_V2 = """
CREATE TABLE IF NOT EXISTS track_lastfm (
    spotify_id TEXT PRIMARY KEY REFERENCES tracks(spotify_id),
    lastfm_listeners INTEGER DEFAULT 0,
    lastfm_playcount INTEGER DEFAULT 0,
    lastfm_artist_match TEXT,
    lastfm_track_match TEXT,
    enriched_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS track_tags (
    spotify_id TEXT NOT NULL REFERENCES tracks(spotify_id),
    tag_id INTEGER NOT NULL REFERENCES tags(id),
    weight INTEGER NOT NULL DEFAULT 100,
    PRIMARY KEY (spotify_id, tag_id)
);

CREATE INDEX IF NOT EXISTS idx_track_tags_tag ON track_tags(tag_id);
"""

MIGRATION_V3 = """
CREATE INDEX IF NOT EXISTS idx_chart_entries_date_region 
ON chart_entries(chart_date, region);
"""

CHUNK_SIZE = 900


class Database:
    """Manages SQLite storage for charts and metadata."""

    def __init__(self, db_path: str | Path = "charts.db") -> None:
        self.db_path = str(db_path)
        self._conn: Optional[sqlite3.Connection] = None

    def connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.execute("PRAGMA synchronous = NORMAL")
        return self._conn

    def init_db(self) -> None:
        conn = self.connect()
        with conn:
            conn.executescript(SCHEMA_V1)
            
            row = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
            curr_v = row[0] if row else 0
            
            if curr_v < 2:
                conn.executescript(MIGRATION_V2)
                curr_v = 2
            
            if curr_v < 3:
                conn.executescript(MIGRATION_V3)
                curr_v = 3

            conn.execute("DELETE FROM schema_version")
            conn.execute("INSERT INTO schema_version (version) VALUES (?)", (curr_v,))

    def upsert_tracks(self, tracks: Sequence[tuple[str, str, str, Optional[str]]]) -> int:
        if not tracks:
            return 0
        conn = self.connect()
        query = """
        INSERT INTO tracks (spotify_id, title, artist, url)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(spotify_id) DO UPDATE SET
            title = excluded.title,
            artist = excluded.artist,
            url = coalesce(excluded.url, tracks.url)
        """
        total = 0
        with conn:
            for i in range(0, len(tracks), CHUNK_SIZE):
                chunk = tracks[i:i + CHUNK_SIZE]
                cursor = conn.executemany(query, chunk)
                total += cursor.rowcount
        return total

    def insert_chart_entries(self, entries: Sequence[dict[str, Any]]) -> int:
        if not entries:
            return 0
        conn = self.connect()
        query = """
        INSERT INTO chart_entries (spotify_id, region, chart_type, chart_date, rank, streams)
        VALUES (:spotify_id, :region, :chart_type, :chart_date, :rank, :streams)
        ON CONFLICT(spotify_id, region, chart_type, chart_date) DO UPDATE SET
            rank = excluded.rank,
            streams = excluded.streams
        """
        total = 0
        with conn:
            for i in range(0, len(entries), CHUNK_SIZE):
                chunk = entries[i:i + CHUNK_SIZE]
                cursor = conn.executemany(query, chunk)
                total += cursor.rowcount
            # print(f"saved {len(entries)} rows")
        return total

    def get_tracks_missing_metadata(self, limit: int = 200) -> list[sqlite3.Row]:
        conn = self.connect()
        query = """
        SELECT t.spotify_id, t.title, t.artist
        FROM tracks t
        LEFT JOIN track_lastfm l ON t.spotify_id = l.spotify_id
        WHERE l.spotify_id IS NULL
        ORDER BY t.created_at DESC
        LIMIT ?
        """
        return conn.execute(query, (limit,)).fetchall()

    # TODO: prune orphan tags when tracks get purged
    def save_lastfm_enrichment(
        self,
        spotify_id: str,
        listeners: int,
        playcount: int,
        artist_match: Optional[str],
        track_match: Optional[str],
        tags: list[tuple[str, int]],
    ) -> None:
        conn = self.connect()
        with conn:
            conn.execute(
                """
                INSERT INTO track_lastfm (spotify_id, lastfm_listeners, lastfm_playcount, lastfm_artist_match, lastfm_track_match, enriched_at)
                VALUES (?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(spotify_id) DO UPDATE SET
                    lastfm_listeners = excluded.lastfm_listeners,
                    lastfm_playcount = excluded.lastfm_playcount,
                    lastfm_artist_match = excluded.lastfm_artist_match,
                    lastfm_track_match = excluded.lastfm_track_match,
                    enriched_at = datetime('now')
                """,
                (spotify_id, listeners, playcount, artist_match, track_match),
            )
            
            conn.execute("DELETE FROM track_tags WHERE spotify_id = ?", (spotify_id,))
            
            for tag_name, weight in tags:
                tag_clean = tag_name.strip().lower()
                if not tag_clean or len(tag_clean) > 48:
                    continue
                conn.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (tag_clean,))
                row = conn.execute("SELECT id FROM tags WHERE name = ?", (tag_clean,)).fetchone()
                if row:
                    # Normalize weight ceiling to 100 just in case API returns bizarre vals
                    clamped_weight = max(1, min(100, int(weight)))
                    conn.execute(
                        "INSERT OR REPLACE INTO track_tags (spotify_id, tag_id, weight) VALUES (?, ?, ?)",
                        (spotify_id, row[0], clamped_weight),
                    )

    def get_genre_drift(
        self,
        region: str,
        start_date: str,
        end_date: str,
    ) -> list[sqlite3.Row]:
        conn = self.connect()
        # Junk tags from user scrobbles that mess up the genre drift trend
        junk_tags = (
            'seen live', 'favorites', 'favourite', 'albums i own',
            'loved', 'spotify', 'owned', 'my favorites', 'all time favorites'
        )
        placeholders = ",".join("?" for _ in junk_tags)
        
        query = f"""
        SELECT 
            c.chart_date,
            tg.name as tag,
            SUM((201 - c.rank) * (tt.weight / 100.0)) as score
        FROM chart_entries c
        JOIN track_tags tt ON c.spotify_id = tt.spotify_id
        JOIN tags tg ON tt.tag_id = tg.id
        WHERE c.region = ? 
          AND c.chart_date BETWEEN ? AND ?
          AND tg.name NOT IN ({placeholders})
        GROUP BY c.chart_date, tg.name
        ORDER BY c.chart_date ASC, score DESC
        """
        params = [region, start_date, end_date] + list(junk_tags)
        return conn.execute(query, params).fetchall()

    def get_available_dates(self, region: str) -> list[str]:
        conn = self.connect()
        query = "SELECT DISTINCT chart_date FROM chart_entries WHERE region = ? ORDER BY chart_date ASC"
        rows = conn.execute(query, (region,)).fetchall()
        return [r["chart_date"] for r in rows]

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
