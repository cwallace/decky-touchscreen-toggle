import asyncio
import sys

import pytest
import main
from conftest import FakeHelper, device, mutations


async def test_one_switch_disables_all_and_enables_all(plugin):
    fake = plugin.install_helper(
        FakeHelper([device(), device("input9", "ELAN", "hid")])
    )
    result = await plugin.set_enabled(False)
    assert result["ok"] and result["enabled"] is False and not result["mixed"]
    assert [c[-2:] for c in mutations(fake)] == [["off", "input3"], ["off", "input9"]]
    assert (await plugin.set_enabled(True))["enabled"] is True
    assert all(not d["inhibited"] for d in fake.devices)


async def test_status_mixed_is_not_all_off(plugin):
    plugin.install_helper(FakeHelper([device(), device("input9", inhibited=True)]))
    result = await plugin.get_status()
    assert result["mixed"] and not result["enabled"]
    assert result["message"] == "Some touchscreens disabled."


async def test_empty_is_unavailable_and_never_mutates(plugin):
    fake = plugin.install_helper(FakeHelper([]))
    assert (await plugin.get_status())["state"] == "unavailable"
    assert not (await plugin.set_enabled(False))["ok"]
    assert not mutations(fake)


async def test_unsupported_is_disclosed_not_mutated(plugin):
    unsupported = device(
        "input8", supported=False, inhibited=None, reason="missing attribute"
    )
    fake = plugin.install_helper(FakeHelper([device(), unsupported]))
    result = await plugin.set_enabled(False)
    assert result["ok"] and result["unsupported"][0]["id"] == "input8"
    assert "supported" in result["message"].lower()
    assert len(mutations(fake)) == 1


@pytest.mark.parametrize("invalid", [None, 0, 1, "false", {}, []])
async def test_boolean_only(plugin, invalid):
    fake = plugin.install_helper(FakeHelper([device()]))
    assert not (await plugin.set_enabled(invalid))["ok"]
    assert not fake.calls


async def test_already_target_is_idempotent(plugin):
    fake = plugin.install_helper(FakeHelper([device()]))
    assert (await plugin.set_enabled(True))["changed"] == 0
    assert not mutations(fake)


async def test_failed_second_write_rolls_back_first(plugin):
    fake = plugin.install_helper(
        FakeHelper([device(), device("input9")], fail_once={"input9"})
    )
    result = await plugin.set_enabled(False)
    assert not result["ok"] and result["rollback"] == "complete"
    assert all(not d["inhibited"] for d in fake.devices)


async def test_false_success_is_rejected(plugin):
    class IgnoresWrites(FakeHelper):
        async def run(self, argv, timeout):
            result = await super().run(argv, timeout)
            for d in self.devices:
                d["inhibited"] = False
            return result

    plugin.install_helper(IgnoresWrites([device()]))
    assert not (await plugin.set_enabled(False))["ok"]


async def test_unload_restores_only_owned_disabled_devices(plugin):
    fake = plugin.install_helper(
        FakeHelper([device(), device("input9", inhibited=True)])
    )
    await plugin._main()
    assert not mutations(fake)
    await plugin.set_enabled(False)
    await plugin._unload()
    assert fake.devices[0]["inhibited"] is False
    assert fake.devices[1]["inhibited"] is True


async def test_unload_does_not_write_reused_input_id(plugin):
    fake = plugin.install_helper(FakeHelper([device()]))
    await plugin.set_enabled(False)
    fake.devices[0]["name"] = "Different touch device"
    before = len(mutations(fake))
    await plugin._unload()
    assert len(mutations(fake)) == before


async def test_readback_failure_keeps_recovery_ownership(plugin, monkeypatch):
    fake = plugin.install_helper(FakeHelper([device()]))
    original = main._fetch_devices
    reads = 0

    async def fail_after_write():
        nonlocal reads
        reads += 1
        if mutations(fake):
            raise main.HelperError("status unavailable")
        return await original()

    monkeypatch.setattr(main, "_fetch_devices", fail_after_write)
    result = await plugin.set_enabled(False)
    assert not result["ok"]
    assert "input3" in plugin._session_disabled


async def test_rollback_never_writes_replacement_device(plugin):
    class ReplaceAfterFailure(FakeHelper):
        async def run(self, argv, timeout):
            result = await super().run(argv, timeout)
            if argv[-2:] == ["off", "input9"]:
                self.devices[0]["name"] = "Replacement"
            return result

    fake = plugin.install_helper(
        ReplaceAfterFailure([device(), device("input9")], fail_once={"input9"})
    )
    result = await plugin.set_enabled(False)
    assert not result["ok"]
    assert not any(c[-2:] == ["on", "input3"] for c in mutations(fake))


async def test_unload_waits_for_inflight_disable(plugin):
    started, release = asyncio.Event(), asyncio.Event()

    class SlowWrite(FakeHelper):
        async def run(self, argv, timeout):
            if argv[-2:] == ["off", "input3"]:
                started.set()
                await release.wait()
            return await super().run(argv, timeout)

    fake = plugin.install_helper(SlowWrite([device()]))
    disable = asyncio.create_task(plugin.set_enabled(False))
    await started.wait()
    unload = asyncio.create_task(plugin._unload())
    await asyncio.sleep(0)
    release.set()
    await asyncio.gather(disable, unload)
    assert fake.devices[0]["inhibited"] is False


async def test_all_targets_are_verified_not_just_written_targets(plugin):
    class ExternalChange(FakeHelper):
        async def run(self, argv, timeout):
            result = await super().run(argv, timeout)
            if argv[-2:] == ["off", "input9"]:
                self.devices[0]["inhibited"] = False
            return result

    plugin.install_helper(ExternalChange([device(inhibited=True), device("input9")]))
    assert not (await plugin.set_enabled(False))["ok"]


async def test_operations_are_serialized(plugin):
    fake = plugin.install_helper(FakeHelper([device(), device("input9")]))
    a, b = await asyncio.gather(plugin.set_enabled(False), plugin.set_enabled(True))
    assert a["ok"] and b["ok"]
    assert all(not d["inhibited"] for d in fake.devices)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"ok": True},
        {"ok": False, "devices": []},
        {"ok": True, "devices": [device(), device()]},
        {"ok": True, "devices": [dict(device(), id="../input1")]},
        {"ok": True, "devices": [dict(device(), inhibited=1)]},
    ],
)
def test_malformed_status_refused(payload):
    with pytest.raises(main.HelperError):
        main._validate_devices(payload)


async def test_real_subprocess_transport_and_timeout():
    code, out, err = await main._run_helper(
        [sys.executable, "-c", "print('transport-ok')"], 2
    )
    assert code == 0 and out.strip() == "transport-ok" and err == ""
    with pytest.raises(main.HelperError, match="timed out"):
        await main._run_helper(
            [sys.executable, "-c", "import time;time.sleep(5)"], 0.02
        )


async def test_missing_helper_is_honest(plugin, monkeypatch):
    monkeypatch.setattr(main, "HELPER", "/nonexistent/touchscreen-helper")
    result = await plugin.get_status()
    assert not result["ok"] and "not installed" in result["error"]


async def test_status_command_failure_is_error(plugin, monkeypatch):
    async def failed(argv, timeout):
        return 1, "", "denied"

    monkeypatch.setattr(main, "_run_helper", failed)
    result = await plugin.get_status()
    assert not result["ok"] and result["state"] == "error"
