"""Catalog restoration gates native readiness without blocking the event loop."""
import asyncio
import threading
from unittest.mock import Mock

import pytest

from serviceBot import main
from serviceBot.api import portal


def test_native_startup_restores_catalog_before_workers_and_ready(monkeypatch):
    order = []
    monkeypatch.setattr(main, '_isolated_startup', lambda: False)
    monkeypatch.setattr(portal, 'sync_services_to_kb', lambda: order.append('catalog'))
    for module, name in (
        ('outbox_worker', 'start_outbox_worker'),
        ('quiet_hours', 'start_quiet_hours_queue_worker'),
        ('sms_reminders', 'start_reminder_polling_worker'),
    ):
        monkeypatch.setattr(f'serviceBot.services.{module}.{name}', lambda: order.append('worker'))
    monkeypatch.delenv('ELEVENLABS_API_KEY', raising=False)
    monkeypatch.setattr('serviceBot.services.call_sync.stop_call_sync_worker', lambda: None)
    log = Mock()
    monkeypatch.setattr(main, 'logger', log)

    async def run():
        async with main.lifespan(main.app):
            order.append('ready')
    asyncio.run(run())
    assert order == ['catalog', 'worker', 'worker', 'worker', 'ready']
    assert any('duration_seconds' in str(call) for call in log.info.call_args_list)


def test_catalog_failure_never_starts_workers_or_becomes_ready(monkeypatch):
    monkeypatch.setattr(main, '_isolated_startup', lambda: False)
    def fail():
        raise ValueError('secret connection string must not escape')
    monkeypatch.setattr(portal, 'sync_services_to_kb', fail)
    worker = Mock()
    monkeypatch.setattr('serviceBot.services.outbox_worker.start_outbox_worker', worker)
    log = Mock()
    monkeypatch.setattr(main, 'logger', log)
    ready = []
    async def run():
        async with main.lifespan(main.app):
            ready.append(True)
    with pytest.raises(RuntimeError, match='Service catalog startup recovery failed') as error:
        asyncio.run(run())
    assert not ready
    worker.assert_not_called()
    assert error.value.__suppress_context__ is True
    assert 'secret' not in str(error.value)
    assert 'secret' not in str(log.mock_calls)


def test_catalog_work_runs_off_event_loop(monkeypatch):
    entered = threading.Event()
    released = threading.Event()
    loop_progress = asyncio.Event()
    owner_thread = threading.get_ident()
    worker_threads = []
    def sync():
        worker_threads.append(threading.get_ident())
        entered.set()
        assert released.wait(timeout=5)
    monkeypatch.setattr(portal, 'sync_services_to_kb', sync)
    async def run():
        task = asyncio.create_task(main._restore_startup_catalog())
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            # A blocked sync owner must leave this coroutine able to advance.
            loop_progress.set()
            assert loop_progress.is_set()
        finally:
            released.set()
        await task
    asyncio.run(run())
    assert worker_threads and worker_threads[0] != owner_thread


def test_isolated_lifespan_does_not_restore_catalog(monkeypatch):
    monkeypatch.setattr(main, '_isolated_startup', lambda: True)
    sync = Mock()
    monkeypatch.setattr(portal, 'sync_services_to_kb', sync)
    async def run():
        async with main.lifespan(main.app):
            pass
    asyncio.run(run())
    sync.assert_not_called()
