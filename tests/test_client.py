import pytest
from spoticharts.client import SpotifyChartsClient, ChartUnavailable, parse_chart_csv


SAMPLE_CSV = """"Position","Track Name","Artist","Streams","URL"
"1","Espresso","Sabrina Carpenter","4982110","https://open.spotify.com/track/2qSkIjg1o9h3e9v095SpTQ"
"2","BIRDS OF A FEATHER","Billie Eilish","4120300","https://open.spotify.com/track/6dOtVTDmmpzpEcWBfyRixU"
"3","A Bar Song (Tipsy)","Shaboozey","3500120","https://open.spotify.com/track/5u9J56bB4m4y10"
"""

# older dumps include note header on line 0
SAMPLE_CSV_WITH_NOTE = """Note that this data is proprietary
"Position","Track Name","Artist","Streams","URL"
"1","Blinding Lights","The Weeknd","5100200","https://open.spotify.com/track/0VjIjW4GlUZAMYd2vXMi3b"
"""


def test_parse_chart_csv_standard():
    entries = parse_chart_csv(SAMPLE_CSV, region="global", chart_date="2024-06-01")
    assert len(entries) == 3
    assert entries[0].rank == 1
    assert entries[0].title == "Espresso"
    assert entries[0].artist == "Sabrina Carpenter"
    assert entries[0].streams == 4982110
    assert entries[0].spotify_id == "2qSkIjg1o9h3e9v095SpTQ"
    assert entries[0].region == "global"
    assert entries[0].chart_date == "2024-06-01"


def test_parse_chart_csv_with_note_prefix():
    entries = parse_chart_csv(SAMPLE_CSV_WITH_NOTE, region="us", chart_date="2020-05-01")
    assert len(entries) == 1
    assert entries[0].artist == "The Weeknd"
    assert entries[0].spotify_id == "0VjIjW4GlUZAMYd2vXMi3b"


def test_parse_empty_content():
    entries = parse_chart_csv("", region="global", chart_date="2024-06-01")
    assert entries == []


def test_invalid_url_skipped():
    bad_csv = '"Position","Track Name","Artist","Streams","URL"\n"1","Bad Track","Noone","100","invalid_link"\n'
    entries = parse_chart_csv(bad_csv, region="gb", chart_date="2024-01-01")
    assert len(entries) == 0
