"""Cross-fork process-label handling, without Kodi or a live device."""
import importlib.util
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
        addon = types.SimpleNamespace(getLocalizedString=lambda number: "N/A")
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


if __name__ == "__main__":
    unittest.main()
