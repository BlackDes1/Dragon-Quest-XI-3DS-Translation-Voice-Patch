from hashlib import sha256
from pathlib import Path

project = Path(__file__).resolve().parents[1]
ips_path = project / "code.ips"
data = ips_path.read_bytes()
expected_hash = "41c57f46acaac44679a22ac1bf3fdfceb70a2a11c35bf287b3930c9da664bcbf"
assert sha256(data).hexdigest() == expected_hash
assert data[:5] == b"PATCH" and data[-3:] == b"EOF"

position = 5
end = len(data) - 3
records = patched_bytes = highest_offset = 0
while position < end:
    assert end - position >= 5
    offset = int.from_bytes(data[position:position + 3], "big")
    size = int.from_bytes(data[position + 3:position + 5], "big")
    position += 5
    if size:
        assert end - position >= size
        position += size
        count = size
    else:
        assert end - position >= 3
        count = int.from_bytes(data[position:position + 2], "big")
        assert count > 0
        position += 3
    records += 1
    patched_bytes += count
    highest_offset = max(highest_offset, offset + count)
assert position == end
assert (len(data), records, patched_bytes, highest_offset) == (7682, 194, 6704, 0x6BFB58)

code_ips = (project / "src" / "CodeIps.ps1").read_text(encoding="utf-8")
prepare = (project / "src" / "Prepare-Sources.ps1").read_text(encoding="utf-8-sig")
installer = (project / "src" / "Installer.ps1").read_text(encoding="utf-8-sig")
container = (project / "src" / "Build-3DSContainer.ps1").read_text(encoding="utf-8-sig")
native = (project / "third_party" / "kenzie" / "native" / "RomBuilder.cs").read_text(encoding="utf-8")
overlay = (project / "src" / "python" / "verified_overlay.py").read_text(encoding="utf-8")
assert "Get-DQXICurrentCodeIpsInfo" in code_ips
assert "Build-VerifiedOverlay.ps1" in prepare
assert "shutil.copyfile(ips, temp/'exefs/code.ips')" in overlay
assert "shutil.copyfile(ips, temp/'code.ips')" in overlay
assert "'-CodeIps',$codeInput.Text.Text" in installer
assert "GeneratedMod 'exefs/code.ips'" in container or "GeneratedMod 'exefs\\code.ips'" in container
assert "NativeCodecs.ApplyIps(File.ReadAllBytes(code), File.ReadAllBytes(Path.Combine(mod, \"exefs\", \"code.ips\")))" in native
print("Current code.ips audit passed: exact supplied patch, valid 194-record IPS, verified Azahar/Luma destinations.")
