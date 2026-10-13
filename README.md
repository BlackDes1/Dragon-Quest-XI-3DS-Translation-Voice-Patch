# DQXI 3DS Patcher

**English text, voice and movie patch builder for the Japanese Nintendo 3DS version of DRAGON QUEST XI.**

DQXI Mod Workshop builds the patch locally from your own Japanese 3DS CIA and a compatible Windows installation of **DRAGON QUEST XI S: Echoes of an Elusive Age – Definitive Edition**. The English installer prepares translated resources, converts PC voices and movies, and produces either a LayeredFS mod or a rebuilt CIA.

**Current version:** v18 · `2026-10-13-compact-storage`  
**Build platform:** Windows x64  
**Intended playback targets:** Azahar and Nintendo 3DS systems using Luma3DS

This is an unofficial community project. It does not include a complete game, a PC installation or the movie source files. The current package **does contain game-derived patch material**; see [Copyright and licensing](#copyright-and-licensing) before redistribution.

## Contents

- [Features](#features)
- [Requirements](#requirements)
- [Getting started](#getting-started)
- [Output formats](#output-formats)
- [How it works](#how-it-works)
- [Storage and build time](#storage-and-build-time)
- [Resuming a failed movie build](#resuming-a-failed-movie-build)
- [Troubleshooting and bug reports](#troubleshooting-and-bug-reports)
- [Project layout](#project-layout)
- [Validation and limitations](#validation-and-limitations)
- [Credits and third-party tools](#credits-and-third-party-tools)
- [Copyright and licensing](#copyright-and-licensing)
- [Contributing](#contributing)
- [GitHub Pages](#github-pages)

## Features

| Area | Included work |
| --- | --- |
| Dialogue | 5,551 dialogue targets, including 58 line-wrap fixes |
| Gameplay voices | 5,095 runtime voice links, 50 additional voice cases and conversion of 5,048 PC voice clips |
| Interface | 2,920 UI text edits and 85 reviewed menu fixes |
| Movies | Local conversion of all ten required 3DS MOFLEX movie slots from PC USM movies, English voices and event timing |
| Location artwork | Up to 28 location-title updates, applied only when the original file matches its expected hash |
| Output | LayeredFS with the included code patch, or a reconstructed CIA |
| Installer | English GUI, live progress, movie checkpoints and a button to open the finished output |

The included `code.ips` is retained unchanged. You do not need the older seven-part mod archive or separate mod folders. Original CIA and PC installation files are read as inputs and are not overwritten.

These counts describe the shipped build recipes and targets. They do not establish that every scene has been tested in an emulator or on a console.

## Requirements

| Requirement | Details |
| --- | --- |
| Operating system | Windows with an x64 environment capable of running the pinned Windows tools |
| Installer runtime | Windows PowerShell 5.1, Windows Forms and Windows Script Host for the `.vbs` launcher |
| 3DS game | Your own unmodified Japanese DRAGON QUEST XI CIA, title ID `0004000000199200`; encrypted and decrypted input are supported |
| PC game | Your own complete, compatible Windows DRAGON QUEST XI S installation with its required PAKs, English voice banks and USM movies |
| Code patch | The `code.ips` supplied with this v18 package |
| Internet | Required when the pinned tool downloads are not already in the local cache |
| Working storage | Ample free space for extraction, audio/video conversion and reconstruction; allow several tens of GB, with actual peak use depending on your sources and output format |

The 3DS input is **DRAGON QUEST XI**. The PC resources come from **DRAGON QUEST XI S**. Other regions, game editions and incomplete PC installations are not supported by the current recipes. Native Linux/macOS installer use and Windows ARM64 compatibility are not validated.

Select the PC installation root containing `Engine` and `Game`, rather than the `Movies` folder itself. The default is:

```text
C:\Program Files (x86)\Steam\steamapps\common\DRAGON QUEST XI S
```

The installer reads movies from `Game\Content\Movies` beneath that root. Required PC files are listed in [the installation manifest](src/pc_installation_manifest.json).

A separate Python installation or C# compiler is not required for normal GUI use. The installer obtains its private Python runtime and compiles the included native helper sources through Windows PowerShell.

## Getting started

1. Obtain the v18 installer ZIP and extract the entire archive to a normal folder. Do not launch files from inside the ZIP.
2. Double-click **`DQXI-Mod-Installer.vbs`**. Keep the `src`, `tools` and other supplied folders together.
3. Select your original Japanese CIA, the supplied `code.ips` and the PC installation root.
4. Choose a **new build folder** outside your game installations and input files. A short path helps avoid legacy tool path-length limits.
5. Select **LayeredFS + Luma code patch** or **Modified CIA**, then select **Build mod**.
6. Wait until the installer reports successful completion. First use also downloads and verifies the required tools.
7. Select **Open finished output** to open the completed `Mod` or `cia` folder. **Open build folder** opens the workspace containing reports and diagnostics.

The launcher opens the GUI without a command-prompt window. The installer builds files locally; it does not install a CIA on a console or configure your emulator automatically.

Review `source-preparation-report.json` and the retained verification reports before using the output. A directory or a `.partial` file alone is not a completed build.

## Output formats

| Format | Finished output | Intended use |
| --- | --- | --- |
| LayeredFS | `Mod/romfs`, `Mod/exefs/code.ips` and `Mod/code.ips` | Mod loading in Azahar or game patching through Luma3DS |
| Modified CIA | `cia/DQXI-S-3DS.cia` | A reconstructed game container for a compatible setup |

### Azahar

Use the generated `Mod/romfs` and `Mod/exefs/code.ips` in the game's mod location for title ID `0004000000199200`. Follow the instructions for your installed [Azahar](https://github.com/azahar-emu/azahar) version, and retain your original game files.

### Luma3DS

For LayeredFS, copy the generated `Mod/romfs` folder and `Mod/code.ips` into:

```text
SD:/luma/titles/0004000000199200/
```

The resulting paths must be `SD:/luma/titles/0004000000199200/romfs/` and `SD:/luma/titles/0004000000199200/code.ips`. Enable **Enable game patching** in Luma3DS and restart the console. See [Luma3DS optional features](https://github.com/LumaTeam/Luma3DS/wiki/Optional-features) for platform instructions.

The supplied `Fix-Luma-Codepatch.cmd` can repair an existing code-patch location and backs up the previous file. Its purpose is described in [the repair guide](LUMA_CODEPATCH_FIX.md).

## How it works

1. **Validate inputs.** Check the CIA title ID and structure, required PC files and the supplied code patch. The installer does not require one fixed checksum for the entire original CIA.
2. **Prepare tools.** Download missing pinned tool versions and verify their SHA-256 hashes. Reuse valid cached tools on later builds.
3. **Extract selected sources.** Export the CIA contents, ROMFS and ExeFS. Extract the PC assets listed in the recipes instead of copying the complete PC installation.
4. **Build resources.** Apply source-guarded text and UI changes, prepare voice lookup data, convert gameplay voices and create ten MOFLEX movie slots from PC movies and English voice events.
5. **Verify outputs.** Check generated resources and fully decode each movie to validate its streams and expected frame count. CIA builds also verify the reconstructed filesystems and read the packed CIA back to check its content set and hashes.
6. **Publish the local result.** Promote the verified output, retain reports and release obsolete intermediate files.

The current implementation uses the Kenzie native helper workflow together with CTRTool, MakeROM, 3dstool and rom-converto. Movie conversion uses the pinned **Mobipeg 2.3** encoder/decoder. Tool versions and download hashes are recorded in [the 3DS tool manifest](src/3ds_tool_manifest.json) and [the PC tool manifest](src/pc_tool_manifest.json).

## Storage and build time

The compact-storage revision reduces duplication throughout the build:

- CIA reconstruction reuses the first original export instead of extracting the entire CIA again.
- Obsolete encrypted content copies and temporary ROMFS/NCCH images are released between successful stages.
- Verified movie slots release their temporary mix/track WAVs while keeping their MOFLEX file, checkpoint and log.
- Generated voices and movies share storage through hard links where supported. Other filesystems use checksum-verified copies.
- Once the mod is verified, extracted PC assets and conversion folders are released. After success, the chosen final output remains: `Mod` for LayeredFS or the rebuilt CIA for CIA mode.

Reports are preserved under `reports`. Encoding logs remain in `movie-logs`, and `storage-cleanup-report.json` records cleanup stages. Failed movie builds retain the required source exports and successful checkpoints for resume.

Movie encoding and full decoding can still take considerable time. There is no guaranteed build duration or measured Windows peak-storage figure for this revision. Existing older build folders are not cleaned automatically.

Tools are cached under `%LOCALAPPDATA%\DQXI-Mod-Werkstatt\tools`. For debugging, the preparation script accepts `-KeepIntermediate` to retain working data; this is not needed for normal GUI builds.

## Resuming a failed movie build

1. Start the updated installer from a freshly extracted installer folder.
2. Select the same original CIA, PC installation and supplied code patch.
3. Enable **Resume an existing movie build**.
4. Select the existing `DQXI-Build-...` folder itself as the output folder.
5. Select **Resume build**.

The installer verifies existing CIA/PC exports, gameplay voices and scene data before reusing them. A completed movie checkpoint is accepted only when its checksum, full-decode evidence, source, voice mix, recipe and encoder fingerprints still match. Changed or damaged slots are rebuilt.

GUI resume applies to builds that stopped **before `Mod` or `cia` assembly folders were created**. Keep the whole failed build folder, including `pc-movies.partial`. Deleted movie outputs cannot be recovered through resume. Exports from older revisions missing required voice banks may require a fresh build.

`Resume-PC-Components.cmd` is a separate helper for selected PC components. It requires retained PC exports and does not resume movie conversion or final assembly.

## Troubleshooting and bug reports

| Symptom | What to check |
| --- | --- |
| The installer does not open | Extract the complete ZIP, keep its folders together and confirm Windows Script Host and Windows PowerShell 5.1 are available. Startup failures produce a dialog and temporary log. |
| Required PC files are missing | Select the root containing `Engine` and `Game`. Confirm the installation has the required English assets and movies. |
| CIA validation or extraction fails | Confirm the Japanese title ID and an unmodified source. Inspect the extraction log; do not bypass validation or tool checksum checks. |
| Movie conversion fails or leaves an empty file | Inspect `movie-build-failure.log`, the movie source checks and per-movie failure logs. An empty or partial file is rejected. Preserve the build folder for resume. |
| A tool download fails | Check connectivity to the official download source. Retry with the pinned version; manually replacing tools can trigger checksum rejection. |
| A rebuild reports a long path | Use a shorter build-folder path and avoid deeply nested installer folders. |
| Voices or text differ on the console | Verify the correct title folder, `code.ips` placement and Luma game patching. Report the exact scene and device; passing file checks does not establish hardware behavior. |

Useful files include:

- `source-preparation-report.json` — selected format, completion state and final output path.
- `reports/build-report.json` and `reports/movie-build-report.json` — resource and movie verification.
- `reports/extract.log` — preserved original extraction log; failed builds may still use `original-3ds/extract.log`.
- `cia/container-report.json` — CIA readback verification and final file hash.
- `movie-source-checks.json`, `movie-voice-decode.log`, `movie-logs` and failure logs — movie diagnostics.
- `storage-cleanup-report.json` — released intermediate files and cleanup warnings.

Use `Collect-Diagnostics.cmd` to collect known diagnostic reports. `Collect-Completion-Data.cmd` gathers parser metadata; successful compact builds provide retained summaries because detailed source exports have been released.

When opening an issue, include the installer revision, Windows version, output format, emulator/Luma version if relevant, exact error, relevant report fields and steps to reproduce. Review logs for private paths and sensitive material before sharing. **Do not attach game dumps, PAKs, decrypted files, keys, voices, movies or generated game outputs.**

## Project layout

| Path | Purpose |
| --- | --- |
| `DQXI-Mod-Installer.vbs` | Double-click GUI launcher |
| `src/` | PowerShell build orchestration, Python builders and pinned manifests |
| `src/recipes/` | Resource conversion and mapping recipes |
| `src/verified-inputs/` | Source-guarded patch datasets and payloads; see copyright notes |
| `third_party/kenzie/` | Retained upstream helpers, decoder, license and provenance |
| `tools/` | Included extraction components and third-party notices |
| `tests/` | Automated checks and validation reports |
| `docs/` | Extended documentation and GitHub Pages configuration |
| `code.ips` | The supplied executable code patch |

## Validation and limitations

The compact-storage validation report records **92 passing Python tests**, **one skipped optional decoder test**, **82 passing native C# checks** and **five passing static audits**. Checks cover guarded cleanup, hard-link/copy fallback, CIA export reuse, complete ROMFS hash-snapshot readback, source validation and movie checkpoints.

See [compact-storage validation](tests/COMPACT_STORAGE_VALIDATION.json), [movie resume validation](tests/MOVIE_RESUME_VALIDATION.json) and [synthetic FFmpeg checks](tests/retrospective-ffmpeg-report.json) for their scope.

Automated checks do not replace game testing. The new compact-storage revision has not completed a Windows build using actual game sources in the authoring environment. Synthetic FFmpeg tests do not establish actual Windows MOFLEX encoding or game playback. No complete emulator or original-hardware gameplay verification is claimed. Test representative dialogue, voice playback, page transitions, menus and movies on your own setup.

## Credits and third-party tools

Thanks to **Kenzie-1377** and all upstream tool authors and contributors. This project retains Kenzie native C# helpers and the Python delta decoder; local changes and source commits are documented in [UPSTREAM.md](third_party/kenzie/UPSTREAM.md). The accompanying MIT notice applies to the retained code, not to game-derived artwork or patch data.

| Component / author | Version used | Role and license note |
| --- | --- | --- |
| [Kenzie-1377 / dqxi-3ds-english-patch](https://github.com/Kenzie-1377/dqxi-3ds-english-patch) | Pinned source snapshots | Native helpers, delta decoder and source-matched patch work. Retained helper code: MIT; game-derived data has separate rights. |
| [CTRTool / Project_CTR](https://github.com/3DSGuy/Project_CTR) — neimod, 3DSGuy and contributors | 1.3.0 | CIA/TMD extraction and readback. No explicit redistribution license is identified in this package's notices. |
| [MakeROM / Project_CTR](https://github.com/3DSGuy/Project_CTR) — 3DSGuy and contributors | 0.18.4 | CIA reconstruction. Same unresolved license status recorded for Project_CTR. |
| [3dstool / Daowen Sun](https://github.com/dnasdw/3dstool) | 1.2.6 | ROMFS, ExeFS and NCCH processing. MIT. |
| [rom-converto / DevYukine](https://github.com/DevYukine/rom-converto) | 0.23.2 | Encrypted 3DS content conversion. MIT. |
| [QuickBMS / Luigi Auriemma](https://aluigi.altervista.org/quickbms.htm) | Included, hash-pinned | Selected PC PAK extraction. GPL-2.0; bundled license text provided. |
| DQXI-specific QuickBMS script — infogram and spiritovod credits | Included, hash-pinned | DQXI PAK extraction rules. Redistribution terms are not recorded in the package. |
| [Python / Python Software Foundation](https://www.python.org/) | 3.13.16 embeddable x64 | Resource builders. PSF license; runtime notices supplied with the download. |
| [vgmstream contributors](https://github.com/vgmstream/vgmstream) | r2117 | PC audio decoding. Its `COPYING` and component notices apply. |
| [Mobipeg / quatric](https://github.com/quatric/mobipeg) and FFmpeg contributors | 2.3 Windows x64 | USM input, MobiClip/MOFLEX encoding and decoding. FFmpeg and component licenses depend on the release build configuration. |
| Microsoft VCLibs Desktop runtime | 14.0.33321.0 x64 | Private runtime support. Microsoft's package terms apply. |

Except for the included QuickBMS components and retained helper sources, the listed dependencies are downloaded when needed. Downloading a dependency does not change its license. See [third-party notices](tools/THIRD_PARTY_NOTICES.md) for distribution details and license links.

## Copyright and licensing

**This package is not copyright-free.** It does not contain a complete retail game image, a complete PC installation or the PC movie sources. It does contain game-derived binary replacement payloads, dialogue/UI datasets, voice-map/resource data, `code.ips` and location-title artwork deltas.

The [root MIT license](LICENSE) covers **original Workshop source code only**. It does not license game-derived content, translation/artwork data, trademarks or third-party components. The retained Kenzie code has its own MIT notice. Other tools remain subject to their respective licenses.

DRAGON QUEST game content and associated trademarks remain the property of their respective rights holders, including Square Enix. Nintendo trademarks belong to Nintendo. This project is not affiliated with, endorsed by or sponsored by Square Enix or Nintendo.

Use your own lawfully obtained input files. Do not redistribute original game assets or generated game containers through this repository. Before publishing the current installer/source package publicly, resolve the rights for game-derived payloads and the DQXI-specific BMS script, and review the Project_CTR license status. Attribution alone does not grant redistribution permission. See [COPYRIGHT.md](COPYRIGHT.md) for the package inventory and recorded licensing boundaries.

## Contributing

Contributions to original code, build reliability, validation, performance, documentation and reproducible bug reports are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.

Keep dependency versions and hashes synchronized, record the source and license of new components, and describe what was tested. Do not commit game files, full source dialogue, audio/video assets, keys or generated outputs.

Run the Python suite from the repository root with:

```bash
python -m unittest discover -s tests -p '*_tests.py'
```

Optional checks may need an independent decoder, platform tools or local fixtures. State any skipped tests and distinguish synthetic checks from actual game, emulator or console testing.

## GitHub Pages

GitHub displays this `README.md` on the repository's main page. Extended documentation is available in [docs/index.md](docs/index.md).

To publish the included documentation as a separate GitHub Pages site after the relevant redistribution review:

1. Commit the `docs` folder, including `index.md` and `_config.yml`.
2. Open **Settings → Pages** in the repository.
3. Select **Deploy from a branch**.
4. Choose the branch containing the documentation, such as `main`, and the **`/docs`** folder.
5. Save and check the Pages deployment result.

See [GitHub's publishing-source guide](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site) for the current instructions. Publish documentation and permitted project materials only; game inputs and generated game outputs do not belong in the Pages site.
