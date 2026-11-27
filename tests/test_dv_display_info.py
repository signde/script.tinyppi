"""Cross-fork process-label handling, without Kodi or a live device."""
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


class DisplayInfoTests(unittest.TestCase):
    def setUp(self):
        self.values = {}
        self.playing = True
        xbmc = types.SimpleNamespace(
            getInfoLabel=lambda label: self.values.get(label, ""),
            getCondVisibility=lambda condition: self.playing,
        )
        addon = types.SimpleNamespace(
            getLocalizedString=lambda number: "N/A" if number == 32033 else "")
        modules = {"xbmc": xbmc, "xbmcgui": types.SimpleNamespace(),
                   "xbmcaddon": types.SimpleNamespace(Addon=lambda: addon)}
        spec = importlib.util.spec_from_file_location(
            "dv_display_info", Path(__file__).parents[1] / "resources/lib/info/dvinfo.py")
        self.info = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, modules):
            spec.loader.exec_module(self.info)

    def put(self, name, value):
        self.values["Player.Process(" + name + ")"] = value

    def test_active_backend_changes_and_missing_support(self):
        for value in ("dovi5", "dovi", ""):
            self.put("amlogic.dv.backend", value)
            self.assertEqual(self.info.get_dv_module(), value or "N/A")
        self.put("amlogic.dv.backend", "Player.Process(amlogic.dv.backend)")
        self.assertEqual(self.info.get_dv_module(), "N/A")

    def test_p3i_numeric_value_and_display_led_empty(self):
        self.put("video.dovi.vsvdb.max.lum", "1000")
        self.assertEqual(self.info.get_dv_target_max_luminance(), "1000 nits")
        self.put("video.dovi.vsvdb.max.lum", "")
        self.assertEqual(self.info.get_dv_target_max_luminance(), "N/A")

    def test_alias_fallback_rejects_unknown_label_echo(self):
        self.put("video.dovi.vsvdb.max.lum", "Player.Process(video.dovi.vsvdb.max.lum)")
        self.put("amlogic.dv.target.max.nits", "800")
        self.assertEqual(self.info.get_dv_target_max_luminance(), "800 nits")
        self.put("amlogic.dv.target.max.nits", "Player.Process(amlogic.dv.target.max.nits)")
        self.assertEqual(self.info.get_dv_target_max_luminance(), "N/A")

    def test_avdvplus_pair_and_preformatted_values_are_preserved(self):
        for raw, expected in [("276/285", "276/285 nits"),
                              ("1000 / 950", "1000 / 950 nits"),
                              ("1000 nits (950 EDID)", "1000 nits (950 EDID)"),
                              ("N/A", "N/A")]:
            self.put("video.dovi.vsvdb.max.lum", raw)
            self.assertEqual(self.info.get_dv_target_max_luminance(), expected)

    def test_stopped_playback_does_not_reuse_old_values(self):
        self.put("amlogic.dv.backend", "dovi5")
        self.put("video.dovi.vsvdb.max.lum", "1000")
        self.playing = False
        self.assertEqual(self.info.get_dv_module(), "")
        self.assertEqual(self.info.get_dv_target_max_luminance(), "")

    def test_p3i_cm_append_without_source_version(self):
        for active, expected in [
                ("VCMv4.0 2-0", "true"),
                ("VCMv4.0 2-0 1-L8", "true"),
                ("CMv2.9 1-L2", "false"),
                ("CMv4.0 2-0 1-L8", "false"),
                ("C29 CMv2.9", "false")]:
            with self.subTest(active=active):
                self.put("video.dovi.meta.version", active)
                self.assertEqual(self.info.get_cm_conversion(), expected)

    def test_avdvplus_cm_conversion_from_source_and_output(self):
        for source, active, expected in [
                ("CMv2.9", "CMv4.0 2-0", "true"),
                ("CMv2.9 1-L2", "CMv4.0 2-0 1-L8", "true"),
                ("CMv2.9", "CMv2.9", "false"),
                ("CMv4.0 2-0", "CMv4.0 2-0", "false")]:
            with self.subTest(source=source, active=active):
                self.put("video.source.dovi.meta.version", source)
                self.put("video.dovi.meta.version", active)
                self.assertEqual(self.info.get_cm_conversion(), expected)

    def test_cm_append_clears_when_skipped_stopped_or_unavailable(self):
        # Smart append can change between scenes; do not latch a prior success.
        for active, expected in [("VCMv4.0 2-0", "true"),
                                 ("CMv2.9 1-L2", "false"),
                                 ("", "false"),
                                 ("Player.Process(video.dovi.meta.version)", "false")]:
            self.put("video.dovi.meta.version", active)
            self.assertEqual(self.info.get_cm_conversion(), expected)
        self.put("video.dovi.meta.version", "VCMv4.0 2-0")
        self.put("video.source.dovi.meta.version",
                 "Player.Process(video.source.dovi.meta.version)")
        self.assertEqual(self.info.get_cm_conversion(), "true")
        self.playing = False
        self.assertEqual(self.info.get_cm_conversion(), "false")

    def test_detector_snapshot_order_zero_and_result_invalidation(self):
        snapshot = {"version": 1, "valid": True,
                    "coordinate_system": "coded-video-pixels",
                    "left": 12, "right": 24, "top": 276, "bottom": 280}
        self.put("video.borders", json.dumps(snapshot))
        self.assertEqual(self.info.get_detected_borders(), "12 L | 24 R | 276 T | 280 B")
        for key in ("left", "right", "top", "bottom"):
            snapshot[key] = 0
        self.put("video.borders", json.dumps(snapshot))
        self.assertEqual(self.info.get_detected_borders(), "0 L | 0 R | 0 T | 0 B")
        snapshot["valid"] = False
        self.put("video.borders", json.dumps(snapshot))
        self.assertEqual(self.info.get_detected_borders(), "N/A")
        self.playing = False
        self.assertEqual(self.info.get_detected_borders(), "")

    def test_unavailable_borders_do_not_borrow_effective_l5(self):
        self.put("video.dovi.l5.top.offset", "276")
        for raw in ("", "Player.Process(video.borders)", "not json", "[]", "null",
                    '{"version":1,"valid":true,"coordinate_system":"coded-video-pixels"}',
                    '{"version":1,"valid":true,"coordinate_system":"coded-video-pixels",'
                    '"left":false,"right":0,"top":0,"bottom":0}'):
            with self.subTest(raw=raw):
                self.put("video.borders", raw)
                self.assertEqual(self.info.get_detected_borders(), "N/A")

    def test_l5_states_including_timeout_and_unknown_builds(self):
        expected = ["Failed", "Skipped (non-16:9)", "Skipped (variable/uncertain)",
                    "Detected", "Skipped", "Disabled / inactive", "Running", "Timed out"]
        for state, text in enumerate(expected):
            self.put("video.dovi.l5.detect.state", str(state))
            self.assertEqual(self.info.get_l5_detection_state(), text)
        for state in ("", "Player.Process(video.dovi.l5.detect.state)", "8", "bad"):
            self.put("video.dovi.l5.detect.state", state)
            self.assertEqual(self.info.get_l5_detection_state(), "N/A")
        self.put("video.dovi.l5.detect.state", "3")
        self.playing = False
        self.assertEqual(self.info.get_l5_detection_state(), "")


if __name__ == "__main__":
    unittest.main()
