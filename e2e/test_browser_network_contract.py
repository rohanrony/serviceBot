"""The browser uses captured QR bytes while ordinary local APIs remain native."""


def test_browser_captures_qr_gateway_without_following_provider_redirect(page, live_server):
    page.goto(f"{live_server}/health")
    result = page.evaluate("""async () => {
        const image = await fetch('/api/v1/portal/twilio/qr-code?data=offline-test-data');
        const bytes = Array.from(new Uint8Array(await image.arrayBuffer()));
        const agents = await fetch('/api/v1/portal/agents');
        return {
            status: image.status,
            redirected: image.redirected,
            contentType: image.headers.get('content-type'),
            signature: bytes.slice(0, 8),
            agentsStatus: agents.status,
            agents: await agents.json(),
        };
    }""")
    assert result["status"] == 200
    assert result["redirected"] is False
    assert result["contentType"] == "image/png"
    assert result["signature"] == [137, 80, 78, 71, 13, 10, 26, 10]
    assert result["agentsStatus"] == 200
    assert any(agent["name"] == "Taylor E2E" for agent in result["agents"])
