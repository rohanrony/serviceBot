"""Catalogue boundaries take precedence over punctuation within service names."""

import pytest

from serviceBot.db.queries import match_catalog_service_names

NAMES = ["Brake Repair & Pad Replacement", "Suspension Repair (Shocks & Struts)"]


@pytest.mark.parametrize("separator", [" and ", ", ", ", and ", " / ", " + ", " & "])
def test_full_catalogue_names_keep_their_punctuation(separator):
    assert match_catalog_service_names(separator.join(NAMES), NAMES) == NAMES


def test_longest_complete_catalogue_label_wins_over_a_prefix():
    assert match_catalog_service_names(NAMES[0], ["Brake Repair", *NAMES]) == [NAMES[0]]


def test_matching_preserves_selected_order_and_catalogue_spelling():
    assert match_catalog_service_names(
        "  " + " and ".join(reversed(NAMES)).lower() + "  ", NAMES
    ) == list(reversed(NAMES))


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "Repair",
        NAMES[0] + " and unexplained noise",
        "Please inspect " + NAMES[0],
        NAMES[0] + " and ",
    ],
)
def test_unrecognized_remainder_is_never_silently_dropped(value):
    assert match_catalog_service_names(value, NAMES) == []


def test_repeated_services_remain_visible_for_booking_validation():
    assert (
        match_catalog_service_names(" and ".join([NAMES[0]] * 2), NAMES)
        == [NAMES[0]] * 2
    )


def test_service_names_can_themselves_contain_delimiters():
    names = ["Inspection, Testing / Calibration", "Wash and Wax"]
    assert match_catalog_service_names(" and ".join(names), names) == names


def test_case_insensitive_duplicate_catalogue_labels_are_ambiguous():
    assert match_catalog_service_names(NAMES[0], [*NAMES, NAMES[0].upper()]) == []
    assert match_catalog_service_names(" and ".join(NAMES), [*NAMES, NAMES[1].upper()]) == []
