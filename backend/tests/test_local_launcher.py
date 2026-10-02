import os

from backend.local import configure_local_environment


def test_local_launcher_preserves_explicit_desktop_connection(monkeypatch):
    monkeypatch.setenv("RLB_CONTROL_PLANE_URL", "https://control.example")
    monkeypatch.setenv("RLB_DEVICE_TOKEN", "device-token")
    monkeypatch.setenv("RLB_DESKTOP_ORIGIN", "http://127.0.0.1:45678")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "inherited-secret")
    monkeypatch.setenv("LOCAL_DATA_DIR", "old-data")

    configure_local_environment(
        {"SUPABASE_URL": "https://local-config.example", "RLB_DEVICE_TOKEN": None},
        ["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "RLB_DEVICE_TOKEN", "RLB_CONTROL_PLANE_URL"],
        "app-data",
    )

    assert os.environ["ENVIRONMENT"] == "development"
    assert os.environ["RLB_CONTROL_PLANE_URL"] == "https://control.example"
    assert os.environ["RLB_DEVICE_TOKEN"] == "device-token"
    assert os.environ["RLB_DESKTOP_ORIGIN"] == "http://127.0.0.1:45678"
    assert "SUPABASE_SERVICE_ROLE_KEY" not in os.environ
    assert os.environ["LOCAL_DATA_DIR"] == "app-data"
