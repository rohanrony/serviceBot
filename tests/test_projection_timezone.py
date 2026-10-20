"""Compose real PostgreSQL projection snapshots with the transition predicate."""

import os
from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

import psycopg2
import pytest

from live_simulations import deployed_full_causal as causal

pytestmark = pytest.mark.test_layer("database")


@pytest.mark.parametrize("session_timezone", ["UTC", "America/Los_Angeles"])
def test_projection_timestamp_read_composes_with_transition(
    monkeypatch, session_timezone
):
    from psycopg2 import sql
    from psycopg2.extensions import make_dsn

    dsn = os.environ["TEST_DATABASE_URL"]
    schema = "projection_test_" + uuid4().hex
    with psycopg2.connect(dsn) as owner:
        with owner.cursor() as cur:
            cur.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        owner.commit()
        try:
            scoped_dsn = make_dsn(
                dsn, options=f"-c search_path={schema} -c timezone={session_timezone}"
            )
            monkeypatch.setenv("PROJECTION_TEST_DATABASE_URL", scoped_dsn)
            adapter = SimpleNamespace(
                config={
                    "deployed_medium": {"database_env": "PROJECTION_TEST_DATABASE_URL"}
                },
                current_ids={10},
                _guard=lambda: None,
            )
            with psycopg2.connect(scoped_dsn) as writer:
                with writer.cursor() as cur:
                    # Match the native schema and CURRENT_TIMESTAMP writer owner.
                    cur.execute("""CREATE TABLE outbox_notifications (
                        id SERIAL PRIMARY KEY, request_id INTEGER,
                        event_type VARCHAR(50), status VARCHAR(50), attempts INTEGER,
                        error_log TEXT, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        payload JSONB NOT NULL)""")
                    cur.execute("""INSERT INTO outbox_notifications
                        (request_id,event_type,status,attempts,error_log,payload)
                        VALUES (10,'calendar_projection','PENDING',1,'provider timeout','{}')
                        RETURNING updated_at AT TIME ZONE current_setting('TimeZone')""")
                    first_instant = cur.fetchone()[0]
                writer.commit()
                failed = causal.observe_projection(adapter, request_ids={10})[0]
                with writer.cursor() as cur:
                    cur.execute("""UPDATE outbox_notifications
                        SET status='DELIVERED', attempts=2,
                        updated_at=CURRENT_TIMESTAMP + INTERVAL '1 minute'
                        RETURNING updated_at AT TIME ZONE current_setting('TimeZone')""")
                    last_instant = cur.fetchone()[0]
                writer.commit()
                recovered = causal.observe_projection(adapter, request_ids={10})[0]
                assert causal.projection_transition(
                    failed, recovered, owned_request_ids={10}
                )
                assert datetime.fromisoformat(failed["updated_at"]) == first_instant
                assert datetime.fromisoformat(recovered["updated_at"]) == last_instant
                assert last_instant > first_instant
                assert not causal.projection_transition(
                    recovered, failed, owned_request_ids={10}
                )
        finally:
            with owner.cursor() as cur:
                cur.execute(
                    sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
                )
