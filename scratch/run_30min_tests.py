import sys
import os

# Add project root to sys.path
sys.path.insert(0, os.path.abspath("."))

from tests.test_calendar_30min_sync import (
    test_generate_slot_strings_has_30min_intervals,
    test_generate_dynamic_slots_has_30min_intervals,
    test_check_busy_via_calendar_30min_event,
    test_seed_database_creates_30min_slots,
)

if __name__ == "__main__":
    print("Running 30-minute calendar sync test suite...")
    test_generate_slot_strings_has_30min_intervals()
    print("  [PASS] test_generate_slot_strings_has_30min_intervals")
    
    test_generate_dynamic_slots_has_30min_intervals()
    print("  [PASS] test_generate_dynamic_slots_has_30min_intervals")
    
    test_check_busy_via_calendar_30min_event()
    print("  [PASS] test_check_busy_via_calendar_30min_event")
    
    test_seed_database_creates_30min_slots()
    print("  [PASS] test_seed_database_creates_30min_slots")
    
    print("\nSUCCESS: All 30-minute calendar sync tests passed!")
