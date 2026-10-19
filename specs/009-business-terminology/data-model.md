# Data model
BusinessProfile: industry (1..100 chars), collect_vehicle_details (bool), intake_fields (0..20). Field: key (snake_case, 1..40), label (1..80), type (text|number), required (bool); keys unique. Values: text <=2000 chars or finite number. Unknown submitted keys rejected. Historical keys retained on edit.
service_requests.intake_data: object JSONB, default {}. Legacy vehicle relationship optional and preserved on edits when omitted. Guarded rollback refuses to drop nonempty intake.
