"""Configuration helpers for the WSB sentiment tracker."""

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class RedditConfig:
    client_id: str
    client_secret: str
    user_agent: str
    subreddit: str = "wallstreetbets"


@dataclass(frozen=True)
class DatabaseConfig:
    url: str


@dataclass(frozen=True)
class AppConfig:
    reddit: RedditConfig
    database: DatabaseConfig


def load_config() -> AppConfig:
    """Load configuration from environment variables."""
    return AppConfig(
        reddit=RedditConfig(
            client_id=os.environ["REDDIT_CLIENT_ID"],
            client_secret=os.environ["REDDIT_CLIENT_SECRET"],
            user_agent=os.environ.get("REDDIT_USER_AGENT", "wsb-tracker/0.1"),
            subreddit=os.environ.get("REDDIT_SUBREDDIT", "wallstreetbets"),
        ),
        database=DatabaseConfig(
            url=os.environ.get("DATABASE_URL", "postgresql+psycopg://localhost/wsb_tracker")
        ),
    )
