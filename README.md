# signde PPI for Kodi FEL

Classic Player Process Info, bundled with the Fire TV Cube 3 Kodi FEL fork.
Open **Programs → signde PPI (Kodi FEL)** during playback, or bind a remote button to
`RunScript(script.signde.tinyppi)`. Run it again or press Back to close it.
For add-ons with their own playback dialog, such as Plex Uno, also map the button
in the `global` keymap section. For the Fire TV Menu button:

```xml
<keymap>
  <global>
    <keyboard>
      <key id="61656">RunScript(script.signde.tinyppi,context_menu)</key>
    </keyboard>
  </global>
</keymap>
```

This opens PPI during fullscreen video and preserves the normal context menu
outside playback. Keep the regular fullscreen-video binding too.

After first using a new skin, restart Kodi if PPI fonts look incorrect. PPI never
forces a skin reload during playback.

The classic layout and color controls are retained. Modern mode, CoreELEC VS10
controls and speaker-layout graphics are disabled in this branch.

Piers supplies decoder, resolution, frame rate, audio format, passthrough, queue
and bitrate information. Kodi FEL also supplies source HDR/Dolby Vision metadata
and FEL decoder status. “FEL decoder active” describes the player pipeline, not
an independent measurement of the picture. Bit depth is the source base-layer
depth; HDMI format is the Cube's driver report, not a receiver measurement.

Processor shows Kodi's CPU use as a percentage of total CPU capacity, not system-wide
load. Fire OS blocks apps from reading the system CPU counters.

Metadata includes HDR10 mastering/CLL/FALL and Dolby Vision CM version, source PQ,
L1 luminance, L5 crop and L6 values when present. RPU values are sampled at decoder
input, so they are not synchronized to the exact displayed frame.

Unavailable fields show N/A. Object counts, dialnorm and Amlogic presentation/drop
counters are not exposed. Source channel counts are shown without assuming a
speaker arrangement.

Based on jamal2362's TinyPPI and signde's CoreELEC adaptation. MIT licensed.
The source is maintained in the `piers-cube3-fel` branch of `script.tinyppi`.
