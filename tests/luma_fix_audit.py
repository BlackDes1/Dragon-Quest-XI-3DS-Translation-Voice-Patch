from pathlib import Path
root=Path(__file__).resolve().parents[1]
s=(root/'src'/'Fix-LumaCodePatch.ps1').read_text(encoding='utf-8')
assert "41c57f46acaac44679a22ac1bf3fdfceb70a2a11c35bf287b3930c9da664bcbf" in s
assert "IPS-Codepatch (*.ips)|*.ips" in s
assert '$source = $sourceDialog.FileName' in s
assert "Join-Path $target 'code.ips'" in s
assert "Join-Path $target 'romfs'" in s
assert 'before_luma_fix_' in s
assert 'Get-FileHash' in s
print('Luma fix source audit passed.')
