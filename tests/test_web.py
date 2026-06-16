from work_agent.config import Config
from work_agent.frontends.web import _INDEX_HTML, create_app


def test_index_html_renders_app_name():
    assert "work-agent" in _INDEX_HTML
    assert "/ws" in _INDEX_HTML  # client connects to the websocket endpoint


def test_app_exposes_expected_routes():
    app = create_app(Config())
    paths = {getattr(r, "path", None) for r in app.routes}
    assert {"/", "/healthz", "/ws"} <= paths
