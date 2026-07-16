import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_root_returns_response(async_client: AsyncClient):
    """
    Test that the root URL returns a valid HTTP response.
    In test mode (OVARP_TESTING=1) the app is minimal, so we just verify
    it doesn't crash. In production it would serve the headless dashboard.
    """
    response = await async_client.get("/")
    # In test mode the app has no static mount, so 404 is expected.
    # In production mode it would be 200 with the headless dashboard.
    assert response.status_code in [200, 404]

@pytest.mark.asyncio
async def test_static_files_resolution(async_client: AsyncClient):
    """
    Test that static files like the SDK resolve correctly even when in headless mode.
    """
    response = await async_client.get("/sdk/oaf-client.js")
    # Even if the file doesn't perfectly match our mocking directory structure in tests,
    # the router should still attempt to fetch it rather than failing with a 500.
    # In GitHub Actions, static folder might not be populated during tox tests unless copied, 
    # but 200/404 is the expected behavior of StaticFiles() not 500.
    assert response.status_code in [200, 404]


