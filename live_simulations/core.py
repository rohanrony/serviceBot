"""Catalog, budgets and private artifact handling shared by the runner."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from decimal import Decimal, InvalidOperation
from pathlib import Path

TIERS = {'minimal': Decimal('.01'), 'medium': Decimal('.02'), 'full': Decimal('.05')}
ROOT = Path(__file__).resolve().parents[1]


class SimulationError(RuntimeError):
    """A blocked operation, with an actionable but secret-free message."""


def number(value, *, positive=False):
    try:
        value = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise SimulationError('Invalid budget amount') from None
    if not value.is_finite() or value < 0 or (positive and value == 0):
        raise SimulationError('Invalid budget amount')
    return value


class Budget:
    def __init__(self, monthly, tier, remaining, *, credit_ceiling=None):
        if tier not in TIERS:
            raise SimulationError('Unknown tier')
        self.cap = number(monthly, positive=True) * TIERS[tier]
        if credit_ceiling is not None:
            self.cap = number(credit_ceiling, positive=True)
        self.remaining = number(remaining)
        self.spent = Decimal(0)
        self.settled = set()
        self.unknown = False

    def can_start(self, estimate):
        estimate = number(estimate, positive=True)
        return (not self.unknown and self.spent + estimate <= self.cap * Decimal('.8')
                and estimate <= self.remaining)

    def settle(self, invocation, amount):
        if invocation in self.settled:
            raise SimulationError('Invocation already settled')
        self.settled.add(invocation)
        if amount is None:
            self.unknown = True
            return
        amount = number(amount)
        self.spent += amount
        self.remaining -= amount


def load_catalog():
    cases = json.loads(Path(__file__).with_name('scenarios.json').read_text())
    if {c['id'] for c in cases} != {f'C{i:02}' for i in range(1, 51)}:
        raise SimulationError('Invalid catalog IDs')
    return cases


def select_cases(catalog, tier, requested=None):
    if tier not in TIERS:
        raise SimulationError('Unknown tier')
    allowed = {c['id']: c for c in catalog if list(TIERS).index(c['tier']) <= list(TIERS).index(tier)}
    wanted = set(requested or allowed)
    if not wanted <= allowed.keys():
        raise SimulationError('Unknown case or case outside selected tier')
    pending = list(wanted)
    while pending:
        for dependency in allowed[pending.pop()].get('dependencies', []):
            if dependency not in wanted:
                wanted.add(dependency)
                pending.append(dependency)
    return [c for c in catalog if c['id'] in wanted]


def render(value, variables):
    if isinstance(value, dict):
        return {k: render(v, variables) for k, v in value.items()}
    if isinstance(value, list):
        return [render(v, variables) for v in value]
    if not isinstance(value, str):
        return value
    def replacement(match):
        if match[1] not in variables:
            raise SimulationError(f'Missing fixture variable: {match[1]}')
        return str(variables[match[1]])
    return re.sub(r'\{\{([a-zA-Z_][a-zA-Z_0-9]*)\}\}', replacement, value)


def redact(value, secrets=()):
    if isinstance(value, dict):
        return {k: '[redacted]' if re.search(r'token|secret|password|authorization|api.?key|dsn', k, re.I)
                else redact(v, secrets) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, secrets) for v in value]
    if not isinstance(value, str):
        return value
    for secret in secrets:
        if secret:
            value = value.replace(secret, '[redacted]')
    value = re.sub(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', '[email]', value)
    def phone(match):
        text = match[0]
        if re.match(r'\d{4}-\d{2}-\d{2}', text):
            return text
        return '[phone]' if len(re.sub(r'\D', '', text)) in (10, 11) else text
    value = re.sub(r'(?<!\w)\+?\d[\d ().-]{8,}\d(?!\w)', phone, value)
    return value


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def private_json(path, value):
    """Atomic mode-0600 manifest updates, including interrupted-campaign evidence."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, indent=2, default=str, allow_nan=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def load_config(path):
    try:
        config = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        raise SimulationError('Cannot read simulation JSON configuration') from None
    if not isinstance(config, dict) or config.get('schema_version') != 1:
        raise SimulationError('Configuration requires schema_version: 1')
    if config.get('environment') in (None, '', 'production'):
        raise SimulationError('An explicit non-production simulation environment is required')
    for key in ('app_port', 'gateway_port'):
        port = config.get(key)
        if type(port) is not int or not 1024 <= port <= 65535:
            raise SimulationError(f'Invalid {key}')
    if config['app_port'] == config['gateway_port']:
        raise SimulationError('Application and gateway ports must differ')
    for key in ('timeout_seconds', 'evidence_timeout_seconds'):
        n = config.get(key, 120)
        if type(n) not in (int, float) or not math.isfinite(n) or not 1 <= n <= 3600:
            raise SimulationError(f'Invalid {key}')
    return config


def secret(config, name):
    variable = config.get('secrets', {}).get(name, '')
    value = os.getenv(variable, '') if variable else ''
    if not value or value.startswith(('synthetic-', 'dummy_')):
        raise SimulationError(f'Missing real credential environment binding: {name}')
    return value
