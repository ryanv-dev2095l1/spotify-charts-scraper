import sys
import os
from datetime import date, datetime, timedelta
import click

from spoticharts.db import Database
from spoticharts.client import SpotifyChartsClient
from spoticharts.lastfm import LastFmClient
from spoticharts.sync import SyncManager


def parse_iso_date(val: str) -> date:
    try:
        return datetime.strptime(val, "%Y-%m-%d").date()
    except ValueError:
        raise click.BadParameter(f"expected YYYY-MM-DD, got {val}")


@click.group()
@click.option("--db-path", default="spoticharts.db", envvar="SPOTICHARTS_DB", help="Path to sqlite file")
@click.pass_context
def cli(ctx, db_path):
    ctx.ensure_object(dict)
    db = Database(db_path)
    db.init_schema()
    ctx.obj["db"] = db

    spotify = SpotifyChartsClient()
    ctx.obj["spotify"] = spotify

    lastfm_key = os.environ.get("LASTFM_API_KEY")
    lastfm = LastFmClient(api_key=lastfm_key) if lastfm_key else None
    ctx.obj["lastfm"] = lastfm
    ctx.obj["manager"] = SyncManager(db, spotify, lastfm)


@cli.command()
@click.argument("region")
@click.option("--date", "chart_date", default=None, help="Date as YYYY-MM-DD (defaults to yesterday)")
@click.pass_context
def fetch(ctx, region, chart_date):
    mgr: SyncManager = ctx.obj["manager"]
    if chart_date is None:
        # charts are usually posted ~1 day late
        target = date.today() - timedelta(days=1)
    else:
        target = parse_iso_date(chart_date)

    region = region.lower()
    count = mgr.sync_chart(region, target)
    click.echo(f"Synced {count} entries for {region} on {target}")


@cli.command()
@click.argument("region")
@click.option("--start", required=True, help="Start date YYYY-MM-DD")
@click.option("--end", required=True, help="End date YYYY-MM-DD")
@click.option("--delay", default=0.4, help="Delay in seconds between requests")
@click.pass_context
def backfill(ctx, region, start, end, delay):
    mgr: SyncManager = ctx.obj["manager"]
    s = parse_iso_date(start)
    e = parse_iso_date(end)
    if s > e:
        raise click.BadParameter("start date cannot be after end date")

    region = region.lower()
    with click.progressbar(label=f"Backfilling {region}", length=(e - s).days + 1) as bar:
        def on_step(d, cnt):
            bar.update(1)

        total = mgr.backfill_region(region, s, e, delay=delay, progress_cb=on_step)
    click.echo(f"Done. Inserted {total} total entries.")


@cli.command()
@click.option("--limit", default=200, help="Max tracks to enrich in this run")
@click.option("--delay", default=0.2, help="Delay between last.fm calls")
@click.pass_context
def enrich(ctx, limit, delay):
    mgr: SyncManager = ctx.obj["manager"]
    if not mgr.lastfm:
        click.echo("LASTFM_API_KEY environment variable is missing", err=True)
        sys.exit(1)

    click.echo(f"Looking up metadata for up to {limit} tracks...")
    count = mgr.enrich_pending_tracks(limit=limit, delay=delay)
    click.echo(f"Enriched {count} tracks")


@cli.command()
@click.argument("region")
@click.option("--top", default=10, help="Number of tags to display")
@click.pass_context
def drift(ctx, region, top):
    """Show top genres/tags for a region across recorded history."""
    db: Database = ctx.obj["db"]
    tag_counts = db.get_region_tag_distribution(region.lower(), limit=top)
    if not tag_counts:
        click.echo(f"No enriched track data found for region '{region}'")
        return

    click.echo(f"Top {top} tags in {region.upper()}:")
    click.echo("-" * 30)
    for tag, count in tag_counts:
        bar = "#" * min(int(count / 2), 25)
        click.echo(f"{tag:<18} {count:>5}  {bar}")


if __name__ == "__main__":
    cli()
