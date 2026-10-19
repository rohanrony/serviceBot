# Contracts
GET/POST /api/v1/portal/config: business_profile object plus existing business_name and optional credential-free HTTP(S) portal_base_url (no query/fragment); regenerate_business_prompt boolean accepted only on save. Invalid profile: 422, no writes/sync.
POST /portal/service-requests: optional vehicle, intake_data object, existing customer/service_request. PUT /portal/service-requests/{id}: optional vehicle_details, optional intake_data; omitted intake preserved. Validation: 400 with actionable field label; no customer/request writes.
Voice create_service_request/book_appointment/request_callback: optional intake_data object or intake_data_json JSON string. Validation before mutations. get_service_fields adds intake_fields and vehicle_details=false when automotive disabled.
