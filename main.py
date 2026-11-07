"""Addon entry point: bootstrap the lib path and dispatch the command."""

import os
import sys

import xbmc
import xbmcaddon


def _bootstrap_lib_path(addon: xbmcaddon.Addon) -> None:
    """Add resources/lib to the import path once."""
    lib_path = os.path.join(addon.getAddonInfo("path"), "resources", "lib")
    if lib_path not in sys.path:
        sys.path.insert(0, lib_path)


def _split_args(raw_args: list[str]) -> list[str]:
    """Flatten Kodi's comma-separated script arguments."""
    args: list[str] = []
    for raw in raw_args:
        args.extend(raw.split(","))
    return args


def main() -> None:
    """Dispatch TinyPPI's script entry point."""
    args = _split_args(sys.argv[1:])
    command = args[0] if args else ""

    # Add-on playback dialogs (for example Uno) have their own keymap context.
    # Preserve the Menu button elsewhere instead of taking over library menus.
    if command == "context_menu":
        if not (xbmc.Player().isPlayingVideo() and
                xbmc.getCondVisibility("Window.IsActive(fullscreenvideo)")):
            xbmc.executebuiltin("Action(ContextMenu)")
            return

    addon = xbmcaddon.Addon()
    if addon.getSettingInt("ppi_mode") != 0:
        addon.setSettingInt("ppi_mode", 0)
    _bootstrap_lib_path(addon)

    from ui.overlay import open_tinyppi

    if command == "splash":
        from ui.splash import open_splash
        open_splash()
    elif command in ("dialog", "run_mode", "context_menu"):
        # CoreELEC VS10 controls must never change Fire OS display state.
        open_tinyppi()
    elif command == "custom_color" and len(args) > 1:
        from ui.theme import custom_color
        custom_color(args[1])
    else:
        if xbmc.Player().isPlayingVideo():
            xbmc.executebuiltin("ActivateWindow(fullscreenvideo)")
            for _ in range(30):
                if xbmc.getCondVisibility("Window.IsActive(fullscreenvideo)"):
                    break
                xbmc.sleep(100)
        open_tinyppi()


if __name__ == "__main__":
    main()
