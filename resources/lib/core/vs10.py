# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Output formats and the SDR-first interlock shared by all VS10 controls."""

import json

import xbmc

OUTPUT_NODE = "/sys/module/aml_media/parameters/dolby_vision_mode"
OUTPUT_FORMATS = {"0": "dv", "1": "dv", "2": "hdr10", "3": "sdr", "4": "sdr"}
MODE_FORMATS = {
    "original_sdr": "sdr",
    "sdr8": "sdr",
    "sdr10": "sdr",
    "hdr10": "hdr10",
    "original_hdr": "hdr10",
    "dv": "dv",
    "original_dv": "dv",
    "original_hlg": "hlg",
}


# SamuriHL exposes one SDR action (SDR10). Both TinyPPI SDR names use it;
# the stock backend alone distinguishes SDR8 from SDR10.
NATIVE_ACTIONS = {
    "original_sdr": "vs10.original",
    "original_hdr": "vs10.original",
    "original_hlg": "vs10.original",
    "original_dv": "vs10.original",
    "dv": "vs10.dv",
    "hdr10": "vs10.hdr10",
    "sdr8": "vs10.sdr",
    "sdr10": "vs10.sdr",
}
_NATIVE_SETTING = "coreelec.amlogic.dolbyvision.vs10.dv"
_native_actions = None


def native_actions_available() -> bool:
    """Detect the setting introduced with SamuriHL's native VS10 actions."""
    global _native_actions
    if _native_actions is None:
        request = {"jsonrpc": "2.0", "id": 1, "method": "Settings.GetSettingValue",
                   "params": {"setting": _NATIVE_SETTING}}
        try:
            response = json.loads(xbmc.executeJSONRPC(json.dumps(request)))
        except Exception as e:
            xbmc.log(f"TinyPPI: VS10 actions probe failed: {e}", xbmc.LOGWARNING)
            response = None
        _native_actions = isinstance(response, dict) and "result" in response
    return _native_actions


def interlock_output():
    """Only the stock backend needs the SDR-first driver interlock."""
    return None if native_actions_available() else output_format()


def output_format():
    """Read the driver's output; bypass retains the source's HDR format.

    Bypass is not necessarily SDR: an untouched HDR10 title still requires
    an SDR step before switching to Dolby Vision. Unreadable state is unknown.
    """
    try:
        with open(OUTPUT_NODE, encoding="utf-8") as node:
            mode = node.read().strip()
    except OSError:
        return None
    if mode != "5":
        return OUTPUT_FORMATS.get(mode)
    source = xbmc.getInfoLabel("VideoPlayer.HdrType").strip().lower()
    if "dolby" in source or "dovi" in source:
        return "dv"
    if "hdr10" in source:
        return "hdr10"
    if "hlg" in source:
        return "hlg"
    return "sdr" if source in ("", "sdr") else None


def mode_allowed(name: str, output) -> bool:
    """On stock CE, HDR10 and DV must be entered from SDR or their own format.

    Keep SDR available as the recovery route even if the driver cannot be
    read. Callers recheck this against live state immediately before writing.
    """
    target = MODE_FORMATS.get(name)
    if target is None:
        return False
    if native_actions_available():
        return True
    if target in ("dv", "hdr10"):
        return output in ("sdr", target)
    return target is not None
