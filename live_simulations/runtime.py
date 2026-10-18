"""Owned local application snapshots and databases. Never loads workspace .env."""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import quote, urlencode, urlunsplit

import httpx
import psycopg2
from psycopg2 import sql
from psycopg2.extras import RealDictCursor
from psycopg2.extensions import make_dsn, parse_dsn

from .core import ROOT, SimulationError, fingerprint, private_json


def database_params(dsn):
    try:
        params = parse_dsn(dsn)
    except psycopg2.Error:
        raise SimulationError('Invalid local PostgreSQL configuration') from None
    host = params.get('host', 'localhost')
    address = '::1' if host == '::1' else '127.0.0.1'
    if host not in ('localhost', '127.0.0.1', '::1') or params.get('service') or params.get('options'):
        raise SimulationError('Only direct loopback PostgreSQL is allowed')
    if params.get('hostaddr', address) != address:
        raise SimulationError('PostgreSQL hostaddr redirects away from loopback')
    params.update(host=host, hostaddr=address, dbname='postgres', connect_timeout='3')
    return params


def application_database_url(params):
    """The application pool accepts URI DSNs; preserve libpq loopback pinning."""
    host = params['host']
    host = '[' + host + ']' if ':' in host else host
    auth = ''
    if params.get('user') or params.get('password'):
        auth = quote(params.get('user', ''), safe='')
        if 'password' in params:
            auth += ':' + quote(params['password'], safe='')
        auth += '@'
    authority = auth + host + (':' + str(params['port']) if params.get('port') else '')
    remaining = {k: v for k, v in params.items() if k not in ('host', 'port', 'user', 'password', 'dbname')}
    return urlunsplit(('postgresql', authority, '/' + quote(params['dbname'], safe=''), urlencode(remaining), ''))


def owned_manifest(root, run_id):
    if not re.fullmatch(r'[0-9a-f]{32}', run_id):
        raise SimulationError('Invalid run ID')
    root = Path(root).resolve()
    folder = root / run_id
    if folder.is_symlink() or folder.resolve().parent != root:
        raise SimulationError('Invalid owned runtime path')
    try:
        manifest = json.loads((folder / 'manifest.json').read_text())
    except (OSError, ValueError):
        raise SimulationError('Run manifest is missing or unreadable') from None
    if manifest.get('run_id') != run_id or manifest.get('database') != f'voice_live_{run_id}_test':
        raise SimulationError('Resource manifest does not establish ownership')
    return folder, manifest


def snapshot_source(source, target):
    source, target = Path(source), Path(target)
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Explicit source allowlist: never copy credentials, databases or old configuration.
    def ignored(directory, names):
        return [n for n in names if n in ('config.json', '__pycache__', 'chroma_db', 'kb_documents')
                or n.startswith('.env') or Path(directory, n).is_symlink()
                or n.endswith(('.log', '.db', '.sqlite3', '.pyc'))]
    shutil.copytree(source / 'serviceBot', target / 'serviceBot', ignore=ignored)
    (target / 'kb_documents').mkdir(exist_ok=True)


class Runtime:
    def __init__(self, config, run_id):
        self.config = config
        self.root = Path(config.get('artifact_root', ROOT / 'scratch/live-simulations')).resolve()
        self.folder, self.manifest = owned_manifest(self.root, run_id)
        self.run_id = run_id
        variable = config.get('database_admin_env', 'LIVE_SIMULATION_POSTGRES')
        dsn = os.getenv(variable, '')
        if not dsn:
            raise SimulationError(f'Missing local database environment binding: {variable}')
        self.admin_params = database_params(dsn)
        self.dsn = application_database_url({**self.admin_params, 'dbname': self.manifest['database']})
        self.url = f'http://127.0.0.1:{config["app_port"]}'
        self.gateway_url = f'http://127.0.0.1:{config["gateway_port"]}'
        self.processes = []

    def save(self):
        private_json(self.folder / 'manifest.json', self.manifest)

    @classmethod
    def prepare(cls, config):
        run_id = uuid.uuid4().hex
        root = Path(config.get('artifact_root', ROOT / 'scratch/live-simulations')).resolve()
        folder = root / run_id
        folder.mkdir(parents=True, mode=0o700)
        manifest = {'run_id': run_id, 'database': f'voice_live_{run_id}_test',
                    'created_at': time.time(), 'provider_tests': [], 'invocations': [],
                    'calendar_events': [], 'results': [], 'status': 'preparing',
                    'config_fingerprint': fingerprint(config), 'cleanup': {}}
        private_json(folder / 'manifest.json', manifest)
        runtime = cls(config, run_id)
        conn = psycopg2.connect(make_dsn(**runtime.admin_params))
        try:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(manifest['database'])))
                cur.execute(sql.SQL('COMMENT ON DATABASE {} IS %s').format(sql.Identifier(manifest['database'])),
                            (f'live_simulations:{run_id}',))
        finally:
            conn.close()
        runtime.manifest['database_created'] = True
        runtime.save()
        snapshot_source(ROOT, folder / 'app')
        files = sorted((folder / 'app/serviceBot').rglob('*'))
        runtime.manifest['source_fingerprint'] = fingerprint({str(p.relative_to(folder / 'app')): fingerprint(p.read_bytes().hex())
                                                             for p in files if p.is_file()})
        runtime.manifest['source_commit'] = subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        runtime.manifest['runner_fingerprint'] = fingerprint({p.name: fingerprint(p.read_bytes().hex())
            for p in sorted((ROOT / 'live_simulations').glob('*')) if p.suffix in ('.py', '.json')})
        private_json(folder / 'gateway.json', {'token': secrets.token_urlsafe(32), 'app_url': runtime.url,
                                              'run_folder': str(folder), 'port': config['gateway_port']})
        # These files contain synthetic configuration only; providers are configured in
        # the isolated portal before any live campaign, never copied from the workspace.
        private_json(folder / 'app/serviceBot/config.json', config.get('app_config', {}))
        (folder / 'app/kb_documents/simulation-services.txt').write_text(
            'Oil Change costs $80-$120 and takes 60 minutes. Tire Rotation costs $30-$50 and takes 30 minutes. '
            'Brake Inspection costs $50-$90 and takes 60 minutes. No lifetime warranty is documented.\n')
        runtime.child('from serviceBot.db.connection import init_db; init_db()')
        # Google IDs contain reservation IDs. Allocate durable non-overlapping blocks
        # across campaigns rather than reusing deleted provider event identifiers.
        lock = os.open(root / '.ids.lock', os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX)
            ids_path = root / 'id-blocks.json'
            allocation = json.loads(ids_path.read_text()) if ids_path.exists() else {'next_base': 8192}
            base = allocation['next_base']
            if type(base) is not int or base < 8192 or base + 8192 >= 2_147_483_647:
                raise SimulationError('Persistent fixture ID allocation exhausted or invalid')
            private_json(ids_path, {'next_base': base + 8192})
            runtime.manifest['id_base'] = base
            with runtime.connection() as db, db.cursor() as cur:
                for sequence in ('service_requests_id_seq', 'appointment_reservations_id_seq'):
                    cur.execute('SELECT setval(%s::regclass,%s,FALSE)', (sequence, base))
        finally:
            os.close(lock)
        runtime.manifest['status'] = 'prepared'
        runtime.save()
        return runtime

    def environment(self):
        env = {k: v for k, v in os.environ.items() if k in ('PATH', 'TMPDIR', 'LANG', 'LC_ALL', 'SSL_CERT_FILE')}
        env.update(PYTHON_DOTENV_DISABLED='1', PYTHONDONTWRITEBYTECODE='1',
                   PYTHONPATH=str(self.folder / 'app') + os.pathsep + str(ROOT), DATABASE_URL=self.dsn,
                   LOG_LEVEL='ERROR', LOG_FILE=str(self.folder / 'app-private.log'))
        for target, source in self.config.get('app_environment', {}).items():
            if target in ('DATABASE_URL', 'TEST_DATABASE_URL', 'TESTING', 'ELEVENLABS_PRODUCTION_AGENT_ID', 'PYTHONPATH', 'PYTHON_DOTENV_DISABLED'):
                raise SimulationError('Application environment attempts to bypass isolation')
            if target not in ('ENCRYPTION_KEY', 'CRON_SECRET') and not target.startswith(
                    ('TWILIO_', 'ELEVENLABS_', 'GOOGLE_', 'GMAIL_', 'SMTP_', 'OPENAI_', 'ANTHROPIC_', 'GEMINI_')):
                raise SimulationError('Unsupported application environment binding')
            if source not in os.environ:
                raise SimulationError(f'Missing application credential binding: {target}')
            env[target] = os.environ[source]
        # The recovery worker must never ingest a reference agent's old calls.
        # A live campaign pins it to the freshly created owned agent identity.
        env['ELEVENLABS_AGENT_ID'] = self.manifest.get('campaign_agent_id', '')
        return env

    def child(self, code):
        result = subprocess.run([sys.executable, '-c', code], cwd=self.folder / 'app',
                                env=self.environment(), capture_output=True, timeout=120)
        if result.returncode:
            raise SimulationError('Isolated application helper failed; inspect private runtime logs')

    def connection(self, readonly=False):
        conn = psycopg2.connect(self.dsn, cursor_factory=RealDictCursor)
        conn.set_session(readonly=readonly)
        return conn

    def rows(self, query, params=()):
        with self.connection(readonly=True) as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                return [dict(row) for row in cur.fetchall()]

    def snapshot(self):
        return {name: self.rows('SELECT * FROM ' + name + ' ORDER BY id') for name in
                ('service_requests', 'appointment_reservations', 'outbox_notifications', 'sms_log', 'crm_notes')}

    def start(self):
        # Binding failure rather than attaching to an unrelated process is intentional.
        listener = socket.socket()
        try:
            listener.bind(('127.0.0.1', self.config['app_port']))
            listener.listen(128)
            app = subprocess.Popen([sys.executable, '-m', 'live_simulations.app_server',
                                    str(self.folder), str(listener.fileno())],
                                   pass_fds=(listener.fileno(),), cwd=self.folder / 'app', env=self.environment(),
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            raise SimulationError('Isolated application port is occupied') from None
        finally:
            listener.close()
        self.processes.append(app)
        deadline = time.monotonic() + 45
        with httpx.Client(timeout=1, trust_env=False) as client:
            while time.monotonic() < deadline:
                if app.poll() is not None:
                    raise SimulationError('Isolated application could not start; port may be occupied')
                try:
                    if client.get(self.url + '/health').status_code == 200:
                        # Process must still own the port, rather than exiting behind
                        # a pre-existing application that happened to answer /health.
                        time.sleep(.1)
                        if app.poll() is not None:
                            raise SimulationError('Application port is already occupied')
                        return
                except httpx.TransportError:
                    pass
                time.sleep(.1)
        raise SimulationError('Isolated application startup timed out')

    def start_gateway(self):
        env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHON_DOTENV_DISABLED='1')
        listener = socket.socket()
        try:
            listener.bind(('127.0.0.1', self.config['gateway_port']))
            listener.listen(128)
            proc = subprocess.Popen([sys.executable, '-m', 'live_simulations.gateway', str(self.folder / 'gateway.json'), str(listener.fileno())],
                                    pass_fds=(listener.fileno(),), cwd=ROOT, env=env,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            raise SimulationError('Gateway port is occupied') from None
        finally:
            listener.close()
        self.processes.append(proc)
        time.sleep(.3)
        if proc.poll() is not None:
            raise SimulationError('Gateway port is occupied or gateway failed to start')

    def stop(self):
        for process in reversed(self.processes):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        self.processes.clear()

    def verify_ownership(self):
        with psycopg2.connect(make_dsn(**self.admin_params)) as conn, conn.cursor() as cur:
            cur.execute("SELECT shobj_description(oid, 'pg_database') FROM pg_database WHERE datname=%s",
                        (self.manifest['database'],))
            row = cur.fetchone()
            if not row or row[0] != f'live_simulations:{self.run_id}':
                raise SimulationError('Database ownership marker missing; refusing mutation')

    def drop_database(self):
        self.verify_ownership()
        self.stop()
        conn = psycopg2.connect(make_dsn(**self.admin_params))
        try:
            conn.autocommit = True
            with conn.cursor() as cur:
                # Only terminate sessions in the exact verified owned database.
                cur.execute('SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s AND pid<>pg_backend_pid()',
                            (self.manifest['database'],))
                cur.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(self.manifest['database'])))
        finally:
            conn.close()
        self.manifest['cleanup']['database'] = 'removed'
        self.save()


@contextlib.contextmanager
def running(runtime, gateway=True):
    try:
        runtime.start()
        if gateway:
            runtime.start_gateway()
        yield runtime
    finally:
        runtime.stop()
