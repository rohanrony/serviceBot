# Contract: Portal Service Agent Tagging API

**Feature**: `006-catalog-service-agent-tagging`  
**Endpoint Base**: `/api/v1/portal`  

---

## 1. List Services with Assigned Agents

### Request
`GET /api/v1/portal/services`

### Response (200 OK)
```json
[
  {
    "id": 1,
    "name": "Brake Pads Replacement",
    "description": "Replacement of front or rear brake pads and rotor inspection.",
    "price_range": "$150 - $250",
    "duration_minutes": 60,
    "req_customer_name": true,
    "req_phone_number": true,
    "req_vehicle_details": true,
    "req_issue_description": true,
    "req_location": true,
    "assigned_agent_ids": [2, 5],
    "assigned_agent_names": ["Sarah Jenkins", "Dave Wilson"],
    "is_open_to_all_agents": false
  },
  {
    "id": 2,
    "name": "General Diagnostic",
    "description": "Comprehensive engine and OBD-II multi-point check.",
    "price_range": "$89 - $120",
    "duration_minutes": 45,
    "req_customer_name": true,
    "req_phone_number": true,
    "req_vehicle_details": true,
    "req_issue_description": true,
    "req_location": true,
    "assigned_agent_ids": [],
    "assigned_agent_names": [],
    "is_open_to_all_agents": true
  }
]
```

---

## 2. Create Service with Assigned Agents

### Request
`POST /api/v1/portal/services`

```json
{
  "name": "Transmission Fluid Flush",
  "description": "Complete fluid drain and flush with synthetic fluid.",
  "price_range": "$180 - $260",
  "duration_minutes": 60,
  "req_customer_name": true,
  "req_phone_number": true,
  "req_vehicle_details": true,
  "req_issue_description": true,
  "req_location": true,
  "agent_ids": [3, 7]
}
```

### Response (201 Created)
```json
{
  "id": 34,
  "name": "Transmission Fluid Flush",
  "assigned_agent_ids": [3, 7],
  "success": true
}
```

---

## 3. Update Service & Agent Tags

### Request
`PUT /api/v1/portal/services/{service_id}`

```json
{
  "name": "Transmission Fluid Flush",
  "description": "Complete fluid drain and flush with synthetic fluid.",
  "price_range": "$180 - $260",
  "duration_minutes": 60,
  "req_customer_name": true,
  "req_phone_number": true,
  "req_vehicle_details": true,
  "req_issue_description": true,
  "req_location": true,
  "agent_ids": [3]
}
```

### Response (200 OK)
```json
{
  "id": 34,
  "name": "Transmission Fluid Flush",
  "assigned_agent_ids": [3],
  "success": true
}
```
