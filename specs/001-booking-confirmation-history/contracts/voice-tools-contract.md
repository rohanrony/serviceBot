# Voice Tools Contract: ElevenLabs & Telephony Integration

**Feature**: `001-booking-confirmation-history`
**Endpoint**: `POST /api/v1/voice/tools`

## 1. `get_customer_appointments`

### Description
Retrieves upcoming and active scheduled appointments for a customer using their 10-digit phone number. Enhanced to include the full issue description, service duration, and vehicle specifications.

### Request Payload
```json
{
  "name": "get_customer_appointments",
  "arguments": {
    "phone": "5551234567"
  }
}
```

### Response Payload
```json
{
  "success": true,
  "appointments": [
    {
      "id": 1042,
      "appointment_datetime": "2026-10-02 10:00:00",
      "service_type": "Oil Change",
      "issue_description": "Engine oil change and multipoint inspection",
      "duration_minutes": 45,
      "status": "pending",
      "year": 2021,
      "make": "Toyota",
      "model": "Camry"
    }
  ],
  "message": "Found 1 upcoming appointment for phone number 5551234567."
}
```

---

## 2. `create_service_request`

### Description
Creates or updates a service request. When called multiple times in the same active call session (or for the same customer/phone within 15 minutes), updates the existing tentative booking rather than creating a duplicate slot.

### Request Payload
```json
{
  "name": "create_service_request",
  "arguments": {
    "customer_name": "John Doe",
    "phone": "5551234567",
    "make": "Toyota",
    "model": "Camry",
    "year": 2021,
    "issue_description": "Oil Change and brake inspection",
    "service_type": "Oil Change",
    "booking_type": "appointment",
    "booking_time": "2026-10-02 10:30:00",
    "call_sid": "CA1234567890abcdef"
  }
}
```

### Response Payload (New Booking)
```json
{
  "success": true,
  "service_request_id": 1042,
  "booking_type": "appointment",
  "booking_time": "2026-10-02 10:30:00",
  "duration_minutes": 60,
  "expected_end_time": "2026-10-02 11:30:00",
  "message": "Service request booked as an appointment from 10:30 AM to approximately 11:30 AM. Calendar projection and notifications are queued. Estimated rate: $79-$119. Please remind the customer that the appointment is booked for this period, but is likely to extend depending on service findings."
}
```

### Response Payload (In-Session Update on Time Change)
```json
{
  "success": true,
  "service_request_id": 1042,
  "is_update": true,
  "previous_booking_time": "2026-10-02 10:00:00",
  "booking_time": "2026-10-02 10:30:00",
  "expected_end_time": "2026-10-02 11:30:00",
  "message": "Updated existing appointment from 10:00 AM to 10:30 AM (expected completion by 11:30 AM). Calendar slot updated successfully."
}
```

---

## 3. `consolidate_appointment_service`

### Description
Consolidates an additional service or symptom into an existing upcoming appointment for the same vehicle, recalculating total duration and adjusting the calendar event.

### Request Payload
```json
{
  "name": "consolidate_appointment_service",
  "arguments": {
    "appointment_id": 1042,
    "phone": "5551234567",
    "additional_issue": "Brake squeak and rotor check",
    "additional_service_type": "Brake Inspection",
    "additional_duration_minutes": 45
  }
}
```

### Response Payload (Capacity Available)
```json
{
  "success": true,
  "appointment_id": 1042,
  "combined_issues": "Oil Change and multipoint inspection; Brake squeak and rotor check",
  "new_duration_minutes": 90,
  "start_time": "2026-10-02 10:00:00",
  "expected_end_time": "2026-10-02 11:30:00",
  "message": "Appointment 1042 successfully consolidated. Total scheduled duration is now 90 minutes (10:00 AM to 11:30 AM). Calendar reservation extended. Please advise the customer that the visit is booked for this window but is likely to extend."
}
```

### Response Payload (Capacity Blocked)
```json
{
  "success": false,
  "capacity_blocked": true,
  "appointment_id": 1042,
  "message": "Technician schedule cannot accommodate the extra 45 minutes after 10:45 AM due to an existing booking at 11:00 AM. Please offer the customer to either: 1) Move the combined 90-minute visit to an open slot (e.g., 1:00 PM), or 2) Book a separate appointment for the brake inspection."
}
```
