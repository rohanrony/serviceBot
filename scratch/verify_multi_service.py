#!/usr/bin/env python3
"""Standalone test runner for multi-service booking logic."""
import sys
import os

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

def test_multi_service_merge():
    from serviceBot.db.connection import get_db_connection, dict_cursor
    from serviceBot.db.queries import book_appointment, get_customer_appointments, get_service_required_fields
    
    print("=" * 60)
    print("TEST 1: get_service_required_fields multi-service fallback")
    print("=" * 60)
    
    res = get_service_required_fields("oil change, air conditioning repair, and brake repair")
    assert res is not None, "FAIL: fallback returned None"
    assert res["name"] == "oil change, air conditioning repair, and brake repair"
    assert res["price_range"] == "Varies by service"
    print("  PASS: multi-service fallback returns correct dict")
    
    print()
    print("=" * 60)
    print("TEST 2: book_appointment merges services for same slot")
    print("=" * 60)
    
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                "SELECT slot_datetime FROM mock_calendar_slots WHERE is_booked = FALSE "
                "ORDER BY slot_datetime ASC LIMIT 1;"
            )
            slot_row = cursor.fetchone()
            if not slot_row:
                print("  SKIP: No unbooked mock_calendar_slots found")
                return
            
            cursor.execute("SELECT id, name FROM customers LIMIT 1;")
            cust = cursor.fetchone()
            if not cust:
                print("  SKIP: No customer found")
                return
            
            customer_id = cust["id"]
            print(f"  Using customer: {cust['name']} (id={customer_id})")
            
            cursor.execute("SELECT id, make, model, year FROM vehicles WHERE customer_id = %s LIMIT 1;", (customer_id,))
            veh = cursor.fetchone()
            if not veh:
                print("  SKIP: No vehicle found")
                return
            
            print(f"  Using vehicle: {veh['year']} {veh['make']} {veh['model']}")
    
    slot_str = slot_row["slot_datetime"]
    if not isinstance(slot_str, str):
        slot_str = slot_str.strftime("%Y-%m-%d %H:%M:%S")
    print(f"  Using slot: {slot_str}")
    
    vehicle_details = {"make": veh["make"], "model": veh["model"], "year": veh["year"]}
    
    print("  Booking Oil Change...")
    try:
        appt_id1 = book_appointment(
            customer_id=customer_id, service_request_id=None,
            appointment_datetime=slot_str, service_type='Oil Change',
            vehicle_details=vehicle_details
        )
        print(f"  First booking OK, id={appt_id1}")
    except Exception as e:
        print(f"  FAIL: First booking raised: {e}")
        return
    
    print("  Booking AC change for SAME slot (should merge)...")
    try:
        appt_id2 = book_appointment(
            customer_id=customer_id, service_request_id=None,
            appointment_datetime=slot_str, service_type='AC change',
            vehicle_details=vehicle_details
        )
        print(f"  Second booking OK, id={appt_id2}")
    except Exception as e:
        print(f"  FAIL: Second booking raised ValueError (the bug!): {e}")
        return
    
    assert appt_id2 == appt_id1, f"FAIL: Expected same ID, got {appt_id1} vs {appt_id2}"
    print(f"  PASS: Both bookings returned same ID ({appt_id1})")
    
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT service_type FROM service_requests WHERE id = %s;", (appt_id1,))
            row = cursor.fetchone()
            svc = row["service_type"]
            print(f"  Merged service_type: '{svc}'")
            assert "Oil Change" in svc
            assert "AC change" in svc
            print("  PASS: Both services merged")
    
    print()
    print("ALL TESTS PASSED")

if __name__ == "__main__":
    test_multi_service_merge()
