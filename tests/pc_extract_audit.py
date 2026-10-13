from pathlib import Path
import json
import re

root = Path(__file__).resolve().parents[1]
manifest = json.loads((root / 'src' / 'pc_asset_manifest.json').read_text(encoding='utf-8'))
script = (root / 'src' / 'Extract-PCAssets.ps1').read_text(encoding='utf-8')
assert manifest['schema_version'] == 3
assets = manifest['assets']
assert len(assets) == 1112
assert len({(a['chunk'], a['path'].casefold()) for a in assets}) == 1112
assert sum(a['chunk'] == 'pakchunk0-WindowsNoEditor' for a in assets) == 779
assert sum(a['chunk'] == 'pakchunk1-WindowsNoEditor' for a in assets) == 333
assert sum(a['kind']=='voice' for a in assets) == 424
assert sum(a['kind']=='voice' and a['language']=='unverified' for a in assets) == 0
assert sum(a['kind']=='text' for a in assets) == 144
assert sum(a['kind']=='voice_extra' for a in assets) == 496
assert sum(a['kind']=='scene' for a in assets) == 48
assert manifest['additional_voice_banks'] == 248
intro_bank='JackGame/Content/Sounds/Voice_NE/CS/VO_A_010_CS_020/SWAV_VO_A_010_CS_020'
assert all(any(a['chunk']=='pakchunk0-WindowsNoEditor' and a['path']==intro_bank+ext
               and a['kind']=='voice_extra' for a in assets) for ext in ('.uasset','.uexp'))
assert manifest['scene_map_pairs'] == 24
for kind, suffixes in (('voice_extra', {'.uasset','.uexp'}), ('scene', {'.umap','.uexp'})):
    groups = {}
    for asset in assets:
        if asset['kind'] == kind:
            groups.setdefault((asset['chunk'],asset['path'].rsplit('.',1)[0].casefold()),set()).add('.'+asset['path'].rsplit('.',1)[-1].lower())
    assert all(suffixes == values for values in groups.values())
assert all(a['chunk']=='pakchunk0-WindowsNoEditor' for a in assets if a['kind']=='voice_extra')
movie_maps={
 ('pakchunk0-WindowsNoEditor','Maps/Product/Title_CS_A010_010'),
 ('pakchunk0-WindowsNoEditor','Maps/Product/World/F01/C01_01/C01_01_CS_C010_120'),
 ('pakchunk0-WindowsNoEditor','Maps/Product/World/F01/D02/D02_CS_A020_TitleMovie'),
 ('pakchunk1-WindowsNoEditor','Maps/Product/World/F18/S14/S14_CS_A180_100'),
 ('pakchunk1-WindowsNoEditor','Maps/Product/World/F18/S14/S14_CS_C300_030'),
 ('pakchunk1-WindowsNoEditor','Maps/Product/World/F18/S14/S14_CS_C300_050'),
 ('pakchunk1-WindowsNoEditor','Maps/Product/World/F93_H/D17/D17_CS_B160_090'),
}
scene_bases={(a['chunk'],a['path'].rsplit('.',1)[0]) for a in assets if a['kind']=='scene'}
assert movie_maps <= scene_bases
assert all(sum(a['chunk']==chunk and a['path'].rsplit('.',1)[0]==base and a['kind']=='scene' for a in assets)==2 for chunk,base in movie_maps)
for asset in assets:
    p = asset['path']
    assert not p.startswith(('/', '\\'))
    assert '..' not in p.split('/')
    assert '\\' not in p
    assert re.fullmatch(r'[A-Za-z0-9_./-]+', p)
assert "'-o' '-f' $filter $BmsPath $inputPak $pakOutput" in script
assert 'Required PC archive missing' in script
assert 'Extracted PC asset is missing' in script
assert 'Extracted PC asset is ambiguous' in script
assert "complete=($results.Count -eq $manifest.assets.Count)" in script
assert not list((root / 'src').rglob('*.pak'))
assert not list((root / 'src').rglob('*.uexp'))
assert all('verified-inputs' in p.parts for p in (root / 'src').rglob('*.bcstm'))
print('PC extraction manifest audit passed: 424 voice banks + 248 supplemental voice pairs (including the CS_020 intro bank) + 24 scene-map pairs + 144 text files.')
