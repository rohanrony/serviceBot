"""Isolated policy tables for eligible technicians and strict staff selection."""

import pytest

from serviceBot.services.booking import BookingService


class StaffCatalog:
    """Deterministic catalog boundary; no provider or database access."""

    def __init__(self, active, tags=None):
        self.active = set(active)
        self.tags = tags or {}
        self.rows = []

    def execute(self, _statement, parameters=()):
        if parameters and isinstance(parameters[0], str):
            self.rows = [
                {"staff_agent_id": agent} for agent in self.tags.get(parameters[0], ())
            ]
        else:
            selected = self.active if not parameters else self.active & {parameters[0]}
            self.rows = [{"id": agent} for agent in sorted(selected)]

    def fetchall(self):
        return self.rows


@pytest.mark.parametrize(
    "active,tags,expected",
    [
        ({1, 2, 3}, {"Oil Change": {1, 2}, "Brake Inspection": {2, 3}}, [2]),
        ({1, 2, 3}, {"Oil Change": {1, 2}}, [1, 2]),
        ({1, 2}, {"Oil Change": {1}, "Brake Inspection": {2}}, []),
        ({1, 3}, {"Oil Change": {1, 2}, "Brake Inspection": {2, 3}}, []),
    ],
    ids=[
        "intersection",
        "untagged-service-open",
        "no-common-technician",
        "qualified-technician-inactive",
    ],
)
def test_grouped_work_requires_one_active_technician_qualified_for_every_service(
    active, tags, expected
):
    request = {
        "service_type": "Oil Change, Brake Inspection",
        "duration_minutes": 60,
        "service_components": [
            {"name": "Oil Change", "duration_minutes": 30},
            {"name": "Brake Inspection", "duration_minutes": 30},
        ],
    }
    assert (
        BookingService._qualified_agent_ids(StaffCatalog(active, tags), request)
        == expected
    )


@pytest.mark.parametrize(
    "active,qualified,expected",
    [({1, 2}, [1, 2], [2]), ({1, 2}, [1], []), ({1}, [1, 2], [])],
    ids=["selected-eligible", "selected-unqualified", "selected-inactive"],
)
def test_explicit_staff_choice_never_falls_back_to_another_technician(
    active, qualified, expected
):
    assert (
        BookingService._candidate_agent_ids(
            StaffCatalog(active),
            requested_agent_id=2,
            fallback_agent_id=1,
            qualified_agent_ids=qualified,
        )
        == expected
    )
