# Research
Decision: additive request intake plus optional existing vehicle adapter. Rationale: vehicle_id is nullable already, but the portal and booking fallbacks fabricate vehicles; renaming tables would break deployed contracts. Alternative: label-only replacement fails for salons/consulting; destructive schema rename adds migration risk.
Decision: explicit prompt regeneration; preserve configured business content. Rationale: generated identity must be consistent without erasing customized operating policies on ordinary saves.
Graph indexing denied by tool allowed-root policy; direct source reads and literal searches used. No coverage completeness claim.
