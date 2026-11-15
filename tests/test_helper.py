#!/usr/bin/env python3
"""Tests for the unprivileged helper library and CLI argument handling.

Fake sysfs trees mirror real /sys topology: /sys/class/input/inputN is a
symlink into a physical directory under /sys/devices/....  Fake udev data and
the fake root are injected only through the library API.  The privileged CLI
never gains a way to choose a sysfs root or path.
"""

import importlib.util
import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from importlib.machinery import SourceFileLoader
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
HELPER_PATH = os.path.join(
    HERE, "..", "root", "usr", "local", "libexec", "ogui-touchscreen-control"
)

spec = importlib.util.spec_from_loader(
    "touchctl", SourceFileLoader("touchctl", HELPER_PATH)
)
assert spec is not None and spec.loader is not None
touchctl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(touchctl)


class FakeSysfs:
    """Builds a throwaway sysfs tree shaped like the real kernel tree."""

    def __init__(self):
        self.root = tempfile.mkdtemp(prefix="touchctl-sysfs-")
        os.makedirs(os.path.join(self.root, "class", "input"))
        os.makedirs(os.path.join(self.root, "devices", "platform"))
        os.makedirs(os.path.join(self.root, "devices", "virtual", "input"))
        self.props = {}

    def cleanup(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def physical_path(self, index, under_virtual=False):
        sysname = "input%d" % index
        if under_virtual:
            return os.path.join(self.root, "devices", "virtual", "input", sysname)
        return os.path.join(
            self.root, "devices", "platform", "fake-%d" % index, "input", sysname
        )

    def add(
        self,
        index,
        name="Touchscreen",
        inhibited=0,
        props=None,
        under_virtual=False,
        with_inhibited=True,
        inhibited_is_symlink=False,
        outside_devices=False,
    ):
        sysname = "input%d" % index
        link = os.path.join(self.root, "class", "input", sysname)
        if outside_devices:
            # A class entry that resolves outside <root>/devices must be ignored.
            base = tempfile.mkdtemp(prefix="touchctl-outside-")
            os.symlink(base, link)
        else:
            base = self.physical_path(index, under_virtual)
            os.makedirs(base, exist_ok=True)
            os.symlink(base, link)
        with open(os.path.join(base, "name"), "w", encoding="utf-8") as fh:
            fh.write(name + "\n")
        if with_inhibited:
            target = os.path.join(base, "inhibited")
            if inhibited_is_symlink:
                real = os.path.join(base, "real-inhibited")
                with open(real, "w", encoding="utf-8") as fh:
                    fh.write(str(inhibited))
                os.symlink(real, target)
            else:
                with open(target, "w", encoding="utf-8") as fh:
                    fh.write(str(inhibited))
        default_props = {
            "ID_INPUT": "1",
            "ID_INPUT_TOUCHSCREEN": "1",
        }
        self.props[link] = dict(props or default_props)
        return base

    def probe(self, path):
        return self.props.get(path, {})

    def class_node(self, index):
        return os.path.join(self.root, "class", "input", "input%d" % index)

    def read_inhibited(self, index):
        with open(os.path.join(self.class_node(index), "inhibited")) as fh:
            return fh.read().strip()


class HelperTests(unittest.TestCase):
    def setUp(self):
        self.fs = FakeSysfs()

    def tearDown(self):
        self.fs.cleanup()

    def discover(self):
        return touchctl.discover(self.fs.root, self.fs.probe)

    # --- discovery -----------------------------------------------------

    def test_discovers_single_physical_touchscreen(self):
        self.fs.add(8, name="Example Physical Touchscreen", inhibited=0)
        devices = self.discover()
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0]["id"], "input8")
        self.assertEqual(devices[0]["name"], "Example Physical Touchscreen")
        self.assertFalse(devices[0]["inhibited"])
        self.assertTrue(devices[0]["supported"])

    def test_class_entry_is_a_symlink_into_devices(self):
        self.fs.add(8)
        self.assertTrue(os.path.islink(self.fs.class_node(8)))
        physical = self.fs.physical_path(8)
        self.assertTrue(
            physical.startswith(os.path.join(self.fs.root, "devices") + os.sep)
        )
        self.assertEqual(os.path.realpath(self.fs.class_node(8)), physical)

    def test_ignores_touchpad_gamepad_and_mouse(self):
        self.fs.add(
            4,
            name="Touchpad",
            props={"ID_INPUT_TOUCHPAD": "1", "ID_INPUT_TOUCHSCREEN": "1"},
        )
        self.fs.add(
            5,
            name="Gamepad",
            props={"ID_INPUT_JOYSTICK": "1", "ID_INPUT_TOUCHSCREEN": "1"},
        )
        self.fs.add(6, name="Mouse", props={"ID_INPUT_MOUSE": "1"})
        self.assertEqual(self.discover(), [])

    def test_ignores_virtual_devices(self):
        self.fs.add(9, name="Virtual Touchscreen", under_virtual=True)
        self.fs.add(10, name="uinput touch", props={"ID_INPUT_TOUCHSCREEN": "1"})
        self.assertEqual(self.discover(), [])

    def test_ignores_class_entries_outside_devices_tree(self):
        self.fs.add(8, outside_devices=True)
        self.assertEqual(self.discover(), [])

    def test_missing_inhibit_attribute_is_reported_unsupported(self):
        self.fs.add(7, name="Old touchscreen", with_inhibited=False)
        devices = self.discover()
        self.assertEqual(len(devices), 1)
        self.assertFalse(devices[0]["supported"])
        self.assertIn("missing", devices[0]["reason"])
        self.assertIsNone(devices[0]["inhibited"])

    def test_symlinked_inhibit_attribute_is_unsupported(self):
        self.fs.add(7, inhibited_is_symlink=True)
        devices = self.discover()
        self.assertFalse(devices[0]["supported"])

    def test_missing_udevadm_yields_no_devices(self):
        self.fs.add(8)
        self.assertEqual(touchctl.discover(self.fs.root, lambda _p: {}), [])

    def test_multiple_devices_sorted_and_hotplug(self):
        self.fs.add(12, name="Second")
        self.fs.add(8, name="First")
        ids = [d["id"] for d in self.discover()]
        self.assertEqual(ids, ["input8", "input12"])
        # Hotplug removal drops both the class link and the physical node, as
        # the kernel does.
        os.unlink(self.fs.class_node(8))
        shutil.rmtree(os.path.join(self.fs.root, "devices", "platform", "fake-8"))
        ids = [d["id"] for d in self.discover()]
        self.assertEqual(ids, ["input12"])

    # --- canonical write target ---------------------------------------

    def test_discovery_carries_canonical_physical_path(self):
        self.fs.add(8)
        device = self.discover()[0]
        self.assertEqual(device["_physical_path"], self.fs.physical_path(8))
        self.assertEqual(
            os.path.realpath(device["_physical_path"]), device["_physical_path"]
        )

    def test_public_status_does_not_expose_physical_path(self):
        self.fs.add(8)
        status = touchctl.read_status(self.fs.root, self.fs.probe)
        self.assertTrue(status["ok"])
        self.assertEqual(len(status["devices"]), 1)
        self.assertNotIn("_physical_path", status["devices"][0])
        self.assertNotIn(self.fs.root, json.dumps(status))

    def test_mutation_writes_physical_inhibited_not_class_path(self):
        self.fs.add(8, inhibited=0)
        result = touchctl.set_inhibited("input8", True, self.fs.root, self.fs.probe)
        self.assertTrue(result["ok"])
        physical = os.path.join(self.fs.physical_path(8), "inhibited")
        with open(physical, encoding="utf-8") as fh:
            self.assertEqual(fh.read().strip(), "1")
        self.assertEqual(self.fs.read_inhibited(8), "1")
        self.assertTrue(self.discover()[0]["inhibited"])

    def test_verified_path_rejects_symlinked_inhibit_target(self):
        self.fs.add(8)
        device = self.discover()[0]
        real = os.path.join(device["_physical_path"], "real-inhibited")
        os.unlink(os.path.join(device["_physical_path"], "inhibited"))
        with open(real, "w", encoding="utf-8") as fh:
            fh.write("0")
        os.symlink(real, os.path.join(device["_physical_path"], "inhibited"))
        with self.assertRaises(touchctl.ControlError):
            touchctl._verified_inhibit_path(self.fs.root, device)

    def test_verified_path_rejects_escape_from_devices_tree(self):
        self.fs.add(8)
        self.assertTrue(self.discover())
        with self.assertRaises(touchctl.ControlError):
            touchctl._verified_inhibit_path(
                self.fs.root, {"id": "input8", "_physical_path": "/tmp"}
            )

    # --- mutations -----------------------------------------------------

    def test_set_off_writes_one_and_reads_back(self):
        self.fs.add(8, inhibited=0)
        result = touchctl.set_inhibited("input8", True, self.fs.root, self.fs.probe)
        self.assertTrue(result["ok"])
        self.assertEqual(self.fs.read_inhibited(8), "1")
        self.assertTrue(self.discover()[0]["inhibited"])

    def test_set_on_restores_zero(self):
        self.fs.add(8, inhibited=1)
        touchctl.set_inhibited("input8", False, self.fs.root, self.fs.probe)
        self.assertEqual(self.fs.read_inhibited(8), "0")

    def test_set_then_restore_round_trip(self):
        self.fs.add(8, inhibited=0)
        touchctl.set_inhibited("input8", True, self.fs.root, self.fs.probe)
        self.assertEqual(self.fs.read_inhibited(8), "1")
        touchctl.set_inhibited("input8", False, self.fs.root, self.fs.probe)
        self.assertEqual(self.fs.read_inhibited(8), "0")

    def test_set_on_non_touchscreen_is_refused_without_write(self):
        self.fs.add(4, name="Touchpad", inhibited=0, props={"ID_INPUT_TOUCHPAD": "1"})
        with self.assertRaises(touchctl.ControlError):
            touchctl.set_inhibited("input4", True, self.fs.root, self.fs.probe)
        self.assertEqual(self.fs.read_inhibited(4), "0")

    def test_unknown_device_is_refused(self):
        self.fs.add(8)
        with self.assertRaises(touchctl.ControlError):
            touchctl.set_inhibited("input99", True, self.fs.root, self.fs.probe)

    def test_malformed_and_traversal_ids_rejected(self):
        self.fs.add(8)
        for bad in [
            "input8/../../etc/passwd",
            "../input8",
            "input",
            "input-1",
            "input8\n",
            "input999999999",
            "",
            "input8 ",
            "/sys/class/input/input8",
            "input٠",
        ]:
            with self.subTest(bad=bad):
                with self.assertRaises(touchctl.ControlError):
                    touchctl.set_inhibited(bad, True, self.fs.root, self.fs.probe)
        self.assertEqual(self.fs.read_inhibited(8), "0")

    def test_readback_mismatch_rolls_back(self):
        self.fs.add(8, inhibited=0)
        calls = []
        real_write = touchctl._write_inhibited

        def fake_write(path, inhibit):
            calls.append(inhibit)
            if len(calls) == 1:
                return  # simulate kernel ignoring the write
            real_write(path, inhibit)

        with mock.patch.object(touchctl, "_write_inhibited", fake_write):
            with self.assertRaises(touchctl.ControlError):
                touchctl.set_inhibited("input8", True, self.fs.root, self.fs.probe)
        self.assertEqual(
            calls, [True, False], "must attempt rollback to previous value"
        )

    def test_permission_denied_reports_control_error(self):
        path = self.fs.add(8, inhibited=0)
        os.chmod(os.path.join(path, "inhibited"), 0o444)
        with self.assertRaises(touchctl.ControlError) as ctx:
            touchctl.set_inhibited("input8", True, self.fs.root, self.fs.probe)
        self.assertEqual(ctx.exception.code, touchctl.EXIT_PERMISSION)

    def test_restore_all_only_touches_supported_touchscreens(self):
        self.fs.add(8, inhibited=1)
        self.fs.add(12, inhibited=1)
        self.fs.add(4, name="Touchpad", inhibited=1, props={"ID_INPUT_TOUCHPAD": "1"})
        result = touchctl.restore_all(self.fs.root, self.fs.probe)
        self.assertTrue(result["ok"])
        self.assertEqual(result["restored"], ["input8", "input12"])
        self.assertEqual(
            self.fs.read_inhibited(4), "1", "touchpad must remain untouched"
        )
        self.assertNotIn("_physical_path", result["devices"][0])

    def test_restore_all_partial_failure_is_reported(self):
        self.fs.add(8, inhibited=1)
        self.fs.add(12, inhibited=1)
        os.chmod(
            os.path.join(
                self.fs.root,
                "devices",
                "platform",
                "fake-12",
                "input",
                "input12",
                "inhibited",
            ),
            0o444,
        )
        result = touchctl.restore_all(self.fs.root, self.fs.probe)
        self.assertFalse(result["ok"])
        self.assertEqual(result["restored"], ["input8"])
        self.assertEqual(result["errors"][0]["id"], "input12")

    # --- CLI surface ---------------------------------------------------

    def run_main(self, argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = touchctl.main(argv)
        return code, buf.getvalue()

    def test_cli_has_no_sys_root_option(self):
        code, out = self.run_main(["--sys-root", "/tmp", "status"])
        payload = json.loads(out)
        self.assertEqual(code, touchctl.EXIT_USAGE)
        self.assertFalse(payload["ok"])

    def test_cli_rejects_traversal_before_privilege_check(self):
        for argv in (
            ["set", "off", "../../etc/passwd"],
            ["set", "off", "input8/../input9"],
            ["set", "maybe", "input8"],
            ["restore-all", "input8"],
        ):
            with self.subTest(argv=argv):
                code, out = self.run_main(argv)
                self.assertEqual(code, touchctl.EXIT_USAGE)
                self.assertFalse(json.loads(out)["ok"])

    def test_cli_status_is_unprivileged_and_well_formed(self):
        code, out = self.run_main(["status"])
        payload = json.loads(out)
        self.assertEqual(code, touchctl.EXIT_OK)
        self.assertTrue(payload["ok"])
        self.assertIsInstance(payload["devices"], list)

    def test_cli_mutations_require_root(self):
        if os.geteuid() == 0:
            self.skipTest("running as root")
        for argv in (
            ["restore-all"],
            ["set", "off", "input8"],
            ["set", "on", "input8"],
        ):
            with self.subTest(argv=argv):
                code, out = self.run_main(argv)
                self.assertEqual(code, touchctl.EXIT_NOT_ROOT)
                self.assertFalse(json.loads(out)["ok"])

    def test_cli_does_not_accept_paths(self):
        self.fs.add(8)
        for argv in (
            ["set", "off", self.fs.class_node(8)],
            ["set", "off", os.path.join(self.fs.physical_path(8))],
            ["status", self.fs.root],
        ):
            with self.subTest(argv=argv):
                code, out = self.run_main(argv)
                self.assertEqual(code, touchctl.EXIT_USAGE)
                self.assertFalse(json.loads(out)["ok"])

    def test_sysfs_root_is_a_fixed_constant(self):
        self.assertEqual(touchctl.SYS_ROOT, "/sys")


if __name__ == "__main__":
    unittest.main(verbosity=2)
