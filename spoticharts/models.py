from datetime import date
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class ChartType(str, Enum):
    DAILY = "daily"
    WEEKLY = "weekly"


class RawChartEntry(BaseModel):
    rank: int
    track_name: str = Field(alias="track_name")
    artist_name: str = Field(alias="artist_names")
    streams: Optional[int] = None
    spotify_id: str
    chart_date: date
    region: str
    chart_type: ChartType = ChartType.DAILY
    previous_rank: Optional[int] = None
    peak_rank: Optional[int] = None
    days_on_chart: Optional[int] = None


class Track(BaseModel):
    spotify_id: str
    title: str
    artist: str


class TagScore(BaseModel):
    name: str
    # last.fm returns tag weight as 0-100 or raw count depending on endpoint
    weight: int


class EnrichedTrack(BaseModel):
    spotify_id: str
    track_name: str
    artist_name: str
    listeners: int = 0
    playcount: int = 0
    tags: list[TagScore] = Field(default_factory=list)


class GenreDriftPoint(BaseModel):
    region: str
    chart_date: date
    tag: str
    weighted_share: float
