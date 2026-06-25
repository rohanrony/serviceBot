from fastapi.testclient import TestClient
from serviceBot.main import app

client = TestClient(app)

def test_static_dashboard_serves_html():
    # Attempt to fetch portal home page
    response = client.get("/portal")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    html_content = response.text
    
    # Check that key containers/tabs of the specification exist in index.html
    assert "VoiceAI" in html_content or "Configuration Portal" in html_content
    assert 'id="dashboard-view"' in html_content
    assert 'id="services-view"' in html_content
    assert 'id="keys-view"' in html_content
