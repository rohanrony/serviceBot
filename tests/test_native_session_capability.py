"""Read-only native callback mechanism probe, no synthetic callback proof."""
from contextlib import contextmanager
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from serviceBot.api import simulation_sessions as api


@pytest.fixture
def setup_and_cleanup_test_db():
    yield


def request(value=None):
    return Request({'type':'http','headers':[] if value is None else [(b'authorization',value.encode())]})


def test_capability_defaults_closed_before_database(monkeypatch):
    monkeypatch.delenv('SIMULATION_STAFF_ENABLED',raising=False)
    monkeypatch.setenv('CRON_SECRET','offline-credential')
    def forbidden():pytest.fail('Disabled probe cannot access DB')
    monkeypatch.setattr(api,'get_db_connection',forbidden)
    with pytest.raises(HTTPException) as error:api.session_capabilities(request('Bearer offline-credential'))
    assert error.value.status_code==403


def test_capability_observes_schema_hmac_and_actual_bypass_without_side_effects(monkeypatch):
    monkeypatch.setenv('SIMULATION_STAFF_ENABLED','true');monkeypatch.setenv('CRON_SECRET','offline-credential')
    cursor=Mock();cursor.fetchone.return_value={'ready':True}
    @contextmanager
    def connection():yield object()
    @contextmanager
    def cursors(conn):yield cursor
    monkeypatch.setattr(api,'get_db_connection',connection);monkeypatch.setattr(api,'dict_cursor',cursors)
    monkeypatch.setattr(api,'elevenlabs_webhook_secret_configured',lambda:True)
    monkeypatch.setattr(api,'is_test_environment',lambda:False)
    result=api.session_capabilities(request('Bearer offline-credential'))
    assert result=={'success':True,'capability':'owned-session-v1','enabled':True,
        'audit_schema_ready':True,'hmac_configured':True,'verification_bypass_active':False}
    assert cursor.execute.call_count==1 and cursor.execute.call_args.args[0].lstrip().startswith('SELECT')
    assert not any(k in result for k in ('secret','hmac_secret','conversation_id','history_verified'))
