from src.transport.ws_layer import WebSocketTransport


def test_connected_client_ids_skips_empty_sets():
    transport = WebSocketTransport()
    transport.active_connections = {
        "headset_01": {"sock-a"},
        "ghost": set(),
        "woz_web_console": {"sock-b"},
    }
    assert transport.connected_client_ids() == ["headset_01", "woz_web_console"]
