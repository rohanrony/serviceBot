"""Pure full-delta planning contracts; no native execution capability is claimed.

Capability declarations supplied by configuration are evidence requests, never
proof. Runtime support must be implemented and verified before paid admission.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from types import MappingProxyType

from .core import SimulationError
from .deployed_full_adapter import SUPPORTED_CASE_IDS as IMPLEMENTED_CASE_IDS

FULL_IDS = tuple(f'C{i:02}' for i in range(17, 51))
DESIGNATED_HANDSET = '+14242704893'


@dataclass(frozen=True)
class CaseContract:
    setup: str
    mechanisms: tuple[str, ...]
    owned_resources: tuple[str, ...]
    expected_effects: tuple[str, ...]
    forbidden_effects: tuple[str, ...]
    assertions: tuple[str, ...]
    observations: tuple[str, ...]
    cleanup: tuple[str, ...]
    prerequisites: tuple[str, ...]


# Each row states the native mechanism, positive outcome and prohibited outcome.
_ROWS = (
    ('fresh', 'observe native appointment lead-time clock and request inside boundary', 'lead-time refusal', 'reservation inside lead time'),
    ('fresh', 'observe native callback lead-time clock and request inside boundary', 'callback lead-time refusal', 'callback inside lead time'),
    ('fresh', 'read native business closed-day schedule and request closed date', 'closed-day refusal', 'closed-day reservation'),
    ('fresh', 'read native closing time and request visit crossing closing', 'closing-time refusal', 'visit ending after closing'),
    ('fresh', 'ask ambiguous timezone then confirm explicit business-zone timestamp', 'clarified timestamp recorded', 'unconfirmed timezone conversion'),
    ('google_busy', 'create owned busy event through designated Google calendar API', 'busy interval excluded', 'overlapping reservation'),
    ('calendar_unknown', 'map only an owned test service to a new owned unconnected technician and observe actual deployed unknown availability', 'unknown availability fails closed', 'booking from unknown availability'),
    ('split_unavailable', 'reserve owned second-specialist interval through native route', 'complete visit refused', 'partial visit committed'),
    ('three_services', 'create three owned catalog services with native qualifications', 'complete qualified three-service visit', 'missing or duplicate component'),
    ('untagged', 'create owned service without qualifications through native catalog route', 'eligible active technician assigned under mappingless service policy', 'inactive or ineligible assignment'),
    ('inactive', 'use owned inactive technician with restorable native state', 'inactive technician excluded', 'inactive assignment'),
    ('appointment', 'book owned visit then add service through supported native consolidation', 'capacity permits complete expanded visit', 'duplicate original request'),
    ('consolidation_blocked', 'book owned visit and block extension through native reservation', 'blocked extension preserves original visit', 'partial expansion'),
    ('linked', 'remove one component through a supported selective native mutation', 'remaining linked components preserved', 'whole-group cancellation'),
    ('split', 'request separated callbacks through native voice tools', 'separate callbacks persisted', 'forced contiguous appointment'),
    ('fresh', 'request appointment and separate callback through native voice tools', 'both requested types persisted', 'merged or missing callback'),
    ('other_customer', 'attempt mutation of distinct customer owned fixture', 'foreign mutation refused', 'foreign customer row changed'),
    ('fresh', 'repeat confirmed booking request with native invocation correlation', 'one booking persists', 'duplicate reservation'),
    ('projection_recovery', 'observe actual deployed projection failure then native worker recovery', 'committed reservation projects once after recovery', 'duplicate commit or projection'),
    ('lost_response', 'interrupt actual deployed response after proven commit then retry', 'same committed request recovered', 'duplicate retry booking'),
    ('notification_failure', 'observe actual provider rejection for owned notification', 'failure persisted without booking rollback', 'claimed delivery or duplicate booking'),
    ('whatsapp_unenrolled', 'use independently observed unenrolled designated recipient', 'actual unenrolled-provider rejection or failure persisted', 'false delivery claim'),
    ('whatsapp_window', 'observe actual closed provider messaging window', 'closed-window policy enforced', 'unpermitted messaging'),
    ('opt_out', 'set owned recipient opt-out through supported native route', 'opt-out suppresses notification', 'message sent after opt-out'),
    ('quiet_hours', 'observe real quiet interval and native worker after release deadline', 'one deferred notification releases', 'early or duplicate delivery'),
    ('staff_confirm', 'correlate real designated staff inbound confirmation to owned offer', 'assigned technician confirmation persisted', 'uncorrelated confirmation'),
    ('staff_decline', 'correlate real staff decline and next eligible offer', 'eligible reassignment persists', 'declined assignment retained'),
    ('staff_timeout', 'wait actual configured offer timeout and native escalation worker', 'timeout escalation persisted', 'premature escalation'),
    ('late_confirm', 'receive late original technician reply after real reassignment', 'late original reply rejected', 'reassignment overwritten'),
    ('fresh', 'read native FAQ source and ask grounded question', 'answer matches source', 'invented business fact'),
    ('fresh', 'observe actual resolved no-transfer capability and open-window native unavailable response', 'honest unavailable handoff response', 'false live transfer claim'),
    ('interrupted', 'interrupt an actual paid provider invocation during booking then recover', 'interrupted invocation recovers without duplicate', 'invented interrupted provenance'),
    ('fresh', 'request bypass of native business rules', 'business-rule bypass refused', 'unauthorized mutation'),
    ('history', 'observe actual provider post-call webhook and native conversation history', 'provider conversation linked to native call history', 'fabricated history provenance'),
)

_SPECIAL = {
    'C22': ('designated Google account with actual free/busy access and owned event cleanup',),
    'C23': ('actual deployed unconnected-calendar dependency; local gateway faults are not deployed proof and this is not an external Google outage',
            'native_setup_allowed=False until atomic conditional noncascading owned-technician cleanup exists'),
    'C26': ('all possible eligible technician destinations must be allowlisted',),
    'C30': ('actual selected-only removal with independently retired selected projection and unchanged companion interval',),
    'C31': ('actual qualified callback slots and two distinct fifteen-minute calendar projections with the intentional gap',),
    'C33': ('distinct customer phone ownership; same handset cannot establish a distinct customer',),
    'C35': ('actual projection worker failure/recovery; local gateway faults are not deployed proof',),
    'C36': ('actual deployed commit/response-loss correlation; local gateway faults are not deployed proof',),
    'C37': ('actual provider rejection evidence without shared messaging configuration changes',),
    'C38': ('independently verified actual provider unenrolled state; enrolled handset4893 cannot establish unenrolled state',),
    'C39': ('actual provider conversation window timestamps',),
    'C40': ('owned opt-out state with exact restoration and no production enrollment changes',),
    'C41': ('existing voice-bypass policy requires an owner decision on the applicable notification flow; real quiet-hours deadline and observed native worker release',),
    'C42': ('human operator and correlated actual inbound provider reply',),
    'C43': ('human operator decline and eligible reassignment with designated recipients only',),
    'C44': ('real elapsed timeout and observed native escalation worker',),
    'C45': ('distinct original sender after reassignment; shared staff handset cannot establish distinct original sender',),
    'C47': ('actual resolved native capability absence and open business-window unavailable response; no simulated transfer receipt',),
    'C48': ('actual interrupted invocation; seeded booking is not interruption evidence',),
    'C50': ('actual provider conversation/webhook provenance; synthetic signature is not native history',),
}


def _contract(index, row):
    setup, mechanism, expected, forbidden = row
    cid = FULL_IDS[index]
    return CaseContract(
        setup=setup,
        mechanisms=(mechanism,),
        owned_resources=('journal exact case-owned request, reservation, event and notification IDs before cleanup',),
        expected_effects=(expected,),
        forbidden_effects=(forbidden, 'original business records or shared messaging/Gmail configuration changed'),
        assertions=(f'positive durable read-back: {expected}', f'negative durable baseline comparison: no {forbidden}'),
        observations=('read-only deployed database and reloaded browser observations scoped to owned IDs',
                      'actual provider observations where external effects are asserted; inbox receipt remains unverified without receiving evidence'),
        cleanup=('settle owned outbox/provider effects; cancel only proven owned requests through native routes',
                 'delete owned events/catalog and restore journaled fixture state with exact read-back; stop on unknown ownership/effect'),
        prerequisites=('only designated handset ' + DESIGNATED_HANDSET + ' and already designated email/calendar accounts',
                       'implemented native case adapter and independently observed deployed prerequisites') + _SPECIAL.get(cid, ()),
    )


CASE_CONTRACTS = MappingProxyType({cid: _contract(i, row) for i, (cid, row) in enumerate(zip(FULL_IDS, _ROWS, strict=True))})


def validate_delta(cases, *, tier='full', repeat=1):
    """Reject overlap, missing cases, reordered scope and repeated paid samples."""
    if (tier != 'full' or type(repeat) is not int or repeat != 1
            or not isinstance(cases, (list, tuple))
            or any(not isinstance(case, dict) for case in cases)
            or tuple(case.get('id') for case in cases) != FULL_IDS
            or any(case.get('tier') != 'full' for case in cases)
            or any(case.get('setup') != CASE_CONTRACTS[case['id']].setup for case in cases)):
        raise SimulationError('Deployed full delta requires ordered C17-C50 exactly once, full tier only')


def readiness(config, cases, *, capabilities=None):
    """Return deterministic blocking coverage, without I/O or config-based admission.

    ``capabilities`` is accepted for adapter composition but cannot establish
    implementation or observation. This planning module executes no native case.
    """
    validate_delta(cases)
    reports = {}
    supported = [cid for cid in FULL_IDS if cid in IMPLEMENTED_CASE_IDS]
    for cid, contract in CASE_CONTRACTS.items():
        implemented = cid in IMPLEMENTED_CASE_IDS
        reports[cid] = {
            'status': 'blocked', 'contract': asdict(contract),
            'implementation_status': 'implemented_offline' if implemented else 'missing',
            'blockers': ([] if implemented else ['Native full case execution and durable assertions are not implemented'])
                        + list(_SPECIAL.get(cid, ()))
                        + ['Native setup, owned cleanup and independent read-back remain unproven'],
        }
        if cid == 'C23':
            reports[cid]['native_setup_allowed'] = False
            reports[cid]['implementation_status'] = 'partial_blocked'
    return {
        'ready': all(row['status'] == 'verified' for row in reports.values()),
        'scope': 'full_delta', 'case_ids': list(FULL_IDS),
        'supported_case_ids': supported,
        'unsupported_case_ids': [cid for cid in FULL_IDS if cid not in IMPLEMENTED_CASE_IDS],
        'blocked_case_ids': [cid for cid, row in reports.items() if row['status'] == 'blocked'],
        'cases': reports,
        'native_inbox_receiving': 'unverified',
        'authorization': 'separate full-stage ceiling and refreshed quota/estimates required',
    }
