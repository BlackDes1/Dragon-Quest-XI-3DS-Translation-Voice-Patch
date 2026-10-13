---
layout: default
title: DQXI Mod Workshop v18
description: An unofficial English patch builder for DRAGON QUEST XI S on Nintendo 3DS.
---

**An unofficial English patch builder for DRAGON QUEST XI S on Nintendo 3DS.**

The Windows installer builds a mod from an original Japanese 3DS CIA and a compatible PC game installation supplied by the user. It can create a LayeredFS output for Azahar/Luma workflows or rebuild a CIA. It does not provide a playable game or game files.

> **Copyright status:** this archive is not copyright-free. It does not include a complete retail CIA or PC installation, but it does include game-derived patch material: roughly 90 MB of binary replacement members before compression, dialogue/UI datasets, an IPS code patch, and location-title artwork deltas. Read [COPYRIGHT.md]({{ site.github.repository_url }}/blob/main/COPYRIGHT.md) before redistribution.

## What the patch does

Version 18 builds English-language resources for the Japanese DQXI S 3DS release. It uses selected text, voice, scene, and movie source files from the user's compatible Windows PC installation.

| Area | v18 coverage |
| --- | ---: |
| Dialogue targets | 5,551 |
| Dialogue line-wrap corrections retained from v17 | 58 |
| Voice links | 5,095 |
| Additional voice cases | 50 |
| PC voice clips converted during a build | 5,048 |
| UI text edits | 2,920 |
| Reviewed menu fixes | 85 |
| Movie slots built as MOFLEX files | 10 |
| Location-title artwork deltas | Up to 28, only on exact source-hash matches |

The included `code.ips` is carried forward unchanged from v17. Artwork deltas are applied only when the source file matches its expected SHA-256; unmatched files are reported and skipped.

## What you need

### Computer

- 64-bit Windows with Windows PowerShell 5.1 and Windows Forms.
- Windows Script Host enabled to run the double-click `.vbs` launcher.
- Internet access on first run. The installer downloads pinned tools from their upstream releases and checks the downloaded hashes.
- Several tens of GB of free working space. CIA extraction, PC asset extraction, voice conversion, and movie conversion all create temporary or output files.

### Game files

- An unmodified Japanese DQXI S 3DS CIA. Encrypted or decrypted CIA input is accepted. The installer checks title ID `0004000000199200` and the CIA structure. The CIA is not included.
- A complete compatible Windows DRAGON QUEST XI S PC installation. The required files and folders are listed in `src/pc_installation_manifest.json`. The installer reads the needed English USM movies from `Game/Content/Movies` and selected PC voice data from the PAK files. The PC game is not included.
- The current `code.ips` included in the v18 package.
- A new output folder outside the original CIA, the PC game folder, and the installer folder.

The separate seven-part mod archive is **not required**. The installer creates all ten movie slots from PC USM movies and PC voice/event data. By default, the PC game folder is `C:\Program Files (x86)\Steam\steamapps\common\DRAGON QUEST XI S`; select another folder in the installer if needed.

Do not download or share a game image through this project. Use files from your own lawful copies and follow the laws and platform terms that apply to you.

## Build the mod

1. Download and extract the v18 release ZIP.
2. Double-click `DQXI-Mod-Installer.vbs` in the extracted folder. Keep the complete folder intact so the launcher can find `src/Launch-Installer.ps1` and `src/Installer.ps1`.
3. Select your original Japanese CIA, the included `code.ips`, the PC installation folder containing `Engine` and `Game`, and a new output folder.
4. Choose an output type and select **Build mod**.
5. After success, select **Open finished output** to open `Mod` for LayeredFS or `cia` for a rebuilt CIA. **Open build folder** opens the workspace containing the reports.
6. Review `source-preparation-report.json`, `reports/movie-build-report.json`, and `reports/build-report.json` before installing or testing the output. CIA verification is also recorded in `cia/container-report.json`.

The VBS launcher starts the included Windows PowerShell 5.1 installer without opening a command prompt. Startup errors are shown in a dialog and written to a temporary diagnostic log. The installer leaves the original CIA and PC installation unchanged. It stops if validation, extraction, conversion, or output verification fails.

### Working storage

The `2026-10-13-compact-storage` revision reduces duplication while a build is running. CIA reconstruction uses the original export prepared earlier in the same build. Successfully replaced encrypted copies and temporary ROMFS/NCCH images are released between stages. After a movie passes full decoding, its temporary mix/track WAVs are removed; the verified movie, checkpoint and encoding log are retained.

Generated voice and movie files share storage through hard links where supported, with checksum-verified copy fallback. Once the mod passes its manifest checks, extracted PC assets and conversion folders are released. A successful LayeredFS build retains `Mod`; a successful CIA build retains `cia/DQXI-S-3DS.cia` and releases the additional mod folder and private reconstruction data. Metadata reports remain in `reports`, and `storage-cleanup-report.json` records the cleanup stages. Encoding logs remain in `movie-logs`.

ROMFS verification still checks the complete file set, exact path casing and SHA-256 of every decoded file. The expected staged tree is represented by a hash snapshot during readback, so a second full staged tree does not need to remain on disk. Movie and CIA readback checks are unchanged. Failed movie builds retain the required source exports and successful checkpoints for resume.

Storage use depends on source size, output format and filesystem. This revision has no measured Windows peak-size result; leave ample free space. Existing older build folders are not cleaned automatically. For debugging, the preparation script accepts `-KeepIntermediate` to retain intermediate data and use the original reconstruction storage path. The component-resume helper requires PC exports from a failed build or a build made with this option.

### Resume a failed movie build

Extract an updated installer into a fresh folder. Select the same original CIA, PC installation and `code.ips`, enable **Resume an existing movie build**, choose the existing `DQXI-Build-...` folder itself, then select **Resume build**. The installer checks and reuses the original ROMFS export, current PC asset recipes, completed gameplay voices and scene events. CIA/PAK extraction and gameplay voice conversion are skipped after those checks pass. Movie resume applies to builds that stopped before `Mod` or `cia` assembly folders were created.

Successfully decoded movies remain in `pc-movies.partial` if a later movie fails. The installer accepts a checkpoint only when its output checksum, full-decode evidence, source, voice mix, recipe and encoder fingerprints match. Changed or damaged slots are rebuilt. Only a complete set of ten verified movies is promoted to `pc-movies`.

The older installer deleted its temporary movie files after failure; those files must be encoded again once. Existing CIA/PC exports and completed gameplay voices can still be reused. Exports from older revisions without the intro-only voice bank need a fresh build because they do not match the current PC asset recipes.

### Optional support tools

- `Fix-Luma-Codepatch.cmd` repairs a misplaced Luma `code.ips` and backs up an existing file. See [Luma code patch repair]({{ site.github.repository_url }}/blob/main/LUMA_CODEPATCH_FIX.md).
- `Resume-PC-Components.cmd` reprocesses selected PC components from an existing build workspace without extracting the CIA or PAKs again. It does not resume movie conversion or final assembly.
- `Collect-Diagnostics.cmd` and `Collect-Completion-Data.cmd` gather metadata reports. After successful compact cleanup, completion-data collection uses retained summaries; detailed source inspection requires exports from a failed build or `-KeepIntermediate`. These tools are not required for a normal build.

## Output formats

### LayeredFS + Luma code patch

The output contains `Mod/romfs` and code-patch files. For Azahar, use `Mod/romfs` with `Mod/exefs/code.ips`. For Luma, use `Mod/romfs` and `Mod/code.ips` in the game's title folder and enable Game Patching. Follow the current setup guidance for the emulator or console before installing a mod.

### Modified CIA

The installer rebuilds a CIA from the selected original CIA and generated mod data. It writes `cia/DQXI-S-3DS.cia` and a container report into the new output folder. The installer does not install the CIA to a console.

## How the build works

1. **Validate sources.** The installer checks the CIA title ID and structure, the PC file manifest, `code.ips`, and the required PC movie paths before extraction.
2. **Fetch tools.** PC and 3DS tools are downloaded from their upstream releases and verified against pinned SHA-256 hashes. QuickBMS and the DQXI-specific extraction script are included; see the licensing notes below.
3. **Extract selected data.** The restored native C# CIA helper uses CTRTool to extract CIA/TMD content and uses 3dstool to extract the complete ROMFS file tree. The extraction log records its file count and total size; container rebuild verifies the tree against a second extraction. QuickBMS extracts only the PC PAK paths listed in the checked-in asset manifest. The installer does not copy the complete PC installation into the output.
4. **Build resources.** Python scripts build dialogue and UI edits, voice lookup data, and converted PC voices. Before the first movie encode, all movie voice references are checked against the regular and supplemental English PC banks, including `VO_A_010_CS_020`. Complete PC clips are decoded once at their original sample rate and channels, then reused for the movie mixes. Mobipeg's FFmpeg build reads the PC USM movies and writes 3DS MobiClip/MOFLEX output with PC English voice events; the installer shows live frame progress during encoding and decoding. Every movie is fully decoded with the same FFmpeg/MobiClip decoder and checked against its required frame count. `movie-source-checks.json` records the voice sources, `movie-voice-decode.log` records voice decoder commands, and `movie-build-failure.log` records failures even before encoding. Encoder failures also preserve a per-movie diagnostic log in the build folder. The installer applies source-guarded binary replacements and location-title deltas to a working copy of the original ROMFS.
5. **Rebuild and verify.** The native C# helpers orchestrate 3dstool for NCCH/ROMFS/ExeFS rebuilding and Project_CTR's MakeROM for CIA packing. CTRTool reads the packed CIA back; the TMD content set and content hashes are checked before the output is promoted. JSON reports record output hashes, movie stream checks, and build completion.

The native v17 container path is restored. It includes the MIT-licensed Kenzie `BuildSupport.cs`, `Codecs.cs`, `RomBuilder.cs`, and codec tests, with attribution and upstream commit recorded in `third_party/kenzie/UPSTREAM.md`. `CiaSupport.cs` is original Workshop code. CTRTool 1.3.0 and MakeROM 0.18.4 from [Project_CTR](https://github.com/3DSGuy/Project_CTR) remain the CIA/TMD tools; 3dstool 1.2.6 handles NCCH and ROMFS structures. The Kenzie Python delta decoder and source-guarded location-title data are also retained.

## Tool versions and attribution

The installer downloads these tools on demand unless marked **included**. Versions, download URLs, and hashes are pinned in `src/3ds_tool_manifest.json` and `src/pc_tool_manifest.json`.

| Tool | Version | Use | Source and license note |
| --- | --- | --- | --- |
| CTRTool | 1.3.0 | Read/extract CIA and TMD content; output readback checks | [Project_CTR](https://github.com/3DSGuy/Project_CTR); upstream credits original CTRTool work to neimod and later contributions to 3DSGuy. The repository does not identify an explicit license; this project does not claim one. |
| MakeROM | 0.18.4 | Rebuild CIA/CCI containers | [Project_CTR](https://github.com/3DSGuy/Project_CTR); upstream credits MakeROM to 3DSGuy. The repository does not identify an explicit license. |
| 3dstool | 1.2.6 | NCCH, ROMFS, ExeFS, and CCI reconstruction | [dnasdw/3dstool](https://github.com/dnasdw/3dstool), MIT license. |
| rom-converto | 0.23.2 | Encrypted/normalized 3DS content conversion support | [DevYukine/rom-converto](https://github.com/DevYukine/rom-converto), MIT license. |
| QuickBMS | Included, hash-pinned executable | Extract only the PC PAK paths in the manifest | [QuickBMS](https://aluigi.altervista.org/quickbms.htm), GPL-2.0; see the included license text. |
| DQXI QuickBMS script | Included, hash-pinned script | Read the DQXI PC PAK structure | Header credits infogram and spiritovod. This package records no redistribution license for the DQXI-specific script; permission must be established before public redistribution. |
| Python | 3.13.16 embeddable x64 | Run the resource builders | [python.org](https://www.python.org/downloads/release/python-31316/), PSF license included in the downloaded package. |
| vgmstream | r2117 | Decode selected PC audio sources | [vgmstream](https://github.com/vgmstream/vgmstream); see its `COPYING` file and bundled component notices. |
| Mobipeg | 2.3 Windows x64 | Read PC USM movies; encode and verify MobiClip/MOFLEX movies | [quatric/mobipeg](https://github.com/quatric/mobipeg), downloaded from its official [v2.3 release](https://github.com/quatric/mobipeg/releases/tag/v2.3). It is an FFmpeg fork; applicable FFmpeg and bundled encoder licenses/notices govern the binaries. Review the upstream source and release notices before redistribution. The executable is downloaded on first use, not included in this archive. |
| Microsoft VCLibs | 14.0.33321.0 x64 | Private runtime dependency for rom-converto | Downloaded from Microsoft; Microsoft's package terms apply. |
| Kenzie delta decoder | v17-retained | Apply source-guarded location-title artwork deltas | [Kenzie-1377/dqxi-3ds-english-patch](https://github.com/Kenzie-1377/dqxi-3ds-english-patch), MIT license file included under `third_party/kenzie`. The game-derived artwork delta data is not independently cleared by that code license. |
| Kenzie native helpers | v17-retained | C# container reconstruction, safe tool execution, codec routines, and codec tests | [Kenzie-1377/dqxi-3ds-english-patch](https://github.com/Kenzie-1377/dqxi-3ds-english-patch), MIT. Source files and upstream commit are recorded under `third_party/kenzie`. |
| DQXI CIA support | Workshop code | Validate/extract CIA contents, check ROMFS extraction completeness, pack and verify CIA output | Original DQXI Mod Workshop code, MIT; see root `LICENSE`. |

See [third-party notices]({{ site.github.repository_url }}/blob/main/tools/THIRD_PARTY_NOTICES.md) and [copyright notes]({{ site.github.repository_url }}/blob/main/COPYRIGHT.md) for fuller attribution and redistribution information.

## Copyright, trademarks, and redistribution

This is an unofficial fan-made project. It is not affiliated with or endorsed by Square Enix, Nintendo, or upstream tool and patch creators. DRAGON QUEST XI S and related game content remain the property of their rights holders.

The source archive is **not copyright-free**. It contains DQXI-derived patch data: 320 binary replacement members (about 90.2 MB uncompressed), dialogue/UI datasets, `code.ips`, and 28 location-title artwork deltas from the Kenzie patch. It does not contain the ten PC movie source files or a full game dump. Game-derived patch data and derivative artwork are not licensed by the Workshop MIT license.

The QuickBMS executable is included, and the DQXI-specific BMS script is included without a recorded redistribution license. The Project_CTR repository also does not identify an explicit license. Before publishing the source archive or a GitHub Release publicly, resolve these rights and licensing questions. Attribution alone does not grant redistribution permission.

## Verification and limitations

- Python tests and static audits are included under `tests/`. Their latest run is reported with the release deliverable.
- Compact-storage checks are recorded in `tests/COMPACT_STORAGE_VALIDATION.json`: 92 Python tests passed, one optional decoder test skipped, 82 native C# checks passed, and five static audits passed. Cleanup guards, hard-link/copy fallback, cached CIA reuse and complete hash-snapshot readback were exercised with synthetic files. No Windows peak-storage measurement or new Windows end-to-end run is claimed.
- The three retrospective frame maps are validated before encoding. Real FFmpeg checks with synthetic sources confirmed 2,005, 2,163 and 2,592 decoded frames and complete stereo audio for MOVIE_007/008/009. These checks use an FFV1/PCM intermediate and do not claim Windows MOFLEX or game playback validation; see `tests/retrospective-ffmpeg-report.json`.
- The native Windows GUI and actual encrypted CIA/CCI end-to-end builds cannot be run in the Linux authoring environment.
- No emulator or real-console gameplay test is claimed by the installer. Test generated outputs on your own setup and retain your original game files.
- Build reports identify which stages completed. A created folder alone is not proof of a complete build.

## GitHub Pages setup

This page is in the `docs` folder and uses GitHub's Cayman theme.

1. Open **Settings → Pages**.
2. Under **Build and deployment**, select **Deploy from a branch**.
3. Choose branch **main** and folder **/docs**, then save.
4. Resolve the rights and licensing questions above before making the repository or release public.

Do not publish user game files, generated CIAs, or decryption keys in the repository or a GitHub Release.
