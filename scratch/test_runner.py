import pytest
import sys

if __name__ == "__main__":
    sys.exit(pytest.main(["tests/test_portal_api.py", "-k", "test_cannot_assign_agent_for_completed_service_request", "-o", "cache_dir=scratch/.pytest_cache"]))
