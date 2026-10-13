# Contributing

Thank you for helping improve the DQXI Mod Workshop. Please keep changes focused on the installer, validation, documentation, and original code.

## Before opening a pull request

- Do not add retail CIA/3DS images, decrypted game files, title keys, full PC assets, audio/video files, or generated mod outputs.
- Do not upload game files, copyrighted dialogue, or private paths/logs to an issue. Share the error message, relevant report fields, and source file hashes where useful.
- Do not add third-party scripts, binaries, or patch assets without documenting their source, author, license, and redistribution permission.
- Keep tool versions and SHA-256 values in the manifests synchronized when intentionally updating a dependency.
- Keep build claims accurate. Do not mark game, emulator, console, or Windows end-to-end testing as complete unless it was actually run.

## Tests

Run the Python test suite from the repository root with:

    python -m unittest discover -s tests -p '*_tests.py'

Some static audit scripts take additional source fixtures or game files that are not part of this repository. Do not commit those fixtures if they contain game material. Describe any tests you could not run in the pull request.

## Copyright review

The current v18 package already contains game-derived patch material and has unresolved redistribution questions documented in COPYRIGHT.md. Contributions do not change that status. Please do not claim that the repository is copyright-free or public-release-cleared unless the relevant rights have been verified.
