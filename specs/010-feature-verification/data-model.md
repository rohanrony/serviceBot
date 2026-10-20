# Evidence model

Receipt schema 1 binds head/base SHAs, Git tree and dependency-file digests, installed package
inventory, timestamps, tool versions, command results and remaining live requirements.
Per-suite collection/execution manifests share a nonce. Executions record every phase and
layer. Artifact paths are relative to the receipt directory and their bytes are hashed.
Receipt status is failed until every mandatory check passes. Browser totals are a subset
of E2E, with explicit collected/executed IDs. No receipt replaces human test-quality review.
