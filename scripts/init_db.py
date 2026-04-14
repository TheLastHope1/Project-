"""Initialize database tables for the WSB sentiment tracker."""

from sqlalchemy import create_engine

from wsb_tracker.config import load_config
from wsb_tracker.models import Base


def main() -> None:
    cfg = load_config()
    engine = create_engine(cfg.database.url)
    Base.metadata.create_all(engine)
    print("Database schema created.")


if __name__ == "__main__":
    main()
