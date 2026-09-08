# spoticharts

I got curious about how fast local genres push out global pop hits in different regional Spotify markets, but Spotify's raw chart downloads don't include genre metadata. This tool pulls daily/weekly regional CSV dumps from Spotify Charts into a local SQLite database and matches tracks with Last.fm's tag API.

## Setup

```bash
pip install -e .
```

Set your Last.fm API key (only needed if running the `enrich` command):

```bash
export LASTFM_API_KEY="your_key_here"
```

## Usage

```bash
# download top 200 daily charts for US, Brazil and Japan
spoticharts sync --territories us,br,jp --days 30

# pull weekly charts instead
spoticharts sync --territories global,de,fr --freq weekly --weeks 8

# fetch top tags and listener counts from Last.fm
spoticharts enrich --batch-size 100 --delay 0.2

# quick genre breakdown per territory
spoticharts drift --territory br --days 30 --top-genres 5
```

SQLite DB defaults to `charts.db` in the working directory, or pass `--db-path /path/to/db.sqlite` to any command.

<!-- refreshed: 2026-09-08 -->
