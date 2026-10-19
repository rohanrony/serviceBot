# Business terminology audit

## Findings and resulting behavior

| Area | Automotive coupling found | Result |
| --- | --- | --- |
| Services, assignment, analytics and lifecycle trace | Technician headers, defaults, stored role display and messages | Agent in app-owned copy and legacy Technician role rendering; existing route/DOM/function names remain compatible |
| Request intake | Portal/API required make/model/year; booking fallbacks fabricated vehicles | Config > Business controls automotive collection and custom text/number intake; generic requests persist without a vehicle |
| Storage | Vehicle relationship was the only structured context | Additive `service_requests.intake_data` JSONB with object constraint; transactional create/edit and guarded rollback |
| Voice and graph intake | Fixed automotive requirements and fields | Shared profile validation, configured get_service_fields schema and optional intake_data_json tool argument |
| Prompts and summaries | Hardcoded Davidson identity, automotive summary instructions and operational prose | Profile-aware summary and explicit Config prompt/greeting regeneration; generated hours and lead-time policies stay synchronized |
| Notifications | Vehicle labels and hardcoded Davidson escalation URLs | Neutral Details labels, intake in booking/multi-service/reminder data, configurable Portal URL |
| Catalog selection | New-request options hardcoded to automotive services | Actual configured catalog populates the form; automotive example catalog is explicitly labeled |

## Compatibility and configuration boundaries

Legacy `vehicles`, `vehicle_id`, `req_vehicle_details`, `VehicleDetails`, `make/model/year/vin`, `/analytics/technicians`, DOM identifiers and mechanic/technician adapter names remain compatibility contracts. Generic intake does not depend on a vehicle row. Existing automotive records remain readable and profile changes never erase historical custom values. Clearing a currently configured optional field removes its value; removed fields remain historical data.

Business-authored catalog entries, knowledge documents, prompts and custom notification templates remain operator-controlled content. Config explains reviewing them when switching businesses. Prompt regeneration is explicit because it replaces customized instructions. No claim is made that arbitrary industry workflows beyond configurable text/number intake and the existing appointment/callback workflow are implemented.

The first release also needs the application migration and updated ElevenLabs tool definitions containing intake_data_json. Subsequent field/business changes use Config and get_service_fields. Tool schema synchronization and live-provider delivery were not executed in this task.

## Source evidence boundary

The code graph could not index this repository under its configured allowed roots. Investigation used direct source reads, literal searches and executed tests. This is a task-directed source audit, not an exhaustive proof of every business-specific document or data value. No existing production configuration, schema or provider agent was changed.

## Change isolation

The feature was reconstructed and tested on `codex/configurable-business-intake` at `/private/tmp/voice-business-intake`, based on 4a1f6fa. Existing OAuth, authenticated-webhook, simulation-campaign, canonical-catalog and availability-menu work in the original dirty checkout was excluded. A calendar test now freezes both application clock boundaries so its fixed appointment date remains deterministic.
