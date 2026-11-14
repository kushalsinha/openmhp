"""The closed-loop demo, end to end, with the scripted agent: a plain-English request, a planner's question,
a charter approved, a GC separation optimised on a simulated chromatograph with the scientist's own optimizer
within the charter's budget, and the results home, verified and acknowledged.

    PYTHONPATH=. python tests/test_gateway_demo.py
"""
import importlib.util
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, ".")


def test_closed_loop_demo():
    if os.name == "nt" or not shutil.which("openssl"):
        print("skip: the demo's gateway needs openssl")
        return
    spec = importlib.util.spec_from_file_location("demo", Path("examples/gateway_closed_loop/demo.py"))
    demo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(demo)
    out = demo.run("scripted", home=Path(tempfile.mkdtemp(prefix="openmhp-demo-test-")), quiet=True)
    assert out["state"] == "finished", out
    assert 1 <= out["injections"] <= 10, out                       # the charter's experiment budget held
    assert out["best"] and out["best"]["resolution_min"] >= 1.5, out
    assert out["verified"] and out["acknowledged"] and out["purged"], out
    assert out["lease_after"] is None, out
    assert "ramp_c_min in each oven_program entry 2 to 40" in out["charter"], out["charter"]   # the nested limit is in it


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok ", name)
