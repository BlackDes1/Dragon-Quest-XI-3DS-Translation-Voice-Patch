"""Typed, bounds-checked DQXIS cooked native text DataTable reader.

JackDataTableText: FString, uint8 Type, FName TalkerID, int32 Flags.
JackDataTableFukidasi extends that with two uint8 enum fields. Native data
does not contain SDK alignment padding. Exact row and export consumption.
"""
import ue4_voice_reader as ue


def table_header(package):
    """Describe the native schema without exporting text or opaque payloads."""
    exports = [e for e in package.exports if package.class_name(e)=='DataTable']
    if len(exports)!=1: raise ValueError('expected_one_datatable')
    export=exports[0]
    tags,end=package.properties(export['data'])
    props={t['name']:t for t in tags}
    prop=props.get('RowStruct')
    if not prop or prop['type']!='ObjectProperty': raise ValueError('missing_row_struct')
    obj=package.object(package.value(prop))
    if not obj or obj.get('class_name')!='ScriptStruct': raise ValueError('invalid_row_struct')
    schema=obj['name']
    return export, end, dict(schema=schema, counts=package.counts,
                            export_index=export['index'], export_bytes=len(export['data']),
                            properties=[dict(name=t['name'], type=t['type'], size=t['size'])
                                        for t in tags])


def describe(package):
    return table_header(package)[2]


def read(package):
    export,end,profile=table_header(package)
    schema=profile['schema']
    if schema not in {'JackDataTableText','JackDataTableFukidasi'}:
        raise ValueError('unsupported_text_row_schema:'+schema)
    r=ue.Reader(export['data'],end)
    if r.number('i')!=0: raise ValueError('unsupported_datatable_guid')
    total=ue.count(r,200000)
    rows=[];names=set()
    for index in range(total):
        start=r.position;name=package.name(r)
        if name in names: raise ValueError('duplicate_text_label:'+name)
        names.add(name)
        size=ue.count(r,1048576);raw=r.take(size);row=ue.Reader(raw)
        text=row.string()
        values=dict(Text=text,Type=row.number('B'),TalkerID=package.name(row),Flags=row.number('i'))
        if schema=='JackDataTableFukidasi':
            values.update(FukidasiType=row.number('B'),FukidasiDuration=row.number('B'))
        if row.position!=len(raw): raise ValueError('native_text_row_end_mismatch:'+name)
        rows.append(dict(label=name,index=index,offset=start,size=size,fields=values,
                         row_sha256=ue.sha(raw)))
    if r.position!=len(r.data): raise ValueError('native_text_table_end_mismatch')
    return dict(schema=schema,counts=package.counts,export_index=export['index'],
                export_sha256=ue.sha(export['data']),rows=rows)
