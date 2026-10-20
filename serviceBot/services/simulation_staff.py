"""Explicitly enabled, authenticated owned C23 fixtures. No provider operations.

A signed creation receipt is the sole ownership authority. Cleanup locks every
relation containing a relevant FK or conventional identity column before checking
references, so concurrent attachments cannot slip between checks and deletion.
"""
import base64
import hashlib
import hmac
import json
import os
import re
import uuid

from psycopg2 import sql
from psycopg2.extensions import cursor as tuple_cursor


class LifecycleDenied(ValueError):
    """No lifecycle mutation is authorized or safe."""


def authorize(authorization):
    secret = os.getenv('CRON_SECRET', '')
    if (os.getenv('SIMULATION_STAFF_ENABLED') != 'true' or not secret
            or not isinstance(authorization, str)
            or not hmac.compare_digest(authorization, 'Bearer ' + secret)):
        raise LifecycleDenied('Simulation staff lifecycle is unavailable')
    return secret


def sign_receipt(record, secret):
    body = base64.urlsafe_b64encode(json.dumps(record, sort_keys=True, separators=(',', ':')).encode()).decode()
    return body + '.' + hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()


def verify_receipt(receipt, secret):
    try:
        body, signature = receipt.split('.')
        if not secret or not hmac.compare_digest(signature, hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()):
            raise ValueError
        record = json.loads(base64.urlsafe_b64decode(body))
        if (set(record) != {'run_id', 'nonce', 'staff_id', 'service_id', 'staff_snapshot', 'service_snapshot'}
                or not isinstance(record['run_id'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', record['run_id'])
                or not re.fullmatch(r'[0-9a-f]{32}', record['nonce'])
                or any(type(record[k]) is not int or record[k] <= 0 for k in ('staff_id', 'service_id'))):
            raise ValueError
        if any(not isinstance(record[k], str) or not re.fullmatch('[0-9a-f]{64}', record[k])
               for k in ('staff_snapshot', 'service_snapshot')):
            raise ValueError
        return record
    except (ValueError, TypeError, AttributeError, KeyError):
        raise LifecycleDenied('Invalid owned fixture receipt') from None


def _names(record):
    prefix = 'simulation-c23-' + hashlib.sha256(record['run_id'].encode()).hexdigest()[:16] + '-' + record['nonce']
    return prefix + '-technician', prefix + '-service'


def _row_digest(row):
    return hashlib.sha256(json.dumps(row, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def create(conn, run_id, secret):
    if not isinstance(run_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', run_id) or not secret:
        raise LifecycleDenied('Invalid run identity')
    record = {'run_id': run_id, 'nonce': uuid.uuid4().hex}
    staff_name, service_name = _names(record)
    with conn, conn.cursor(cursor_factory=tuple_cursor) as cur:
        cur.execute("INSERT INTO staff_agents(name,role,is_active) VALUES (%s,'Technician',TRUE) RETURNING id", (staff_name,))
        record['staff_id'] = cur.fetchone()[0]
        cur.execute('INSERT INTO services(name,duration_minutes) VALUES (%s,60) RETURNING id', (service_name,))
        record['service_id'] = cur.fetchone()[0]
        cur.execute('INSERT INTO service_staff_agents(service_id,staff_agent_id) VALUES (%s,%s)', (record['service_id'], record['staff_id']))
        cur.execute('SELECT to_jsonb(s) FROM staff_agents s WHERE id=%s', (record['staff_id'],))
        record['staff_snapshot'] = _row_digest(cur.fetchone()[0])
        cur.execute('SELECT to_jsonb(s) FROM services s WHERE id=%s', (record['service_id'],))
        record['service_snapshot'] = _row_digest(cur.fetchone()[0])
    return {'success': True, **record, 'name': staff_name, 'service_name': service_name, 'receipt': sign_receipt(record, secret)}


def _reference_columns(cur):
    # Catalog-driven FK coverage also catches future references and cascades.
    cur.execute("""SELECT DISTINCT ns.nspname,c.relname,a.attname,
        CASE WHEN f.confrelid='staff_agents'::regclass THEN 'staff_id' ELSE 'service_id' END
        FROM pg_constraint f JOIN pg_class c ON c.oid=f.conrelid
        JOIN pg_namespace ns ON ns.oid=c.relnamespace
        JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum=ANY(f.conkey)
        WHERE f.contype='f' AND f.confrelid IN ('staff_agents'::regclass,'services'::regclass)""")
    refs = set(cur.fetchall())
    cur.execute("""SELECT table_schema,table_name,column_name FROM information_schema.columns
        WHERE table_schema=current_schema() AND data_type IN ('integer','bigint','smallint') AND column_name IN
        ('staff_agent_id','agent_id','assigned_agent_id','triage_lock_owner','service_id')""")
    refs.update((schema, table, column, 'service_id' if column == 'service_id' else 'staff_id')
                for schema, table, column in cur.fetchall())
    return sorted(refs)


def cleanup(conn, receipt, secret):
    record = verify_receipt(receipt, secret)
    staff_name, service_name = _names(record)
    with conn, conn.cursor(cursor_factory=tuple_cursor) as cur:
        cur.execute("SET LOCAL lock_timeout='2s'")
        refs = _reference_columns(cur)
        # Parent locks stop FK attachment and deletion; table locks additionally
        # cover legacy references without FKs and serialize mapping updates.
        relations = {('public', 'staff_agents'), ('public', 'services'), ('public', 'service_requests')}
        relations.update((schema, table) for schema, table, _, _ in refs)
        for schema, table in sorted(relations):
            cur.execute(sql.SQL('LOCK TABLE {} IN SHARE ROW EXCLUSIVE MODE').format(sql.Identifier(schema, table)))
        if refs != _reference_columns(cur):
            raise LifecycleDenied('Reference schema changed during cleanup')
        cur.execute('SELECT name,is_active,email,phone_number,google_access_token,google_refresh_token,google_token_expires_at FROM staff_agents WHERE id=%s FOR UPDATE', (record['staff_id'],))
        row = cur.fetchone()
        if row != (staff_name, True, None, None, None, None, None):
            raise LifecycleDenied('Owned technician identity or account changed')
        cur.execute('SELECT name,duration_minutes FROM services WHERE id=%s FOR UPDATE', (record['service_id'],))
        if cur.fetchone() != (service_name, 60):
            raise LifecycleDenied('Owned service identity changed')
        cur.execute('SELECT to_jsonb(s) FROM staff_agents s WHERE id=%s', (record['staff_id'],))
        if _row_digest(cur.fetchone()[0]) != record['staff_snapshot']:
            raise LifecycleDenied('Owned technician was edited; cleanup refused')
        cur.execute('SELECT to_jsonb(s) FROM services s WHERE id=%s', (record['service_id'],))
        if _row_digest(cur.fetchone()[0]) != record['service_snapshot']:
            raise LifecycleDenied('Owned service was edited; cleanup refused')
        cur.execute('SELECT service_id,staff_agent_id FROM service_staff_agents WHERE service_id=%s OR staff_agent_id=%s', (record['service_id'], record['staff_id']))
        if cur.fetchall() != [(record['service_id'], record['staff_id'])]:
            raise LifecycleDenied('Owned mapping changed')
        cur.execute('SELECT 1 FROM service_requests WHERE service_type=%s LIMIT 1', (service_name,))
        if cur.fetchone():
            raise LifecycleDenied('Owned service acquired requests; cleanup refused')
        for schema, table, column, identity in refs:
            if table == 'service_staff_agents' and schema == 'public':
                continue
            cur.execute(sql.SQL('SELECT 1 FROM {} WHERE {}=%s LIMIT 1').format(sql.Identifier(schema, table), sql.Identifier(column)), (record[identity],))
            if cur.fetchone():
                raise LifecycleDenied('Owned fixture acquired references; cleanup refused')
        cur.execute('DELETE FROM service_staff_agents WHERE service_id=%s AND staff_agent_id=%s', (record['service_id'], record['staff_id']))
        cur.execute('DELETE FROM staff_agents WHERE id=%s AND name=%s AND is_active=TRUE', (record['staff_id'], staff_name))
        if cur.rowcount != 1:
            raise LifecycleDenied('Owned technician deletion refused')
        cur.execute('DELETE FROM services WHERE id=%s AND name=%s', (record['service_id'], service_name))
        if cur.rowcount != 1:
            raise LifecycleDenied('Owned service deletion refused')
    return {'success': True, 'staff_id': record['staff_id'], 'service_id': record['service_id']}
