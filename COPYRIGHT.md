# Copyright and redistribution

## This is not a copyright-free archive

The v18 installer source package does not include a complete retail CIA/3DS image, a complete PC game installation, or movie files. It does, however, include patch material derived from game and upstream mod files. The package must not be described as containing no copyrighted material.

The current v18 package includes:

- 320 binary replacement-member records. The referenced payload files total approximately 90.2 MB before ZIP compression and are applied to matching Japanese 3DS resource archives.
- Dialogue, UI, voice-map, and resource datasets used to build the English patch.
- The v18 code.ips file, which patches game code.
- 28 location-title artwork delta payloads retained from the Kenzie DQXI 3DS English patch. They apply only when the expected source hash matches.
- QuickBMS and a DQXI-specific QuickBMS extraction script. The executable is a third-party tool; the script header credits infogram and spiritovod, but this package does not record a redistribution license for the script.

These patch payloads may reproduce or derive from copyrighted game content, translations, or artwork. The original game and its contents remain the property of their respective rights holders, including Square Enix. The MIT license at the repository root does not grant rights to game-derived data, trademarks, or upstream mod material.

## User-supplied inputs

The installer requires the user's original Japanese DQXI S CIA and compatible PC installation. It reads selected USM movies and English voice sources from that PC installation and converts ten movie slots locally; neither those movie files nor a separate seven-part mod package is included or required. The installer does not alter the original CIA or PC files.

Do not add original game archives, decrypted game files, generated mod outputs, full audio/video files, or keys to the public repository or issue tracker. A checksum or file manifest is not a substitute for permission to distribute the associated contents.

## License scope

- The root MIT license applies only to original DQXI Mod Workshop source code.
- The MIT license in third_party/kenzie/LICENSE accompanies the retained Kenzie delta decoder. It does not establish rights to redistribute DQXI artwork or other game-derived patch data.
- Third-party tools have their own licenses and copyright holders. See tools/THIRD_PARTY_NOTICES.md.
- Project_CTR has no explicit license identified in the upstream repository at the time this page was prepared. No Project_CTR source code or release binary is stored in this source archive; the installer downloads pinned binaries from the official upstream releases.
- The bundled DQXI-specific QuickBMS script has no redistribution terms recorded here. Obtain permission from the script's rightsholders or replace it with a properly licensed implementation before publishing this package publicly.

## Before publishing

Resolve the redistribution status of the game-derived binary/text/artwork payloads and the DQXI-specific BMS script. Keep the required upstream notices with their corresponding components. If those rights cannot be established, do not publish the current installer archive or repository as a public release. Describing the project as a patch tool or adding attribution does not itself grant redistribution rights.

This file documents the known contents and licensing boundaries of this package; it is not a legal opinion or a grant of rights from any third party.
