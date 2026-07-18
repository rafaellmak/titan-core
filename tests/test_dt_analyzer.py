import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from titan.hardware.dt_analyzer import DeviceTreeAnalyzer


def _analyze(content: str):
    with tempfile.TemporaryDirectory() as tmp:
        dts = Path(tmp) / "test.dts"
        dts.write_text(content)
        with patch.object(DeviceTreeAnalyzer, "_has_dtc", return_value=False), \
             patch.object(DeviceTreeAnalyzer, "_has_dt_validate", return_value=False):
            return DeviceTreeAnalyzer().analyze_dts(dts)


def test_static_runs_even_without_dtc():
    findings = _analyze("/dts-v1/;\n/ {\n};\n")
    components = {f["component"] for f in findings}
    assert "dtc missing" in components
    has_static = any(c in components for c in ("Root", "AddressCells", "SizeCells"))
    assert has_static, f"expected static findings, got: {components}"


def test_detects_missing_compatible():
    findings = _analyze("/dts-v1/;\n/ { model = \"x\"; #address-cells=<1>; #size-cells=<1>; };\n")
    has = [f for f in findings if f["component"] == "Root"]
    assert any("compatible" in f["description"] for f in has)


def test_detects_missing_address_cells():
    findings = _analyze("/dts-v1/;\n/ { model=\"x\"; compatible=\"v\"; };\n")
    has = [f for f in findings if f["component"] == "AddressCells"]
    assert has, "should warn about missing #address-cells"


def test_detects_missing_size_cells():
    findings = _analyze("/dts-v1/;\n/ { model=\"x\"; compatible=\"v\"; #address-cells=<1>; };\n")
    has = [f for f in findings if f["component"] == "SizeCells"]
    assert has


def test_detects_invalid_status_value():
    findings = _analyze('/dts-v1/;\n/ { model="x"; compatible="v"; #address-cells=<1>; #size-cells=<1>;\n  node { status = "active"; }; };\n')
    has = [f for f in findings if f["component"] == "Status" and f["severity"] == "Error"]
    assert has


def test_detects_legacy_status_ok():
    findings = _analyze('/dts-v1/;\n/ { model="x"; compatible="v"; #address-cells=<1>; #size-cells=<1>;\n  node { status = "ok"; }; };\n')
    has = [f for f in findings if f["component"] == "Status" and "antiga" in f["description"]]
    assert has


def test_detects_undefined_label_reference():
    dts = """/dts-v1/;
/ {
    soc {
        i2c: i2c@10000 { compatible="v"; reg=<0x10000 0x1000>; };
    };
};

&nonexistent_label {
    status = "okay";
};
"""
    findings = _analyze(dts)
    has = [f for f in findings if f["component"] == "LabelRef"]
    assert has
    assert "nonexistent_label" in has[0]["description"]


def test_does_not_flag_defined_labels():
    dts = """/dts-v1/;
/ {
    soc {
        i2c: i2c@10000 { compatible="v"; reg=<0x10000 0x1000>; };
    };
};

&i2c {
    status = "okay";
};
"""
    findings = _analyze(dts)
    label_findings = [f for f in findings if f["component"] == "LabelRef"]
    assert not label_findings


def test_detects_i2c_without_pinctrl():
    dts = """/dts-v1/;
/ {
    model="b"; compatible="v"; #address-cells=<1>; #size-cells=<1>;
    soc { i2c@10000 { compatible="v"; reg=<0x10000 0x1000>; status="okay"; }; };
};
"""
    findings = _analyze(dts)
    has = [f for f in findings if f["component"] == "Pinctrl"]
    assert has, f"expected pinctrl warning, got: {[f['component'] for f in findings]}"


def test_detects_duplicate_node_names():
    dts = """/dts-v1/;
/ {
    model="b"; compatible="v"; #address-cells=<1>; #size-cells=<1>;
    soc {
        uart@10000 { compatible="v"; reg=<0x10000 0x1000>; status="okay"; };
        uart@20000 { compatible="v"; reg=<0x20000 0x1000>; status="okay"; };
    };
};
"""
    findings = _analyze(dts)
    has = [f for f in findings if f["component"] == "DuplicateNode"]
    assert has


def test_detects_missing_dts_v1_header():
    findings = _analyze('/ { model="b"; compatible="v"; #address-cells=<1>; #size-cells=<1>; };\n')
    has = [f for f in findings if f["component"] == "Header"]
    assert has


def test_clean_dts_produces_minimal_findings():
    findings = _analyze("""/dts-v1/;
/ {
    model="Board v1"; compatible="vendor,board";
    #address-cells=<1>; #size-cells=<1>;
    chosen { };
};
""")
    components = {f["component"] for f in findings}
    assert "Root" not in components
    assert "AddressCells" not in components
    assert "SizeCells" not in components
    assert "Header" not in components


def test_empty_file_reports_error():
    findings = _analyze("")
    has = [f for f in findings if f["component"] == "Static" and f["severity"] == "Error"]
    assert has


if __name__ == "__main__":
    test_static_runs_even_without_dtc()
    test_detects_missing_compatible()
    test_detects_missing_address_cells()
    test_detects_missing_size_cells()
    test_detects_invalid_status_value()
    test_detects_legacy_status_ok()
    test_detects_undefined_label_reference()
    test_does_not_flag_defined_labels()
    test_detects_i2c_without_pinctrl()
    test_detects_duplicate_node_names()
    test_detects_missing_dts_v1_header()
    test_clean_dts_produces_minimal_findings()
    test_empty_file_reports_error()
    print(f"OK: 13 testes do DT analyzer")
