"""Browser read-back contract for the live runner; all providers stay captured."""
from live_simulations.evidence import browser_readback


def test_live_simulation_browser_reads_actual_booking_after_reload(page, live_server, scenario, db):
    db("UPDATE service_requests SET booking_time=%s WHERE id=1", (scenario['start'].isoformat(' '),))
    rows = db('SELECT id,service_type,issue_description,status,booking_time FROM service_requests ORDER BY id')
    checks = browser_readback(page, live_server, rows)
    assert rows and all(check['passed'] for check in checks), checks
    db("UPDATE service_requests SET issue_description='Live evidence persistence witness' WHERE id=%s", (rows[0]['id'],))
    rows = db('SELECT id,service_type,issue_description,status,booking_time FROM service_requests ORDER BY id')
    assert all(c['passed'] for c in browser_readback(page, live_server, rows))
    assert 'Live evidence persistence witness' in page.locator('#service-requests-list').inner_text()


def test_live_simulation_detects_missing_reservation(db, scenario):
    from live_simulations.evidence import local_invariants
    db("UPDATE service_requests SET booking_time=%s,staff_agent_id=1 WHERE id=1", (scenario['start'].isoformat(' '),))
    class Reader:
        rows = staticmethod(db)
    checks = local_invariants(Reader())
    assert any(c['name'] == 'booked requests have reservations' and not c['passed'] for c in checks)
