import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if "decky" not in sys.modules:
    decky = types.ModuleType("decky")
    logger = types.SimpleNamespace(
        info=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
        error=lambda *args, **kwargs: None,
        debug=lambda *args, **kwargs: None,
    )
    decky.logger = logger
    sys.modules["decky"] = decky

import main  # noqa: E402


def device(
    device_id="input3",
    name="Goodix Touchscreen",
    driver="goodix",
    supported=True,
    inhibited=False,
    reason="",
):
    return {
        "id": device_id,
        "name": name,
        "driver": driver,
        "supported": supported,
        "inhibited": inhibited,
        "reason": reason,
        "virtual": False,
    }


class FakeHelper:
    """Stateful stand-in for the installed helper, speaking its JSON contract."""

    def __init__(self, devices, fail_once=None):
        self.devices = [dict(item) for item in devices]
        self.fail_once = set(fail_once or ())
        self.calls = []

    def _status_payload(self):
        return {
            "ok": True,
            "version": "test",
            "devices": [dict(item) for item in self.devices],
        }

    def _find(self, device_id):
        for item in self.devices:
            if item["id"] == device_id:
                return item
        return None

    async def run(self, argv, timeout):
        self.calls.append(list(argv))
        if list(argv) == [main.HELPER, "status"]:
            return 0, json.dumps(self._status_payload()), ""
        assert list(argv[:5]) == [main.SUDO, "-n", "--", main.HELPER, "set"], argv
        action, device_id = argv[-2], argv[-1]
        assert action in ("on", "off")
        item = self._find(device_id)
        if item is None:
            return (
                1,
                json.dumps(
                    {
                        "ok": False,
                        "error": "device is not a discovered physical touchscreen",
                    }
                ),
                "",
            )
        if device_id in self.fail_once:
            self.fail_once.discard(device_id)
            return (
                1,
                json.dumps({"ok": False, "error": "simulated kernel rejection"}),
                "",
            )
        item["inhibited"] = action == "off"
        return (
            0,
            json.dumps(
                {
                    "ok": True,
                    "device": {
                        "id": device_id,
                        "name": item["name"],
                        "inhibited": item["inhibited"],
                    },
                }
            ),
            "",
        )


@pytest.fixture
def plugin(monkeypatch):
    instance = main.Plugin()

    def install(fake):
        async def run(argv, timeout):
            return await fake.run(argv, timeout)

        monkeypatch.setattr(main, "_run_helper", run)
        return fake

    instance.install_helper = install  # type: ignore[attr-defined]
    return instance


MUTATION_PREFIX = [main.SUDO, "-n", "--", main.HELPER, "set"]


def mutations(fake):
    return [call for call in fake.calls if call[:5] == MUTATION_PREFIX]
