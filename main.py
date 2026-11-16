"""Decky backend for a single global physical-touchscreen toggle.

The backend never writes sysfs itself.  It runs the helper bundled inside the
plugin (``bin/touchscreen-control``) with a fixed interpreter and argv, and
performs mutations only through that helper's narrow, re-validated interface.
Decky starts this backend as root because ``plugin.json`` declares the
``root`` flag.  A mutation is reported as successful only after an independent
status read-back confirms every device this operation changed.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import signal
import tempfile
import time
from typing import Any, Dict, List, Optional, Tuple

import decky

PYTHON = "/usr/bin/python3"
HELPER_NAME = "touchscreen-control"
INPUT_RE = re.compile(r"input[0-9]{1,6}\Z")
APP_ID_RE = re.compile(r"[0-9]{1,20}\Z")
STATUS_TIMEOUT = 5.0
MUTATE_TIMEOUT = 20.0
MAX_OUTPUT_BYTES = 64 * 1024

SETTINGS_FILENAME = "game_rules.json"
SETTINGS_VERSION = 1
# Tests and embedders may point this at an isolated directory.
SETTINGS_DIR: Optional[str] = None
# A frontend heartbeat renews this lease; a lost frontend lets it expire.
LEASE_SECONDS = 15.0
WATCHDOG_INTERVAL = 2.0


class HelperError(Exception):
    """A helper invocation or payload failed; the message is user-facing."""


def _log() -> Any:
    return getattr(decky, "logger", None)


def _plugin_dir() -> str:
    """The installed plugin directory Decky provides; never the CWD."""
    configured = getattr(decky, "DECKY_PLUGIN_DIR", None)
    if not (isinstance(configured, str) and configured):
        configured = os.environ.get("DECKY_PLUGIN_DIR")
    if not (isinstance(configured, str) and os.path.isabs(configured)):
        raise HelperError(
            "Decky plugin directory is unavailable; the touchscreen helper "
            "cannot be located."
        )
    return configured


def _helper_path() -> str:
    return os.path.join(_plugin_dir(), "bin", HELPER_NAME)


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


def _valid_app_id(value: Any) -> bool:
    """App ids are exact unsigned decimal strings; never coerce or truncate."""
    return isinstance(value, str) and APP_ID_RE.fullmatch(value) is not None


def _settings_dir() -> str:
    if SETTINGS_DIR:
        return SETTINGS_DIR
    configured = getattr(decky, "DECKY_PLUGIN_SETTINGS_DIR", None)
    if isinstance(configured, str) and configured:
        return configured
    configured = os.environ.get("DECKY_PLUGIN_SETTINGS_DIR")
    if configured:
        return configured
    raise HelperError("Decky settings directory is unavailable; preferences were not saved.")


def _settings_path() -> str:
    return os.path.join(_settings_dir(), SETTINGS_FILENAME)


def _load_settings() -> Dict[str, Any]:
    """Read preferences; a missing or corrupt file means the safe defaults."""
    try:
        with open(_settings_path(), "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, ValueError, HelperError):
        return {"auto": False, "exceptions": []}
    if not isinstance(raw, dict):
        return {"auto": False, "exceptions": []}
    exceptions: List[str] = []
    stored = raw.get("exceptions")
    if isinstance(stored, list):
        for item in stored:
            if _valid_app_id(item) and item not in exceptions:
                exceptions.append(item)
    return {"auto": raw.get("auto") is True, "exceptions": exceptions}


def _save_settings(settings: Dict[str, Any]) -> None:
    """Atomically persist preferences; failure is reported, never swallowed."""
    payload = {
        "version": SETTINGS_VERSION,
        "auto": settings.get("auto") is True,
        "exceptions": list(settings.get("exceptions") or []),
    }
    path = _settings_path()
    directory = _settings_dir()
    temp = ""
    try:
        os.makedirs(directory, exist_ok=True)
        # Decky's settings directory is host-user owned, so a predictable
        # temporary name could be pre-created as a symlink and followed as root.
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=directory,
            prefix=".game_rules.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp = handle.name
            os.fchmod(handle.fileno(), 0o644)
            json.dump(payload, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    except OSError as exc:
        if temp:
            try:
                os.unlink(temp)
            except OSError:
                pass
        raise HelperError(f"Could not save game rules: {exc.strerror or exc}")


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


async def _run_helper(args: List[str], timeout: float) -> Tuple[int, str, str]:
    """Run one bundled-helper command with fixed argv (never a shell)."""
    helper = _helper_path()
    if not os.path.isfile(helper):
        raise HelperError("Touchscreen helper is missing from the plugin directory.")
    try:
        proc = await asyncio.create_subprocess_exec(
            PYTHON,
            "-I",
            helper,
            *args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
            start_new_session=True,
        )
    except FileNotFoundError:
        raise HelperError("Touchscreen helper interpreter is unavailable.")
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
    returncode, stdout, _stderr = await _run_helper(["status"], STATUS_TIMEOUT)
    payload = _parse_payload(stdout)
    if returncode != 0:
        if payload is not None and isinstance(payload.get("error"), str):
            raise HelperError(payload["error"])
        raise HelperError(f"Touchscreen status check failed (exit {returncode}).")
    if payload is None:
        raise HelperError("Touchscreen helper returned no status.")
    return _validate_devices(payload)


async def _mutate(device_id: str, inhibit: bool) -> None:
    """Inhibit (off) or restore (on) one supported touchscreen via the helper."""
    action = "off" if inhibit else "on"
    returncode, stdout, _stderr = await _run_helper(
        ["set", action, device_id], MUTATE_TIMEOUT
    )
    payload = _parse_payload(stdout)
    if returncode != 0:
        if payload is not None and isinstance(payload.get("error"), str):
            raise HelperError(payload["error"])
        raise HelperError(f"Touchscreen helper command failed (exit {returncode}).")
    if payload is None or payload.get("ok") is not True:
        raise HelperError("Touchscreen helper did not confirm the change.")


class Plugin:
    def __init__(self) -> None:
        self._lock: Optional[asyncio.Lock] = None
        self._session_disabled: Dict[str, Dict[str, str]] = {}
        self._closing = False
        self._settings: Dict[str, Any] = {"auto": False, "exceptions": []}
        self._current_game: Optional[str] = None
        self._lease_until = 0.0
        self._generation = 0
        self._auto_inhibited = False
        self._auto_pending = False
        self._automation_error = ""
        self._watchdog_task: Optional[asyncio.Task] = None

    def _mutation_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def _desired_inhibit(self) -> bool:
        """Automatic mode disables touch only for a running, non-excepted game."""
        if not self._settings["auto"] or time.monotonic() >= self._lease_until:
            return False
        game = self._current_game
        if game is None:
            return False
        return game not in self._settings["exceptions"]

    def _settings_reply(self, **extra: Any) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "ok": True,
            "auto": self._settings["auto"],
            "exceptions": list(self._settings["exceptions"]),
        }
        result.update(extra)
        return result

    async def get_settings(self) -> Dict[str, Any]:
        async with self._mutation_lock():
            self._settings = _load_settings()
            return self._settings_reply()

    async def get_status(self) -> Dict[str, Any]:
        async with self._mutation_lock():
            return await self._read_status()

    async def _read_status(self) -> Dict[str, Any]:
        try:
            result = _summarize(await _fetch_devices())
        except HelperError as exc:
            result = _failure(str(exc))
        result.update(auto=self._settings["auto"], automation_error=self._automation_error)
        return result

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

    async def _apply_desired(self, desired: bool) -> Dict[str, Any]:
        """Drive every supported touchscreen to one verified inhibit state."""
        applied: List[Tuple[Dict[str, Any], bool]] = []
        try:
            devices = await _fetch_devices()
            supported = [d for d in devices if d["supported"]]
            if not supported:
                result = _summarize(devices)
                result.update(ok=False, error=result["message"])
                return result
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

    async def set_enabled(self, enabled: Any) -> Dict[str, Any]:
        if type(enabled) is not bool:
            return _failure("The touchscreen toggle requires a boolean value.")
        async with self._mutation_lock():
            if self._closing:
                return _failure("Touchscreen plugin is unloading; no change was made.")
            if self._settings["auto"]:
                return _failure(
                    "Touchscreen is controlled automatically while Games only is on."
                )
            result = await self._apply_desired(not enabled)
            if result.get("ok"):
                # Explicit verified manual control supersedes automatic recovery.
                self._auto_pending = False
                self._auto_inhibited = False
                self._automation_error = ""
            return result

    async def _apply_auto(self, desired: bool) -> Dict[str, Any]:
        # Retain recovery responsibility even if disable and rollback both fail.
        self._auto_inhibited = self._auto_inhibited or desired
        result = await self._apply_desired(desired)
        self._auto_pending = not bool(result.get("ok"))
        self._automation_error = result.get("error", "") if self._auto_pending else ""
        if result.get("ok"):
            self._auto_inhibited = desired
        result.update(auto=self._settings["auto"], exceptions=list(self._settings["exceptions"]),
                      automation_error=self._automation_error)
        return result

    async def set_auto_enabled(self, auto: Any) -> Dict[str, Any]:
        if type(auto) is not bool:
            return _failure("Games only requires a boolean value.")
        self._generation += 1
        async with self._mutation_lock():
            if self._closing:
                return _failure("Touchscreen plugin is unloading; no change was made.")
            updated = {
                "auto": auto,
                "exceptions": list(self._settings["exceptions"]),
            }
            try:
                _save_settings(updated)
            except HelperError as exc:
                return _failure(str(exc), auto=self._settings["auto"])
            self._settings = updated
            if not auto:
                self._lease_until = 0.0
                self._current_game = None
            return await self._apply_auto(self._desired_inhibit())

    async def set_exception(self, appid: Any, keep: Any) -> Dict[str, Any]:
        if not _valid_app_id(appid):
            return _failure("Game exceptions require a numeric app id string.")
        if type(keep) is not bool:
            return _failure("Game exception state requires a boolean value.")
        self._generation += 1
        async with self._mutation_lock():
            if self._closing:
                return _failure("Touchscreen plugin is unloading; no change was made.")
            exceptions = list(self._settings["exceptions"])
            if keep:
                if appid not in exceptions:
                    exceptions.append(appid)
            else:
                exceptions = [item for item in exceptions if item != appid]
            updated = {"auto": self._settings["auto"], "exceptions": exceptions}
            try:
                _save_settings(updated)
            except HelperError as exc:
                return _failure(
                    str(exc),
                    auto=self._settings["auto"],
                    exceptions=list(self._settings["exceptions"]),
                )
            self._settings = updated
            if not self._settings["auto"] or self._current_game != appid:
                return self._settings_reply(applied=False)
            desired = self._desired_inhibit()
            result = await self._apply_auto(desired)
            result["applied"] = bool(result.get("changed"))
            return result

    async def report_game_state(self, appid: Any) -> Dict[str, Any]:
        """Frontend heartbeat: the running game id, or None when no game runs."""
        if appid is not None and not _valid_app_id(appid):
            return _failure("Game reports require a numeric app id string or null.")
        received = time.monotonic()
        self._generation += 1
        generation = self._generation
        async with self._mutation_lock():
            if self._closing:
                return _failure("Touchscreen plugin is unloading; no change was made.")
            if generation != self._generation:
                # A newer report or settings change superseded this one.
                return self._settings_reply(applied=False, stale=True)
            if not self._settings["auto"]:
                # Read-only heartbeat: reflects watchdog recovery without ever
                # overriding manual control, including while the panel is open.
                result = await self._read_status()
                result.update(applied=False, exceptions=list(self._settings["exceptions"]))
                return result
            # Waiting behind helper IO must not make an old report fresh again.
            self._lease_until = received + LEASE_SECONDS
            self._current_game = appid if time.monotonic() < self._lease_until else None
            desired = self._desired_inhibit()
            result = await self._apply_auto(desired)
            result["applied"] = bool(result.get("changed"))
            return result

    async def release_auto(self) -> Dict[str, Any]:
        """Frontend released automation: restore touch but keep the preference."""
        self._generation += 1
        async with self._mutation_lock():
            if self._closing:
                return _failure("Touchscreen plugin is unloading; no change was made.")
            self._lease_until = 0.0
            self._current_game = None
            if not self._settings["auto"] and not self._auto_pending:
                return self._settings_reply(applied=False)
            return await self._apply_auto(False)

    async def _watchdog_tick(self) -> None:
        async with self._mutation_lock():
            if self._closing:
                return
            expired = time.monotonic() >= self._lease_until
            if not self._auto_pending and not (expired and self._auto_inhibited):
                return
            if expired:
                self._current_game = None
            await self._apply_auto(self._desired_inhibit())

    async def _watchdog(self) -> None:
        while True:
            await asyncio.sleep(WATCHDOG_INTERVAL)
            try:
                await self._watchdog_tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # never let the watcher die silently
                logger = _log()
                if logger:
                    logger.error(f"Touchscreen watchdog tick failed: {exc}")

    async def _main(self) -> None:
        self._settings = _load_settings()
        logger = _log()
        if logger:
            logger.info("Touchscreen toggle loaded; no device state was changed.")
        if self._watchdog_task is None:
            self._watchdog_task = asyncio.create_task(self._watchdog())

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
        task = self._watchdog_task
        self._watchdog_task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
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
