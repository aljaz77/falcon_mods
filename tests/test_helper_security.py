"""The falconbedgrid:// URL can be opened by anything on the PC (including web pages), so the
helper must only accept well-formed, harmless parameters."""
import numpy as np
import pytest

from falcon_bedgrid import __main__ as helper


@pytest.mark.parametrize("url", [
    "falconbedgrid://apply?token=..%2F..%2Fx",
    "falconbedgrid://apply?token=abc/../../x",
    "falconbedgrid://apply?token=abc",            # too short
    "falconbedgrid://apply?token=" + "a" * 41,    # too long
    "falconbedgrid://markers?token=a%00bcdefg",
])
def test_bad_tokens_are_dropped(url):
    assert helper.parse_url(url)["token"] is None


def test_image_and_device_are_constrained():
    a = helper.parse_url("falconbedgrid://calibrate?token=abcdef123&image=..%5C..%5Cevil&device=x%22%3Bdel")
    assert a["image"].endswith("10.jpg")          # falls back to the app's own capture
    assert a["device"] is None
    b = helper.parse_url("falconbedgrid://calibrate?token=abcdef123&image=10&device=0A1B2C3D4E5F")
    assert b["device"] == "0A1B2C3D4E5F" and b["token"] == "abcdef123"


def test_unknown_action_falls_back_to_calibrate_and_wrong_scheme_raises():
    assert helper.parse_url("falconbedgrid://rm-rf?token=abcdef123")["action"] == "calibrate"
    with pytest.raises(ValueError):
        helper.parse_url("http://apply?token=abcdef123")


def good_pending():
    K = [[1000.0, 0, 1296], [0, 1000.0, 972], [0, 0, 1]]
    return {"K": K, "NK": K, "W": np.eye(3).tolist(), "D": [-0.3, 0.1, 0, 0, 0], "device": "0A1B2C3D4E5F",
            "config_path": "C:/Windows/System32/evil.txt"}


def test_valid_pending_accepts_sane_matrices():
    assert helper._valid_pending(good_pending()) is not None


@pytest.mark.parametrize("bad", [
    {"K": [[1, 2], [3, 4]]},
    {"D": [0.1, 0.2]},
    {"W": [[float("nan")] * 3] * 3},
    {"K": [[-5.0, 0, 0], [0, 1, 0], [0, 0, 1]]},
    {"device": "../../etc"},
])
def test_valid_pending_rejects_garbage(bad):
    p = good_pending()
    p.update(bad)
    assert helper._valid_pending(p) is None


def test_apply_never_uses_path_from_job(monkeypatch, tmp_path):
    """headless_apply must write the app's own config, never the path stored in pending.json."""
    seen = {}
    monkeypatch.setattr(helper.jobs, "load_pending", lambda token: good_pending())
    monkeypatch.setattr(helper, "apply_report", lambda rep, device, log: seen.update(rep=rep))
    helper.headless_apply("abcdef123", lambda m: None)
    assert seen["rep"]["config_path"] == helper.config_io.default_config_path()
