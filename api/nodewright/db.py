"""Engine and sessions."""

from __future__ import annotations

from contextlib import contextmanager

from importlib.resources import files

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import Session, sessionmaker

BASELINE = "0001"


class Database:
    def __init__(self, url: str, broker=None):
        if url.startswith("postgresql://"):
            url = "postgresql+psycopg://" + url[len("postgresql://"):]
        self.engine = create_engine(url, pool_pre_ping=True)
        if url.startswith("sqlite"):
            # SQLite ignores foreign keys (and so ON DELETE CASCADE) unless asked.
            event.listen(self.engine, "connect",
                         lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))
        self._session = sessionmaker(self.engine, expire_on_commit=False)
        self.broker = broker
        event.listen(self._session, "after_commit", self._publish)
        event.listen(self._session, "after_rollback", lambda s: s.info.pop("nw_events", None))

    def _publish(self, s: Session) -> None:
        pending = s.info.pop("nw_events", None)
        if pending and self.broker is not None:
            for canvas_id, ev in pending:
                self.broker.publish(canvas_id, ev)

    def migrate(self) -> None:
        """Bring the schema to the latest migration. A database made by
        create_all before migrations existed (0.6.0 and earlier) matches the
        baseline, so it is stamped there first rather than re-created."""
        cfg = Config()
        cfg.set_main_option("script_location", str(files("nodewright") / "migrations"))
        with self.engine.begin() as conn:
            cfg.attributes["connection"] = conn
            tables = set(inspect(conn).get_table_names())
            if "alembic_version" not in tables and "users" in tables:
                command.stamp(cfg, BASELINE)
            command.upgrade(cfg, "head")

    @contextmanager
    def session(self):
        s: Session = self._session()
        try:
            yield s
            s.commit()
        except BaseException:
            s.rollback()
            raise
        finally:
            s.close()
