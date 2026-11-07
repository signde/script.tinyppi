"""Read-only Piers and Fire TV telemetry. Never opens /dev/dvfel or changes modes."""
import os
import json
import re
import time
import xbmc
import xbmcgui

ALIASES = {
    "audio.live.kibit.rate": "audiolivebitrate",
    "video.live.mibit.rate": "videolivebitrate",
    "video.queue.level": "videoqueuelevel",
    "video.queue.data.level": "videoqueuedatalevel",
    "audio.queue.level": "audioqueuelevel",
    "audio.queue.data.level": "audioqueuedatalevel",
    "video.height.raw": "videoheight",
}
_values = {}
_deadline = 0.0
_last_source = ""
_cpu_sample = None
_cpu_text = "Measuring…"


def raw(label):
    value = xbmc.getInfoLabel(label) or ""
    return "" if value.lower() == label.lower() else value


def read(path):
    try:
        with open(path, encoding="utf-8") as source:
            return source.read(8192).strip()
    except OSError:
        return ""


def refresh():
    global _values, _deadline, _last_source
    source = raw("Player.Process(firetvsource)")
    if time.monotonic() < _deadline and source == _last_source:
        return
    _deadline = time.monotonic() + 1.0
    _last_source = source
    previous = _values
    try:
        data = json.loads(source)
        _values = {k: str(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except (ValueError, TypeError):
        _values = {}
    if xbmc.getCondVisibility("Player.HasVideo"):
        hdr = raw("VideoPlayer.HDRType").lower()
        _values["video.source.hdr.type"] = {
            "dolbyvision": "Dolby Vision", "hdr10": "HDR10", "hdr10+": "HDR10+",
            "hlg": "HLG", "": "SDR",
        }.get(hdr, hdr.upper())
        status = raw("Player.Process(firetvfelstatus)")
        _values["firetv.fel.status"] = status or "Not active"
        if status.startswith("FEL"):
            _values["video.dovi.el.type"] = "full"
        elif status.startswith("MEL"):
            _values["video.dovi.el.type"] = "minimum"
        _values["firetv.source.detail"] = raw("VideoPlayer.HDRDetail") or _values["video.source.hdr.type"]
    for old, new in ALIASES.items():
        _values[old] = raw("Player.Process(" + new + ")")
    config = read("/sys/class/amhdmitx/amhdmitx0/config")
    fields = dict(re.findall(r"^([a-z_]+):\s*(.*)$", config, re.M))
    depth = fields.get("colordepth", "").replace("bit", "-bit")
    chroma = fields.get("colorspace", "").lower()
    chroma = {"444": "YUV444", "422": "YUV422", "420": "YUV420", "rgb": "RGB"}.get(chroma, "")
    _values["amlogic.pixformat"] = f"{depth}, {chroma}" if depth and chroma else ""
    _values["amlogic.displaymode"] = read("/sys/class/display/mode")
    _values["amlogic.eoft_gamut"] = _values.get("video.hdr.colour.primaries", "")
    home = xbmcgui.Window(10000)
    for key in previous.keys() | _values.keys():
        home.setProperty("SigndeTinyPPI.Process." + key, _values.get(key, ""))


def process(name):
    refresh()
    return _values.get(name.lower(), "")


def label(expression):
    match = re.fullmatch(r"Player\.Process\(([^)]+)\)", expression, re.I)
    if match:
        name = match.group(1).lower()
        if "." in name or name in ALIASES:
            return process(name)
    return raw(expression)


def cpu_usage():
    """Kodi's process CPU, normalized to total logical CPU capacity (0–100%)."""
    global _cpu_sample, _cpu_text
    now, used = time.monotonic(), time.process_time()
    if _cpu_sample is None:
        _cpu_sample = (now, used)
    elif now - _cpu_sample[0] >= 1.0:
        elapsed = now - _cpu_sample[0]
        fraction = (used - _cpu_sample[1]) / elapsed / max(1, os.cpu_count() or 1)
        _cpu_text = f"Kodi {max(0.0, min(100.0, 100.0 * fraction)):.1f}%"
        _cpu_sample = (now, used)
    return _cpu_text
