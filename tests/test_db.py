import pytest
from spoticharts.db import Database
from spoticharts.models import ChartEntry


@pytest.fixture
def in_memory_db():
    db = Database(":memory:")
    db.init_schema()
    return db


def test_init_schema_creates_tables(in_memory_db):
    with in_memory_db.connect() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = {row[0] for row in cursor.fetchall()}
        assert "charts" in tables
        assert "tracks" in tables
        assert "track_tags" in tables


def test_save_chart_entries_and_has_chart(in_memory_db):
    entry1 = ChartEntry(
        spotify_id="track_1",
        title="Song One",
        artist="Artist A",
        rank=1,
        streams=15000,
        region="global",
        chart_date="2024-01-10",
    )
    entry2 = ChartEntry(
        spotify_id="track_2",
        title="Song Two",
        artist="Artist B",
        rank=2,
        streams=12000,
        region="global",
        chart_date="2024-01-10",
    )

    assert not in_memory_db.has_chart("global", "2024-01-10")
    in_memory_db.save_chart_entries([entry1, entry2])
    assert in_memory_db.has_chart("global", "2024-01-10")
    assert not in_memory_db.has_chart("us", "2024-01-10")


def test_idempotent_insert(in_memory_db):
    entry = ChartEntry(
        spotify_id="track_1",
        title="Song One",
        artist="Artist A",
        rank=1,
        streams=15000,
        region="global",
        chart_date="2024-01-10",
    )
    in_memory_db.save_chart_entries([entry])
    in_memory_db.save_chart_entries([entry])

    with in_memory_db.connect() as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM charts")
        assert c.fetchone()[0] == 1
        c.execute("SELECT COUNT(*) FROM tracks")
        assert c.fetchone()[0] == 1


def test_tag_enrichment_and_distribution(in_memory_db):
    entry = ChartEntry(
        spotify_id="trk_pop_1",
        title="Dance Anthem",
        artist="Pop Star",
        rank=1,
        streams=99000,
        region="gb",
        chart_date="2024-05-01",
    )
    in_memory_db.save_chart_entries([entry])

    # initially not enriched
    missing = in_memory_db.get_tracks_missing_tags(limit=10)
    assert len(missing) == 1
    assert missing[0].spotify_id == "trk_pop_1"

    # enrich with multiple tags
    in_memory_db.update_track_metadata(
        spotify_id="trk_pop_1",
        tags=["pop", "dance", "electronic"],
        listeners=500000,
        playcount=2000000,
        is_enriched=True,
    )

    missing_after = in_memory_db.get_tracks_missing_tags(limit=10)
    assert len(missing_after) == 0

    dist = in_memory_db.get_region_tag_distribution("gb")
    tags_found = {tag for tag, count in dist}
    assert "pop" in tags_found
    assert "dance" in tags_found
    assert len(dist) == 3
