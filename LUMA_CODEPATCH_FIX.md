# Repair the Luma code patch

The v18 package includes the current `code.ips`; it does not generate a new one. The builder writes identical bytes to both expected output locations:

- `pc-dialogue/code.ips` for `SD:/luma/titles/0004000000199200/code.ips`
- `pc-dialogue/exefs/code.ips` for the Azahar mod folder

The patch is checked against SHA-256 `41c57f46acaac44679a22ac1bf3fdfceb70a2a11c35bf287b3930c9da664bcbf`. If an existing Luma installation needs repair, run `Fix-Luma-Codepatch.cmd`, select the `code.ips` from the installer output, and select the existing Luma title folder. The helper saves a timestamped backup before replacing an existing file.

In Luma, enable **Enable game patching**. Fully power off the 3DS, then restart it. Test voice playback, dialogue page changes, and first-line alignment in the same scene that works in the emulator.

The PC dialogue step remains a partial build. A correct patch path alone does not establish complete translation coverage or runtime behavior on original hardware. No original-hardware test is claimed. If the display still differs, investigate the specific dialogue scene on the device.
