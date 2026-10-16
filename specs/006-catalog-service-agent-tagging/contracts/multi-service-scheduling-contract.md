# Contract: Multi-Service Availability & Back-to-Back Booking

**Feature**: `006-catalog-service-agent-tagging`  
**Components**: Telephony Voice Agent, Booking Service, Availability Engine  

---

## 1. Check Availability for Multiple Services

### Internal Python Interface
```python
def check_availability(
    service_type: Optional[str] = None,
    service_types: Optional[list[str]] = None,
    preferred_date: Optional[str] = None,
    preferred_time: Optional[str] = None,
    booking_type: str = "appointment",
) -> list[str]:
    """
    Checks available slots for single or multiple services.
    - If single qualified technician is free for sum(durations), prioritizes single-technician slots.
    - If no single technician can perform all services, searches for contiguous back-to-back slots
      (0-min buffer) across qualified specialists concluding strictly before closing hour.
    """
```

### Telephony Tool Call (`check_availability`)
```json
{
  "name": "check_availability",
  "arguments": {
    "preferred_date": "2026-10-16",
    "preferred_time": "10:00 AM",
    "service_types": ["Oil Change", "Brake Replacement"],
    "booking_type": "appointment"
  }
}
```

### Telephony Tool Response (Single Qualified Agent Available)
```json
{
  "success": true,
  "allocation_type": "single_agent",
  "assigned_agent_name": "John Doe",
  "total_duration_minutes": 90,
  "available_slots": ["2026-10-16 10:00:00", "2026-10-16 13:00:00"],
  "message": "The requested time (10:00 AM) IS AVAILABLE in our schedule with technician John Doe who can perform both services! Total visit duration is 90 minutes concluding at 11:30 AM."
}
```

### Telephony Tool Response (Split Back-to-Back Agents)
```json
{
  "success": true,
  "allocation_type": "back_to_back",
  "schedule_breakdown": [
    {
      "service": "Oil Change",
      "technician": "John Doe",
      "start_time": "10:00 AM",
      "end_time": "10:30 AM",
      "duration_minutes": 30
    },
    {
      "service": "Brake Replacement",
      "technician": "Sarah Jenkins",
      "start_time": "10:30 AM",
      "end_time": "11:30 AM",
      "duration_minutes": 60
    }
  ],
  "total_duration_minutes": 90,
  "available_slots": ["2026-10-16 10:00:00"],
  "message": "We have back-to-back availability starting at 10:00 AM! John will take care of your Oil Change from 10:00 to 10:30 AM, and Sarah will handle your Brake Replacement immediately after from 10:30 to 11:30 AM."
}
```

---

## 2. Book Multi-Service Appointment

### Telephony Tool Call (`book_appointment`)
```json
{
  "name": "book_appointment",
  "arguments": {
    "phone": "5551234567",
    "customer_name": "Alice Smith",
    "appointment_datetime": "2026-10-16 10:00:00",
    "service_types": ["Oil Change", "Brake Replacement"],
    "make": "Toyota",
    "model": "RAV4",
    "year": 2022
  }
}
```

### Response
```json
{
  "success": true,
  "visit_group_id": "f81d4fae-7dec-11d0-a765-00a0c91e6bf6",
  "service_request_ids": [101, 102],
  "booking_time": "2026-10-16 10:00:00",
  "expected_end_time": "11:30 AM",
  "allocation_type": "back_to_back",
  "message": "Your visit to CBA Auto is confirmed for October 16 starting at 10:00 AM: John will perform your Oil Change from 10:00 to 10:30 AM, followed immediately by Brake Replacement with Sarah from 10:30 to 11:30 AM."
}
```
