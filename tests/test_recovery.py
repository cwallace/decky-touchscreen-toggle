import asyncio
import pytest
import main
from conftest import FakeHelper, device, mutations


async def test_missing_owned_touchscreen_does_not_prevent_restoring_others(plugin):
    fake = plugin.install_helper(FakeHelper([device(), device("input9")]))
    await plugin.set_enabled(False)
    fake.devices = [fake.devices[1]]
    await plugin._unload()
    assert fake.devices[0]["inhibited"] is False


async def test_unload_readback_failure_keeps_record_and_logs(plugin, monkeypatch):
    fake = plugin.install_helper(FakeHelper([device()]))
    await plugin.set_enabled(False)
    messages = []
    monkeypatch.setattr(main.decky.logger, "error", lambda s: messages.append(s))
    original = main._mutate

    async def ignored(device_id, inhibit):
        return None

    monkeypatch.setattr(main, "_mutate", ignored)
    await plugin._unload()
    assert "input3" in plugin._session_disabled
    assert messages and "incomplete" in messages[0]
    assert fake.devices[0]["inhibited"] is True
    monkeypatch.setattr(main, "_mutate", original)


async def test_cancellation_rolls_back_write(plugin):
    written = asyncio.Event()

    class CancelWrite(FakeHelper):
        async def run(self, argv, timeout):
            result = await super().run(argv, timeout)
            if argv[-2:] == ["off", "input3"]:
                written.set()
                await asyncio.Event().wait()
            return result

    fake = plugin.install_helper(CancelWrite([device()]))
    task = asyncio.create_task(plugin.set_enabled(False))
    await written.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert fake.devices[0]["inhibited"] is False


async def test_unloading_rejects_later_mutations(plugin):
    fake = plugin.install_helper(FakeHelper([device()]))
    await plugin._unload()
    assert not (await plugin.set_enabled(False))["ok"]
    assert not mutations(fake)
