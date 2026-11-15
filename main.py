"""Decky backend for a single global physical-touchscreen toggle.

The backend never writes sysfs itself.  It asks the fixed, separately
installed helper (``/usr/local/libexec/ogui-touchscreen-control``) for the
current device list and performs mutations only through the helper's narrow
passwordless-sudo boundary.  A mutation is reported as successful only after
an independent status read-back confirms every device this operation changed.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import signal
from typing import Any, Dict, List, Optional, Tuple

import decky

HELPER = "/usr/local/libexec/ogui-touchscreen-control"
SUDO = "/usr/bin/sudo"
INPUT_RE = re.compile(r"input[0-9]{1,6}\Z")
STATUS_TIMEOUT = 5.0
MUTATE_TIMEOUT = 20.0
MAX_OUTPUT_BYTES = 64 * 1024


class HelperError(Exception):
    """A helper invocation or payload failed; the message is user-facing."""


def _log() -> Any:
    return getattr(decky, "logger", None)


def _identity(device: Dict[str, Any]) -> Dict[str, str]:
    return {
        "id": device["id"],
        "name": device["name"],
        "driver": device["driver"],
    }


def _same_identity(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
    return (
        left.get("id") == right.get("id")
        and left.get("name") == right.get("name")
        and left.get("driver") == right.get("driver")
    )


def _public_device(device: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": device["id"],
        "name": device["name"],
        "driver": device["driver"],
        "inhibited": device["inhibited"],
    }


def _parse_payload(stdout: str) -> Optional[Dict[str, Any]]:
    if len(stdout) > MAX_OUTPUT_BYTES:
        raise HelperError("touchscreen helper returned an oversized response")
    text = stdout.strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        raise HelperError("touchscreen helper returned an invalid response")
    if not isinstance(payload, dict):
        raise HelperError("touchscreen helper returned an unexpected response")
    return payload


def _validate_devices(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    if payload.get("ok") is not True:
        raise HelperError("touchscreen helper did not report success")
    raw_devices = payload.get("devices")
    if not isinstance(raw_devices, list):
        raise HelperError("touchscreen helper response is missing the device list")
    devices: List[Dict[str, Any]] = []
    seen = set()
    for raw in raw_devices:
        if not isinstance(raw, dict):
            raise HelperError("touchscreen helper returned a malformed device entry")
        device_id = raw.get("id")
        if not isinstance(device_id, str) or not INPUT_RE.fullmatch(device_id):
            raise HelperError("touchscreen helper returned an invalid device id")
        if device_id in seen:
            raise HelperError("touchscreen helper returned a duplicate device id")
        seen.add(device_id)
        supported = raw.get("supported")
        if type(supported) is not bool:
            raise HelperError(
                "touchscreen helper returned a non-boolean supported flag"
            )
        inhibited = raw.get("inhibited")
        if supported:
            if type(inhibited) is not bool:
                raise HelperError(
                    "touchscreen helper returned a non-boolean inhibit state"
                )
        elif inhibited is not None:
            raise HelperError("touchscreen helper returned incomplete inhibit state")
        name = raw.get("name", "")
        driver = raw.get("driver", "")
        reason = raw.get("reason", "")
        if (
            not isinstance(name, str)
            or not isinstance(driver, str)
            or not isinstance(reason, str)
        ):
            raise HelperError("touchscreen helper returned malformed device metadata")
        devices.append(
            {
                "id": device_id,
                "name": name,
                "driver": driver,
                "supported": supported,
                "inhibited": inhibited,
                "reason": reason,
            }
        )
    devices.sort(key=lambda item: int(item["id"][5:]))
    return devices


def _summarize(devices: List[Dict[str, Any]]) -> Dict[str, Any]:
    supported = [device for device in devices if device["supported"]]
    unsupported = [device for device in devices if not device["supported"]]
    inhibited = [device for device in supported if device["inhibited"]]
    enabled = bool(supported) and not inhibited
    mixed = bool(inhibited) and len(inhibited) < len(supported)

    if not supported:
        message = "No supported physical touchscreen detected."
        if unsupported:
            message += " Detected touchscreen hardware lacks kernel inhibit support."
    elif enabled:
        message = "All touchscreens enabled."
    elif mixed:
        message = "Some touchscreens disabled."
    else:
        message = "All touchscreens disabled."

    if supported and unsupported:
        message = message.replace("All touchscreens", "All supported touchscreens")

    result: Dict[str, Any] = {
        "ok": True,
        "state": "ready" if supported else "unavailable",
        "enabled": enabled if supported else None,
        "mixed": mixed,
        "message": message,
        "devices": [_public_device(device) for device in supported],
        "unsupported": [
            {"id": device["id"], "name": device["name"], "reason": device["reason"]}
            for device in unsupported
        ],
    }
    if unsupported:
        result["unsupported_message"] = (
            f"{len(unsupported)} detected touchscreen(s) cannot be controlled "
            "because the kernel inhibit attribute is unavailable."
        )
    return result


def _failure(message: str, **extra: Any) -> Dict[str, Any]:
    result: Dict[str, Any] = {"ok": False, "state": "error", "error": message}
    result.update(extra)
    return result


def _sudo_error(stderr: str, returncode: int) -> str:
    lowered = stderr.lower()
    if "password is required" in lowered or "no tty present" in lowered:
        return (
            "Touchscreen helper authorization is unavailable: passwordless sudo "
            "for the helper is not configured."
        )
    if "not allowed" in lowered:
        return "The current user is not authorized to run the touchscreen helper."
    if "command not found" in lowered or "no such file" in lowered:
        return "Touchscreen helper is not installed."
    return f"Touchscreen helper command failed (exit {returncode})."


async def _terminate(proc: "asyncio.subprocess.Process") -> None:
    if proc.returncode is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        try:
            proc.kill()
        except ProcessLookupError:
            pass
    try:
        await asyncio.wait_for(proc.wait(), 5.0)
    except asyncio.TimeoutError:
        pass


async def _run_helper(argv: List[str], timeout: float) -> Tuple[int, str, str]:
    """Run one helper command with argv (never a shell), bounded and reaped."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
            start_new_session=True,
        )
    except FileNotFoundError:
        raise HelperError("Touchscreen helper is not installed.")
    except OSError as exc:
        raise HelperError(
            f"Touchscreen helper could not be started: {exc.strerror or exc}"
        )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        await _terminate(proc)
        raise HelperError("Touchscreen helper timed out.")
    except asyncio.CancelledError:
        await _terminate(proc)
        raise
    if len(stdout) > MAX_OUTPUT_BYTES:
        raise HelperError("Touchscreen helper returned an oversized response")
    return (
        proc.returncode if proc.returncode is not None else -1,
        stdout.decode("utf-8", "replace"),
        stderr.decode("utf-8", "replace"),
    )


async def _fetch_devices() -> List[Dict[str, Any]]:
    returncode, stdout, _stderr = await _run_helper([HELPER, "status"], STATUS_TIMEOUT)
    payload = _parse_payload(stdout)
    if returncode != 0:
        if payload is not None and isinstance(payload.get("error"), str):
            raise HelperError(payload["error"])
        raise HelperError(f"Touchscreen status check failed (exit {returncode}).")
    if payload is None:
        raise HelperError("Touchscreen helper returned no status.")
    return _validate_devices(payload)


async def _mutate(device_id: str, inhibit: bool) -> None:
    """Inhibit (off) or restore (on) one supported touchscreen through sudo."""
    action = "off" if inhibit else "on"
    returncode, stdout, stderr = await _run_helper(
        [SUDO, "-n", "--", HELPER, "set", action, device_id], MUTATE_TIMEOUT
    )
    payload = _parse_payload(stdout)
    if returncode != 0:
        if payload is not None and isinstance(payload.get("error"), str):
            raise HelperError(payload["error"])
        raise HelperError(_sudo_error(stderr, returncode))
    if payload is None or payload.get("ok") is not True:
        raise HelperError("Touchscreen helper did not confirm the change.")


class Plugin:
    def __init__(self) -> None:
        self._lock: Optional[asyncio.Lock] = None
        self._session_disabled: Dict[str, Dict[str, str]] = {}
        self._closing = False

    def _mutation_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def get_status(self) -> Dict[str, Any]:
        async with self._mutation_lock():
            try:
                return _summarize(await _fetch_devices())
            except HelperError as exc:
                return _failure(str(exc))

    async def _current(self, original: Dict[str, Any]) -> Dict[str, Any]:
        for current in await _fetch_devices():
            if current["id"] == original["id"]:
                if current["supported"] and _same_identity(original, current):
                    return current
                break
        raise HelperError(
            f"{original['id']}: touchscreen disappeared or changed identity"
        )

    def _reconcile_session(self, observed: List[Dict[str, Any]]) -> None:
        for current in observed:
            identity = self._session_disabled.get(current["id"])
            if identity and (
                not _same_identity(identity, current) or current["inhibited"] is False
            ):
                self._session_disabled.pop(current["id"], None)

    async def _rollback(self, applied: List[Tuple[Dict[str, Any], bool]]) -> str:
        if not applied:
            return "not_needed"
        failed = []
        for original, prior in reversed(applied):
            try:
                current = await self._current(original)
                if current["inhibited"] != prior:
                    try:
                        await _mutate(original["id"], prior)
                    except HelperError:
                        pass  # Only independent readback can establish restoration.
                current = await self._current(original)
                if current["inhibited"] != prior:
                    raise HelperError("pre-operation state not restored")
            except HelperError as exc:
                failed.append(f"{original['id']}: {exc}")
        return "complete" if not failed else "incomplete: " + "; ".join(failed)

    async def set_enabled(self, enabled: Any) -> Dict[str, Any]:
        if type(enabled) is not bool:
            return _failure("The touchscreen toggle requires a boolean value.")
        async with self._mutation_lock():
            if self._closing:
                return _failure("Touchscreen plugin is unloading; no change was made.")
            applied: List[Tuple[Dict[str, Any], bool]] = []
            try:
                devices = await _fetch_devices()
                supported = [d for d in devices if d["supported"]]
                if not supported:
                    result = _summarize(devices)
                    result.update(ok=False, error=result["message"])
                    return result
                desired = not enabled
                for original in supported:
                    if original["inhibited"] == desired:
                        continue
                    current = await self._current(original)
                    if current["inhibited"] == desired:
                        continue
                    applied.append((original, current["inhibited"]))
                    # Keep ownership even if a command times out after writing and
                    # both verification and rollback fail. Never infer from stale status.
                    if desired and not current["inhibited"]:
                        self._session_disabled[original["id"]] = _identity(original)
                    await _mutate(original["id"], desired)
                observed = await _fetch_devices()
                observed_supported = [d for d in observed if d["supported"]]
                if (
                    {d["id"] for d in observed_supported}
                    != {d["id"] for d in supported}
                    or any(
                        not any(_same_identity(a, b) for b in observed_supported)
                        for a in supported
                    )
                    or any(d["inhibited"] != desired for d in observed_supported)
                ):
                    raise HelperError(
                        "Touchscreen state read-back did not confirm every target."
                    )
                self._reconcile_session(observed)
                result = _summarize(observed)
                result["changed"] = len(applied)
                return result
            except (HelperError, asyncio.CancelledError) as exc:
                rollback = await asyncio.shield(self._rollback(applied))
                try:
                    self._reconcile_session(await _fetch_devices())
                except HelperError:
                    pass
                if isinstance(exc, asyncio.CancelledError):
                    raise
                return _failure(
                    f"Could not change every touchscreen: {exc}", rollback=rollback
                )

    async def _main(self) -> None:
        logger = _log()
        if logger:
            logger.info("Touchscreen toggle loaded; no device state was changed.")

    async def _restore_owned(self) -> None:
        async with self._mutation_lock():
            # Snapshot only after in-flight disable/rollback has completed.
            failures = []
            for identity in list(self._session_disabled.values()):
                try:
                    current = await self._current(identity)
                    if current["inhibited"]:
                        await _mutate(current["id"], False)
                    current = await self._current(identity)
                    if current["inhibited"]:
                        raise HelperError(
                            f"{current['id']}: unload restoration unverified"
                        )
                    self._session_disabled.pop(current["id"], None)
                except HelperError as exc:
                    failures.append(str(exc))
            if failures:
                raise HelperError("; ".join(failures))

    async def _unload(self) -> None:
        self._closing = True
        try:
            # Decky 3.3.1 kills backend processes after five seconds on stop.
            # Leave time for subprocess cleanup; abrupt termination cannot guarantee restore.
            await asyncio.wait_for(self._restore_owned(), 3.5)
        except (HelperError, asyncio.TimeoutError) as exc:
            logger = _log()
            if logger:
                logger.error(
                    f"Touchscreen unload restoration incomplete: {exc}. Reboot restores touch."
                )

    async def _uninstall(self) -> None:
        await self._unload()
