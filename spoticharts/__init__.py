"""Spoticharts - regional Spotify chart collector and genre drift tracker."""

from spoticharts.client import SpotifyChartsClient
from spoticharts.db import Database

__version__ = "0.2.4"
__all__ = ["SpotifyChartsClient", "Database", "__version__"]
