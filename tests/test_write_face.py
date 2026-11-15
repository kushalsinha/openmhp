"""Tests for the MCP bridge's two write faces. The default typed face keeps the shipped schema and
passes the model's value through to the device gate untouched; the opt-in wrapped face
(--write-face=wrapped) announces one string form, restores the target's declared descriptor type
before the device gate, and refuses unrestorable values with a correction naming the exact form to
send (weak tool-calling models emit typed JSON reliably only when the schema offers no other form).

    PYTHONPATH=. python tests/test_write_face.py
"""
import os
import sys
import tempfile

sys.path.insert(0, ".")
os.environ["OPENMHP_HOME"] = tempfile.mkdtemp(prefix="openmhp-write-face-tests-")

from openmhp import mcp_bridge as mb
from openmhp.client import RemoteError


class FakeDev:
    """A device that declares three setting types and records what the bridge sent it."""

    SETTINGS = {"ch1_enabled": "boolean", "trigger_coupling": "string", "ch1_probe_atten": "integer"}

    def __init__(self):
        self.written = []

    def call(self, method, payload=None):
        if method == "device/describe":
            names = (payload or {}).get("select", {}).get("settings", [])
            return {"settings": [{"name": n, "type": t} for n, t in self.SETTINGS.items() if n in names]}
        if method == "settings/write":
            self.written.append(payload)
            return {"ok": True}
        raise AssertionError(f"unexpected call {method}")


def refused(bridge, dev, name, value):
    try:
        bridge._write_wrapped(dev, {"device": "d", "name": name, "value": value})
        return None
    except RemoteError as e:
        return e


def test_typed_face_schema_is_unchanged():
    w = [t for t in mb.Bridge().tools() if t["name"] == "mhp_write"][0]
    assert w["inputSchema"]["properties"]["value"] == {}
    assert w["input_examples"][0]["value"] == 95


def test_wrapped_face_schema_is_one_string_form():
    w = [t for t in mb.Bridge(write_face="wrapped").tools() if t["name"] == "mhp_write"][0]
    v = w["inputSchema"]["properties"]["value"]
    assert v["type"] == "string"
    assert w["inputSchema"]["required"] == ["device", "name", "value"]
    assert all(isinstance(ex["value"], str) for ex in w["input_examples"])


def test_restore_matrix():
    b, dev = mb.Bridge(write_face="wrapped"), FakeDev()
    for name, value, expect in [("ch1_enabled", "true", True), ("ch1_probe_atten", "10", 10),
                                ("ch1_probe_atten", "12", 12), ("trigger_coupling", "DC", "DC"),
                                ("trigger_coupling", '"' + "DC" + '"', "DC")]:
        b._write_wrapped(dev, {"device": "d", "name": name, "value": value})
        got = dev.written[-1]["value"]
        assert got == expect and isinstance(got, type(expect)), (name, value, got)


def test_unknown_setting_is_forwarded_with_restored_value():
    b, dev = mb.Bridge(write_face="wrapped"), FakeDev()
    b._write_wrapped(dev, {"device": "d", "name": "not_a_setting", "value": "95"})
    assert dev.written[-1]["value"] == 95          # the device's own unknown-name refusal stays authoritative


def test_refuses_double_wrapped_boolean_with_correction():
    e = refused(mb.Bridge(write_face="wrapped"), FakeDev(), "ch1_enabled", '"' + "true" + '"')
    assert e is not None and e.code == -32602
    assert e.data["category"] == "unrestorable" and e.data["declared_type"] == "boolean"
    assert '{"value": "true"}' in e.message        # the correction shows the exact arguments JSON


def test_refuses_json_number_for_string_target():
    e = refused(mb.Bridge(write_face="wrapped"), FakeDev(), "trigger_coupling", "5")
    assert e is not None and e.data["category"] == "unrestorable"


def test_refuses_non_string_value():
    e = refused(mb.Bridge(write_face="wrapped"), FakeDev(), "ch1_enabled", True)
    assert e is not None and e.data["category"] == "form_mismatch"


def test_rejects_nan_constant():
    e = refused(mb.Bridge(write_face="wrapped"), FakeDev(), "ch1_probe_atten", "NaN")
    assert e is not None and e.data["category"] == "unrestorable"


def test_unknown_face_rejected_at_construction():
    try:
        mb.Bridge(write_face="loose")
        raise AssertionError("construction should refuse an unknown face")
    except ValueError:
        pass


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"{len(fns)} tests passed")
