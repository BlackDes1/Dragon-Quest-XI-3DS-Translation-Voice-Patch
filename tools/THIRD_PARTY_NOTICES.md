# Third-party software and content notices

This file identifies external software used by the v18 installer and the components included in the source package. Tool versions and download hashes are pinned in src/3ds_tool_manifest.json and src/pc_tool_manifest.json. Except where marked **included**, tools are downloaded from upstream at build time and are not bundled as executables in this source archive. Their own licenses and notices continue to apply.

## Tools

| Component | Version | Copyright / license information | Distribution in this package |
| --- | --- | --- | --- |
| CTRTool | 1.3.0 | Project_CTR; upstream credits original CTRTool work to neimod and later contributions to 3DSGuy (see [issue #103](https://github.com/3DSGuy/Project_CTR/issues/103)). The repository does not identify an explicit license; see [upstream issue #150](https://github.com/3DSGuy/Project_CTR/issues/150). | Downloaded from the official [Project_CTR release](https://github.com/3DSGuy/Project_CTR/releases/tag/ctrtool-v1.3.0); not bundled. |
| MakeROM | 0.18.4 | Project_CTR / 3DSGuy; see the upstream [Project_CTR issue #103](https://github.com/3DSGuy/Project_CTR/issues/103). No explicit license is identified in the upstream repository; see [issue #150](https://github.com/3DSGuy/Project_CTR/issues/150). | Downloaded from the official [Project_CTR release](https://github.com/3DSGuy/Project_CTR/releases/tag/makerom-v0.18.4); not bundled. |
| 3dstool | 1.2.6 | Copyright (c) 2014-2020 Daowen Sun; MIT license. See the [upstream repository](https://github.com/dnasdw/3dstool) and its [LICENSE](https://github.com/dnasdw/3dstool/blob/master/LICENSE). | Downloaded from the upstream [v1.2.6 release](https://github.com/dnasdw/3dstool/releases/tag/v1.2.6); not bundled. |
| rom-converto | 0.23.2 | DevYukine; MIT license. See the [upstream repository](https://github.com/DevYukine/rom-converto) and its [LICENSE](https://github.com/DevYukine/rom-converto/blob/main/LICENSE). | Downloaded from the pinned upstream release; not bundled. |
| QuickBMS | Hash-pinned executable | Copyright (c) Luigi Auriemma; GPL-2.0. See the [official QuickBMS site](https://aluigi.altervista.org/quickbms.htm), the [source mirror and license](https://github.com/LittleBigBug/QuickBMS), and the included [GPL-2.0 license text](licenses/GPL-2.0.txt). | The executable is included in tools/quickbms_4gb_files.exe. The source release does not include modified QuickBMS source. |
| DQXI-specific QuickBMS script | Version 0.4.20a header; DQXI modification v4 | The header credits the Unreal Engine script to its upstream author, modification for DQXI to infogram, and a fix to spiritovod. This package contains no license or redistribution permission for the DQXI-specific script. | Included as tools/dqxi_pak_extract.bms. Obtain permission or replace it with a licensed script before public redistribution. |
| Python embeddable runtime | 3.13.16 x64 | Python Software Foundation license. The runtime package includes LICENSE.txt. | Downloaded from [python.org](https://www.python.org/downloads/release/python-31316/); not bundled. |
| vgmstream | r2117 | Copyright belongs to the vgmstream contributors and included codec projects. See the upstream [COPYING](https://github.com/vgmstream/vgmstream/blob/master/COPYING) and notices. | Downloaded from the [r2117 release](https://github.com/vgmstream/vgmstream/releases/tag/r2117); not bundled. The downloaded archive contains its notices. |
| Microsoft VCLibs Desktop runtime | 14.0.33321.0 x64 | Copyright and license terms belong to Microsoft; see the [official Microsoft package source](https://download.microsoft.com/download/4/7/c/47c6134b-d61f-4024-83bd-b9c9ea951c25/Microsoft.VCLibs.x64.14.00.Desktop.appx). | Selected runtime files are downloaded on demand for the private tool runtime; no system-wide installation is performed. |
| Mobipeg | 2.3 Windows x64 | [quatric/mobipeg](https://github.com/quatric/mobipeg) is a fork of FFmpeg with MobiClip/MOFLEX support. The release binary may include GPL-enabled FFmpeg components; the exact applicable licenses and source notices are determined by its build configuration. See upstream [source](https://github.com/quatric/mobipeg) and [v2.3 release](https://github.com/quatric/mobipeg/releases/tag/v2.3), including its license/COPYING files and build configuration. | Official release ZIP downloaded on demand; not included in this package. Its archive hash is `9f15c9f7359be362ae8704ee0a0d6fc8046162311eefe471f3466ebf4530831b`; the installer validates `ffmpeg.exe` and `ffprobe.exe` individually. |

## Retained upstream patch component

The project retains Kenzie-1377's Python delta decoder and 28 source-guarded location-title artwork deltas from [dqxi-3ds-english-patch](https://github.com/Kenzie-1377/dqxi-3ds-english-patch), upstream version 0.7.0 at commit ea515509d0ab082320bedfbb27602ae2b655c956. The MIT license file is included at third_party/kenzie/LICENSE. The decoder is code; the game-derived artwork delta payloads are not independently cleared by that code license.

The native helper files `BuildSupport.cs`, `Codecs.cs`, and `RomBuilder.cs` are included and used. They are MIT-licensed Kenzie upstream code, with local reconstruction changes documented in `third_party/kenzie/UPSTREAM.md`. `CodecTests.cs` is included under `tests/native/` and used only by the test harness. The DQXI-specific `CiaSupport.cs` is original Workshop code, licensed under the root MIT license. CIA/TMD tools remain CTRTool and MakeROM from Project_CTR; 3dstool handles NCCH and ROMFS extraction/reconstruction. The extraction log records the ROMFS file count and size, and the CIA rebuild stage compares the full ROMFS tree against a fresh extraction.

## Game and mod material

The source archive contains DQXI-derived binary replacement members, translation/UI data, code.ips, and artwork delta payloads. The ten movie files needed by the full build are supplied separately by the user. None of these materials are licensed by the root MIT license. See [COPYRIGHT.md](../COPYRIGHT.md) before redistributing the package.

DRAGON QUEST XI S and associated game content are the property of their respective rights holders. This project is unofficial and is not endorsed by Square Enix or Nintendo.

## License status note

Attribution is not the same as permission. Project_CTR has no explicit license identified in its upstream repository, and this package records no redistribution license for the DQXI-specific BMS script. Resolve those conditions, along with the game-derived patch data rights, before making a public source repository or release.
