Source: https://github.com/Kenzie-1377/dqxi-3ds-english-patch
Commit: 3c5024b603a4b637af29600cfa2956381a99f772
License: MIT (LICENSE alongside this file).

Copied upstream files: BuildSupport.cs, Codecs.cs, RomBuilder.cs, CodecTests.cs.
The v17 comparison also uses the upstream delta codec (delta.py) under the
same MIT license.
RomBuilder modifications: allow generated additions in the private ROMFS copy;
factor verified NCCH reconstruction into a shared routine; expose the NCCH
validation/rebuild path for CIA sources; retain cartridge verification.

CiaSupport.cs is original DQXI Mod Werkstatt code (MIT), kept alongside the
upstream helpers for their common runtime compilation. It validates/extracts
user CIA sources, validates the PC file inventory, and packages/verifies CIA
contents including safe plaintext auxiliary flag normalization.
No game data, headers or encryption key databases accompany these sources.

The v17 source-guarded location-title assets and delta codec were compared
against release 0.7.0 at commit ea515509d0ab082320bedfbb27602ae2b655c956.
Only 28 location artwork deltas whose original-file hashes match this build's
ROMFS are bundled. The installer skips those assets when a user's source file
does not match. 58 line-wrap-only dialogue edits are stored in the mod's
verified dialogue recipe; no upstream control-marker changes are included.

The compact-storage revision adds opt-in native overloads used by the GUI's
default build path. They release owned reconstruction intermediates between
stages and retain a complete path/SHA-256 snapshot instead of the staged ROMFS
tree during readback. The legacy overloads keep their previous storage
behavior. CiaSupport can reuse the first export after matching its raw TMD
against the selected CIA and validating its game/code/region data. Tool
arguments, tool versions, code patching, full filesystem readback checks and
CIA content verification remain unchanged. Synthetic storage tests are in
tests/native/StorageTests.cs.

The v18 installer restores the native helper path from the v17 build. CIA
content extraction uses CTRTool without the later-added `-p` flag on the
initial `--contents` command. 3dstool extracts the ROMFS directory, logs its
file count and total byte size, and the container rebuild verifies the full
tree against a fresh extraction from the embedded ROMFS region. Codec test
harnesses are kept under `tests/native/`, outside the installer's runtime
folder.
