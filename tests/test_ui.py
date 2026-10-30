from fastapi.testclient import TestClient
from serviceBot.main import app

client = TestClient(app)

def test_static_dashboard_serves_html():
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert 'type="email"' in response.text
    assert 'type="password"' in response.text

    protected = client.get("/portal/", follow_redirects=False)
    assert protected.status_code in (302, 303, 307, 308)
    assert protected.headers["location"].endswith("/")
