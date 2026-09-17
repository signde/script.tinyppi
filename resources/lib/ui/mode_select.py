# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""VS10-mode selection dialog.

Open via ``RunScript(script.tinyppi,dialog)`` or ``open_dialog()``.
"""

import json
import threading
import time

import xbmc
import xbmcaddon
import xbmcgui
from core import display, vs10
from core.utils import PROP_HDR10PLUS_PRESENT, clear_overlay_state

_ADDON      = xbmcaddon.Addon()
_ADDON_PATH = _ADDON.getAddonInfo("path")

# The Dolby Vision driver, as CoreELEC 22 (kernel 5.15, Amlogic-ne) exposes it.
# Every value below is the one CoreELEC's own Kodi writes to these nodes in
# CAMLCodec::OpenDecoder / CloseDecoder, which is what this add-on has to agree
# with: it drives the same driver, on the same box, mid-playback.
_POLICY  = "/sys/module/aml_media/parameters/dolby_vision_policy"
_ENABLE  = "/sys/module/aml_media/parameters/dolby_vision_enable"
_DVMODE  = "/sys/class/amdolby_vision/dv_mode"

# Whether the driver runs Dolby Vision low latency, i.e. Player-LED: 0 is
# DOLBY_VISION_LL_DISABLE (TV-LED), 1 is DOLBY_VISION_LL_YUV422 (Player-LED).
# Kodi only writes it for a stream it turns Dolby Vision on for, so it answers
# for that playback and not for an HDR10 one -- see ``_player_led_mode``.
_LL_POLICY = "/sys/module/aml_media/parameters/dolby_vision_ll_policy"
_DOLBY_VISION_LL_DISABLE = "0"
_DOLBY_VISION_LL_YUV422 = "1"
_DV_STATUS = "/sys/module/aml_media/parameters/dolby_vision_status"

# dolby_vision_policy: AMDV_FOLLOW_SINK, AMDV_FOLLOW_SOURCE and
# AMDV_FORCE_OUTPUT_MODE.  Forcing is what a VS10 mode is; follow-source is what
# Kodi leaves behind when it turns Dolby Vision off, and so what a mode that
# wants no VS10 at all restores.
_POLICY_FOLLOW_SOURCE = "1"
_POLICY_FORCE_OUTPUT  = "2"

# _DVMODE takes the AMDV_OUTPUT_MODE enum shifted by one -- Kodi writes it as
# ``(AMDV_OUTPUT_MODE_x + 1) % 6`` -- so bypass lands on 0 and the modes below
# read one higher than the output mode they select.  Both spellings are live at
# once: _DVMODE is written shifted, vs10.OUTPUT_NODE is read unshifted.
_MODE_BYPASS     = "0"   # AMDV_OUTPUT_MODE_BYPASS, i.e. the source untouched
_MODE_DV_IPT     = "1"   # AMDV_OUTPUT_MODE_IPT, Dolby Vision for Player-LED
_MODE_DV_TUNNEL  = "2"   # AMDV_OUTPUT_MODE_IPT_TUNNEL, DV for TV-LED
_MODE_HDR10      = "3"
_MODE_SDR10      = "4"
_MODE_SDR8       = "5"

# How long the driver gets to pick up a mode change before the switch is taken
# to have failed to reach the requested output format.
_DV_OUTPUT_TIMEOUT_MS = 1000

_BTN_TINYPPI = 1001


def _w(path: str, value: str) -> bool:
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(value)
        xbmc.log(f"TinyPPI: {path} = {value}", xbmc.LOGINFO)
        return True
    except OSError as e:
        xbmc.log(f"TinyPPI: FAILED {path}: {e}", xbmc.LOGERROR)
        return False


def _delay(ms: int) -> None:
    try:
        xbmc.sleep(ms)
    except Exception:
        time.sleep(ms / 1000)


def _read(path: str):
    """Read a sysfs node, returning its stripped contents or None on failure."""
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return None


def _wait_for_output(target: str, timeout_ms: int = _DV_OUTPUT_TIMEOUT_MS,
                     step_ms: int = 50) -> bool:
    """Wait for the requested format, not merely any departure from DV."""
    for waited in range(0, timeout_ms + 1, step_ms):
        if not _is_playing_video():
            return False
        if vs10.output_format() == target:
            return True
        if waited < timeout_ms:
            _delay(step_ms)
    return False


def _wait_for_dv_status_off(timeout_ms: int = 1000, step_ms: int = 50) -> bool:
    """Do not disable a core that is still running or cannot be read."""
    for waited in range(0, timeout_ms + 1, step_ms):
        if _read(_DV_STATUS) == "0":
            return True
        if waited < timeout_ms:
            _delay(step_ms)
    return False


def _is_playing_video() -> bool:
    """True when a video is playing, i.e. when native VS10 actions can apply."""
    try:
        return xbmc.Player().isPlayingVideo()
    except Exception:
        return False


def _reset_display_on_output_change(name: str, before) -> bool:
    """Reapply HDMI colour depth/space after confirmed SDR, HDR or DV changes.

    Both TV-LED and Player-LED require the reset. A non-DV boolean loses the
    SDR/HDR10 distinction, leaving the previous carrier format on HDMI.
    """
    if not _is_playing_video():
        return False
    target = vs10.MODE_FORMATS[name]
    if not _wait_for_output(target):
        xbmc.log(f"TinyPPI: '{name}' did not reach {target} -> no display reset",
                 xbmc.LOGWARNING)
        return False
    if before == target and name != "original_hdr":
        return True
    return display.reset(f"VS10 output switched {before or 'unknown'} -> {target}")


def _write_sequence(
    steps: tuple[tuple[str, str], ...],
    delay_ms: int = 100,
) -> bool:
    """Write a sysfs sequence, waiting between steps when requested."""
    for index, (path, value) in enumerate(steps):
        if index and delay_ms > 0:
            _delay(delay_ms)
        if not _w(path, value):
            return False
    return True


def _set_passthrough_mode(dv_mode: str, delay_ms: int = 100) -> bool:
    """Set policy and LED mode before selecting the output.

    For bypass, wait for the core to stop before disabling it. This preserves
    Portisch's tested SDR/DV sequence without treating a timeout as success.
    """
    if dv_mode == _MODE_BYPASS:
        steps = [(_POLICY, _POLICY_FOLLOW_SOURCE)]
    else:
        steps = [(_ENABLE, "Y"), (_POLICY, _POLICY_FORCE_OUTPUT)]
    if dv_mode == _MODE_DV_TUNNEL:
        steps.append((_LL_POLICY, _DOLBY_VISION_LL_DISABLE))
    elif dv_mode == _MODE_DV_IPT:
        steps.append((_LL_POLICY, _DOLBY_VISION_LL_YUV422))
    steps.append((_DVMODE, dv_mode))
    if not _write_sequence(tuple(steps), delay_ms=delay_ms):
        return False
    if dv_mode == _MODE_BYPASS:
        if not _wait_for_dv_status_off():
            xbmc.log("TinyPPI: DV core did not stop -> leaving it enabled",
                     xbmc.LOGWARNING)
            return False
        return _w(_ENABLE, "N")
    # Preserve the tested passthrough settling interval. A forced output can
    # keep the core on, so this timeout is not an acknowledgement; the caller
    # must still verify the requested output before resetting the display.
    _wait_for_dv_status_off(timeout_ms=500)
    return True


def _set_sdr_conversion_mode(dv_mode: str) -> bool:
    """Select one output. A return to SDR is a separate user operation."""
    return _set_passthrough_mode(dv_mode)


def original_sdr() -> bool:
    return _set_passthrough_mode(_MODE_BYPASS, delay_ms=0)


def hdr10() -> bool:
    return _set_sdr_conversion_mode(_MODE_HDR10)


def dv() -> bool:
    # Which of the two Dolby Vision outputs the box wants: Player-LED takes IPT,
    # TV-LED the tunnelled one, exactly as Kodi picks between them itself.
    if _player_led_mode():
        return _set_passthrough_mode(_MODE_DV_IPT)
    else:
        return _set_passthrough_mode(_MODE_DV_TUNNEL)


def original_hdr() -> bool:
    """Restore the source HDR path, not HDR10 output from an enabled VS10 core.

    On CE22, the HDMI reset selects DV carrier attributes while the DV engine
    is enabled, even for forced SDR output. In TV-LED this leaves 8-bit HDMI,
    where the driver's HDR capability check can reject a forced HDR10 request.
    Follow CE's decoder shutdown order: force bypass, wait for core-off, then
    restore follow-source and disable. The caller resets HDMI afterwards so
    the normal HDR path regains its configured colour depth and colour space.
    """
    if not _write_sequence(((_POLICY, _POLICY_FORCE_OUTPUT),
                            (_DVMODE, _MODE_BYPASS))):
        return False
    if not _wait_for_dv_status_off():
        xbmc.log("TinyPPI: DV core did not stop -> original HDR10 not restored",
                 xbmc.LOGWARNING)
        return False
    return _write_sequence(((_POLICY, _POLICY_FOLLOW_SOURCE), (_ENABLE, "N")),
                           delay_ms=0)


def original_hlg() -> bool:
    # HLG is not a valid VS10 input, so turn VS10 off to let HLG pass through
    # the standard HDR path untouched.  That is also why neither the dialog nor
    # the dashboard offers HLG any modes at all; this one is left reachable
    # through ``run_mode`` for a keymap that wants to clear a VS10 mode an
    # earlier title left behind.  Follow-source with enable=N is the state
    # Kodi itself leaves the driver in when it releases Dolby Vision; policy 0 is
    # follow-sink, a different thing, and not what "off" means here.
    return _write_sequence(
        (
            (_POLICY, _POLICY_FOLLOW_SOURCE),
            (_ENABLE, "N"),
        )
    )


# Alias of dv; kept as its own name so keymaps can use both.
original_dv = dv


def sdr8() -> bool:
    return _set_sdr_conversion_mode(_MODE_SDR8)


def sdr10() -> bool:
    return _set_sdr_conversion_mode(_MODE_SDR10)


_MODES = {
    "original_sdr": original_sdr,
    "hdr10": hdr10,
    "dv": dv,
    "original_hdr": original_hdr,
    "original_hlg": original_hlg,
    "original_dv": original_dv,
    "sdr8": sdr8,
    "sdr10": sdr10,
}

def _probe_dv_Player_LED_setting():
    """Return the configured Dolby Vision LED mode, or None when it cannot be
    read.

    ``coreelec.amlogic.dolbyvisionled`` is CoreELEC's own
    ``AML_DISPLAY_DV_LED``: 0 is TV-LED, 1 Player-LED.  Unlike
    ``vs10.native_actions_available``, which asks whether a setting is there at all, this
    one has to read what it says -- the setting exists on every build that can
    do either end, so its presence alone answers nothing.  Going by presence put
    a TV-LED box on the Player-LED output, where the picture went out SDR
    BT.2020nc.

    None, not False, when the value does not arrive: not knowing is not the same
    as TV-LED, and the caller has somewhere else to ask.
    """
    request = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "Settings.GetSettingValue",
            "params": {"setting": "coreelec.amlogic.dolbyvisionled"},
        }
    )
    try:
        response = json.loads(xbmc.executeJSONRPC(request))
    except Exception as e:
        xbmc.log(f"TinyPPI: probe failed: {e}", xbmc.LOGWARNING)
        return None
    if not isinstance(response, dict) or "result" not in response:
        return None
    value = response["result"].get("value")
    # Read as a number, so a "0" that arrives as text is still TV-LED: taking
    # it as a bare string would repeat the mistake this replaced.
    try:
        return int(value)
    except (TypeError, ValueError):
        return 1 if value else 0


def _player_led_mode() -> bool:
    """Return True if Dolby Vision is being driven Player-LED on this box.

    Kodi's own setting answers first, because it answers for every source.  The
    driver's ``dolby_vision_ll_policy`` describes the same choice -- Kodi writes
    it from that very setting -- but only for a stream it turned Dolby Vision on
    for; an HDR10 one leaves it holding whatever the last title put there, which
    is why it stands in only when the setting cannot be read at all rather than
    being trusted over it.

    TV-LED is the answer when neither can be read: it is CoreELEC's default.
    """
    setting = _probe_dv_Player_LED_setting()
    if setting is not None:
        return setting != 0

    ll_policy = _read(_LL_POLICY)
    if ll_policy is not None:
        xbmc.log(
            "TinyPPI: Dolby Vision LED mode unreadable from Kodi -> taking the "
            f"driver's low-latency policy ({ll_policy})",
            xbmc.LOGINFO,
        )
        return ll_policy not in ("", "0")

    return False


def _hybrid_dv_hdr10plus() -> bool:
    """Return whether the playing stream is a Dolby Vision + HDR10+ hybrid.

    Read off the two properties ``info.properties.publish_hdr_type`` publishes,
    rather than parsed here: the side data is already being read once a poll
    for the overlay and the dialog, and this only needs its answer.
    """
    home = xbmcgui.Window(10000)
    return (
        home.getProperty(PROP_HDR10PLUS_PRESENT) == "1"
        and "dolby" in home.getProperty("TinyPPI.HdrType").lower()
    )


def set_mode(name: str) -> bool:
    """Dispatch native actions, or apply a stock CE transition.

    Stock CE DV/HDR10 swaps require a separate SDR selection and display reset.
    A file lock covers concurrent RunScript interpreters (web, dialog and
    keymap); a threading lock would only protect one interpreter.
    """
    if name not in _MODES:
        xbmc.log(f"TinyPPI: Unknown mode '{name}'", xbmc.LOGERROR)
        return False

    if vs10.native_actions_available():
        if not _is_playing_video():
            return False
        action = vs10.NATIVE_ACTIONS[name]
        xbmc.executebuiltin(f"Action({action})")
        xbmc.log(f"TinyPPI: '{name}' dispatched via Action({action})", xbmc.LOGINFO)
        # Dispatch is not completion: Kodi owns asynchronous resets and may
        # intentionally reject the action. Never override it with sysfs.
        return True

    import fcntl
    import xbmcvfs

    lock_path = xbmcvfs.translatePath("special://temp/tinyppi-vs10.lock")
    with open(lock_path, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            xbmc.log("TinyPPI: VS10 switch already in progress", xbmc.LOGWARNING)
            return False
        try:
            return _set_mode_locked(name)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _set_mode_locked(name: str) -> bool:
    before = vs10.output_format()
    playing = _is_playing_video()
    if playing and not vs10.mode_allowed(name, before):
        xbmc.log(f"TinyPPI: '{name}' blocked from {before}: select SDR first",
                 xbmc.LOGWARNING)
        xbmcgui.Dialog().notification("TinyPPI", _ADDON.getLocalizedString(32555))
        return False
    if _hybrid_dv_hdr10plus():
        xbmc.log(f"TinyPPI: '{name}' requested for a DV/HDR10+ hybrid; "
                 "the driver may not accept it", xbmc.LOGWARNING)
    if not _apply_mode(name):
        return False
    if not playing:
        return True
    return _reset_display_on_output_change(name, before)


def _apply_mode(name: str) -> bool:
    """Apply the stock CE sysfs sequence; native builds never enter here."""
    if not _MODES[name]():
        return False
    xbmc.log(f"TinyPPI: mode '{name}' set via built-in TinyPPI VS10 (sysfs)",
             xbmc.LOGINFO)
    return True


__all__ = list(_MODES.keys()) + ["open_dialog", "set_mode"]


# Dialog button id -> mode name (routed through ``set_mode`` so the dialog also
# prefers the native VS10 Actions when they are available).
_ACTIONS = {
    # SDR
    1002: "original_sdr",
    1003: "hdr10",
    1004: "dv",
    # HDR10
    1005: "original_hdr",
    1006: "sdr8",
    1008: "dv",
    # DV
    1012: "original_dv",
    1013: "sdr8",
}


class SettingsDialog(xbmcgui.WindowXMLDialog):
    """Menu dialog to pick a VS10 output mode or launch the TinyPPI overlay."""

    def onInit(self) -> None:
        # The SDR / HDR10 / DV groups branch on TinyPPI.HdrType, derived from
        # the stream's side data; refresh it so the right group appears as soon
        # as the player publishes it.
        self._running = True
        self._pending_mode = None
        self._monitor = xbmc.Monitor()
        self._refresh_modes()
        threading.Thread(target=self._hdr_type_loop, daemon=True).start()

    def _hdr_type_loop(self) -> None:
        """Republish the HDR type until the dialog closes.

        A failed read only costs this cycle: the dialog would otherwise keep
        showing whichever SDR / HDR10 / DV group was up when the thread died.
        """
        from info.properties import publish_hdr_type

        home = xbmcgui.Window(10000)
        logged = False
        while self._running and not self._monitor.abortRequested():
            try:
                publish_hdr_type(home)
                self._refresh_modes()
            except Exception as e:
                if not logged:
                    logged = True
                    xbmc.log(f"TinyPPI: HDR type refresh failed: {e}",
                             xbmc.LOGWARNING)
            if self._monitor.waitForAbort(0.5):
                break

    def _refresh_modes(self) -> None:
        output = vs10.interlock_output()
        for control_id, mode in _ACTIONS.items():
            self.getControl(control_id).setEnabled(vs10.mode_allowed(mode, output))

    def close(self) -> None:
        self._running = False
        super().close()

    def onClick(self, control_id: int) -> None:
        if control_id == _BTN_TINYPPI:
            self.close()
            clear_overlay_state(xbmcgui.Window(10000))
            from ui.overlay import open_tinyppi
            open_tinyppi()
            return

        mode = _ACTIONS.get(control_id)
        if mode:
            if not vs10.mode_allowed(mode, vs10.interlock_output()):
                return
            # Defer applying: a native VS10 action fired now would be dropped by
            # the window manager while this modal dialog's closing animation is
            # still running ("ignoring action ..., because topmost modal dialog
            # closing animation is running"). open_dialog() applies it once
            # doModal() has returned, i.e. after the dialog is fully gone.
            self._pending_mode = mode
            self.close()

    def onAction(self, action: xbmcgui.Action) -> None:
        if action.getId() in (
            xbmcgui.ACTION_PREVIOUS_MENU,
            xbmcgui.ACTION_NAV_BACK,
            xbmcgui.ACTION_STOP,
        ):
            self.close()


def open_dialog() -> None:
    """Create and display the mode-selection dialog modally."""
    win = SettingsDialog(
        "script-tinyppi-dialog.xml",
        _ADDON_PATH,
        "Default",
        "1080i",
    )
    win.doModal()
    mode = getattr(win, "_pending_mode", None)
    del win
    if mode:
        # The dialog and its closing animation are fully gone now, so a native
        # VS10 action will reach the fullscreen video player instead of being
        # ignored. Let the underlying window settle first, then apply.
        _delay(250)
        set_mode(mode)
