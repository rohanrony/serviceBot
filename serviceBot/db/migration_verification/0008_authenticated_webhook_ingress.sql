SELECT provider,event_id,conversation_id,payload_hash,verified_at
FROM authenticated_webhook_ingress
WHERE provider <> 'elevenlabs' OR event_id <> conversation_id
   OR payload_hash !~ '^[0-9a-f]{64}$';
SELECT provider,event_id,count(*) FROM authenticated_webhook_ingress
GROUP BY provider,event_id HAVING count(*) <> 1;
