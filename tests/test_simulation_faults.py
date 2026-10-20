"""Native simulation failure controls: disposable DB and synthetic credentials only."""
import pytest


def test_control_path_is_authenticated_and_disabled(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from serviceBot.api.simulation_faults import router
    app = FastAPI()
    app.include_router(router)
    monkeypatch.delenv('SIMULATION_FAULTS_ENABLED', raising=False)
    response = TestClient(app).post('/api/v1/portal/internal/simulation-faults', json={
        'run_id':'unit-run','mode':'calendar_once','technician_id':1,
        'phone':'+15550100001','booking_time':'2030-01-02T10:00:00'})
    assert response.status_code == 403


def test_no_context_hook_does_not_touch_database():
    from serviceBot.services import simulation_faults as faults
    class RefuseCursor:
        def execute(self, *args):
            raise AssertionError('Non-simulation booking must not query fault controls')
    faults.bind_booking(RefuseCursor(), request_id=1, reservation_id=2,
        outbox_id=3, staff_agent_id=4, service_type='Oil Change', customer_phone='+15550100001')


@pytest.mark.parametrize('headers,enabled',[
    ({},'true'),({'authorization':'Bearer wrong'},'true'),
    ({'authorization':'Bearer local-only-cron'},'false')])
def test_fault_auth_rejects_missing_wrong_and_disabled(monkeypatch,headers,enabled):
    from serviceBot.services import simulation_faults as faults
    monkeypatch.setenv('CRON_SECRET','local-only-cron')
    monkeypatch.setenv('SIMULATION_FAULTS_ENABLED',enabled)
    with pytest.raises(faults.FaultDenied):
        faults.authorize(headers.get('authorization'))


def test_lease_token_is_bound_to_its_handle_and_server_secret():
    import uuid

    from serviceBot.services import simulation_faults as faults
    handle=str(uuid.uuid4())
    token=faults._token(handle,'local-only-cron')
    assert faults.verify_token(handle,token,'local-only-cron')==handle
    with pytest.raises(faults.FaultDenied):
        faults.verify_token(str(uuid.uuid4()),token,'local-only-cron')
    with pytest.raises(faults.FaultDenied):
        faults.verify_token(handle,token,'another-secret')


def test_disabled_worker_hook_does_not_open_database(monkeypatch):
    from serviceBot.services import simulation_faults as faults
    monkeypatch.delenv('SIMULATION_FAULTS_ENABLED',raising=False)
    def refused():
        raise AssertionError('Disabled native worker hook must not open any database')
    monkeypatch.setattr(faults,'get_db_connection',refused)
    assert faults.before_calendar_dispatch(1,2,{}) is None


def test_capability_auth_rejection_happens_before_database_access(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from serviceBot.api.simulation_faults import router
    from serviceBot.services import simulation_faults as faults
    monkeypatch.setenv('SIMULATION_FAULTS_ENABLED','true')
    monkeypatch.setenv('CRON_SECRET','local-only-cron')
    def database_forbidden():
        raise AssertionError('Unauthenticated metadata probe must not access PostgreSQL')
    monkeypatch.setattr(faults,'get_db_connection',database_forbidden)
    app=FastAPI()
    app.include_router(router)
    assert TestClient(app).get('/api/v1/portal/internal/simulation-faults').status_code==403


@pytest.mark.parametrize('operation', ['create', 'begin_execute', 'capabilities'])
def test_required_business_intake_blocks_before_fault_resources(monkeypatch, operation):
    from serviceBot.services import business_profile
    from serviceBot.services import simulation_faults as faults

    profile = business_profile.BusinessProfile(intake_fields=[{
        'key': 'preference', 'label': 'Preference', 'required': True,
    }]).model_dump()
    monkeypatch.setattr(business_profile, 'get_business_profile', lambda: profile)
    monkeypatch.setenv('SIMULATION_FAULTS_ENABLED', 'true')
    monkeypatch.setenv('SIMULATION_FAULT_TECHNICIAN_IDS', '1')
    monkeypatch.setenv('SIMULATION_FAULT_PHONE_NUMBERS', '+15550100001')

    def database_forbidden():
        raise AssertionError('Unsupported business intake must fail before opening fault resources')

    monkeypatch.setattr(faults, 'get_db_connection', database_forbidden)
    with pytest.raises(faults.FaultDenied, match='required business intake'):
        if operation == 'create':
            faults.create(run_id='required-intake', mode='calendar_once', technician_id=1,
                phone='+15550100001', booking_time='2030-01-02T10:00:00', secret='test-only')
        elif operation == 'begin_execute':
            faults.begin_execute('00000000-0000-0000-0000-000000000001')
        else:
            faults.capabilities()
