"""Metadata-only packet, source mode and CI invocation checks."""
import ast, hashlib, json, re, tarfile
from pathlib import Path, PurePosixPath
def format_proof(source,targets):
    conv=source['scripts/convert.sh'].decode();test=source['scripts/test-convert-outputs.sh'].decode();hermes=source['scripts/build-hermes-plugin.py'].decode()
    headers={}
    for name in ['windsurf','aider']:
        function=re.search(r'(?ms)^accumulate_'+name+r'\(\) \{\n(.*?)^\}',conv).group(1)
        matches=re.findall(r'(?m)^## (\$\{name\})$',function)
        assert matches==['${name}'],('ACTUAL_AGGREGATE_HEADER',name,matches)
        assert 'get_field "name" "$file"' in function
        headers[name]=['## '+row['name']for row in targets.values()]
    spec=ast.literal_eval(re.search(r'(?ms)^SPEC = (\{.*?^\})',test).group(1))
    aggregates={tool:list(pair) for tool,pair in spec.items() if pair[1] in ['accum','json']}
    assert aggregates=={'aider':['CONVENTIONS.md','accum'],'windsurf':['.windsurfrules','accum'],'hermes':['agency-agents-router/data/agents.json','json']},aggregates
    for pattern in ['names.get(l.rstrip()[3:]) if l.startswith("## ") else None','items = items if isinstance(items, list) else items.get("agents", [])','sl = it.get("slug") if isinstance(it, dict) else None']:
        assert pattern in test,('UPSTREAM_LAYER_B_BOUNDARY',pattern)
    tree=ast.parse(hermes);parse=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='parse_agent')
    entry=next(n.value for n in parse.body if isinstance(n,ast.Return) and isinstance(n.value,ast.Dict))
    fields=[ast.literal_eval(k) for k in entry.keys];slug=entry.values[fields.index('slug')]
    assert isinstance(slug,ast.Call) and isinstance(slug.func,ast.Name) and slug.func.id=='slugify' and isinstance(slug.args[0],ast.Name) and slug.args[0].id=='name'
    collect=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='collect_agents')
    assert any(isinstance(n,ast.AnnAssign) and isinstance(n.target,ast.Name) and n.target.id=='agents' and isinstance(n.value,ast.List) and not n.value.elts for n in collect.body)
    assert isinstance(collect.body[-1],ast.Return) and collect.body[-1].value.id=='agents'
    assert 'agents.append(parsed)' in hermes and 'parsed = parse_agent(path, repo_root)' in hermes
    assert 'json.dumps(agents, ensure_ascii=False, indent=2)' in hermes
    assert 'value = value.lower()' in hermes and 'value = re.sub(r"[^a-z0-9]+", "-", value)' in hermes and 'return value.strip("-")' in hermes
    manifest=source['scripts/convert-outputs.sha256'].decode()
    assert len(targets)==3
    for slug,row in targets.items():
        persona=source[row['path']].decode();assert '\nname: '+row['name']+'\n' in persona
        assert re.sub(r'[^a-z0-9]+','-',row['name'].lower()).strip('-')==slug
        assert len([line for line in manifest.splitlines()if line.startswith('agent\t'+slug+'\t')])==1
    return {'headers':headers,'aggregate_tools':aggregates,'json_form':'list','json_entry_keys':fields,'targets':{slug:row['name']for slug,row in targets.items()},'source_sha256':{n:hashlib.sha256(source[n]).hexdigest() for n in ['scripts/convert.sh','scripts/test-convert-outputs.sh','scripts/build-hermes-plugin.py']+[row['path']for row in targets.values()]},'method':'Static AST/literal/header inspection only; no project execution'}

def check(p):
    targets=json.loads((p/'targets.json').read_text())
    sources=json.loads((p/'sources.json').read_text());modes=json.loads((p/'source-modes.json').read_text())
    workflows={};counts={};archive_data={}
    for variant in ['base','candidate']:
        archive_data[variant]={}
        with tarfile.open(p/(variant+'.tar.gz')) as t:
            members=t.getmembers();files=[m for m in members if m.isfile()]
            assert len({m.name for m in members})==len(members),'DUPLICATE_ARCHIVE_MEMBER'
            assert {m.name for m in files}==set(sources[variant]),'ARCHIVE_PREFIX_OR_PATH_SET'
            for m in members:
                name=PurePosixPath(m.name)
                assert not name.is_absolute() and '..' not in name.parts and (m.isfile() or m.isdir()),'ARCHIVE_PATH_OR_KIND'
                if m.isdir():assert m.mode&0o777==0o755
                else:
                    assert m.mode&0o777==int(modes[variant][m.name][-3:],8),('ARCHIVE_MODE',variant,m.name)
                    data=t.extractfile(m).read();archive_data[variant][m.name]=data;assert hashlib.sha256(data).hexdigest()==sources[variant][m.name]
                    if m.name.startswith('.github/workflows/'):workflows.setdefault(variant,{})[m.name]=data.decode()
            counts[variant]=len(files)
    formats=format_proof(archive_data['base'],targets)
    assert formats==json.loads((p/'format-proofs.json').read_text()),'FORMAT_PROOF_DRIFT'
    candidate=archive_data['candidate'];divisions=json.loads(candidate['divisions.json'])['divisions']
    assert isinstance(divisions,(dict,list)) and all(isinstance(d,str) for d in divisions),'DIVISION_SHAPE'
    roster=[]
    for name,data in candidate.items():
        if name.endswith('.md') and name.split('/')[0] in divisions:
            lines=data.decode().splitlines();assert lines,('EMPTY_DIVISION_MARKDOWN',name)
            if lines[0]=='---':roster.append(name)
    manifest_agents=[line for line in candidate['scripts/convert-outputs.sha256'].decode().splitlines() if line.startswith('agent\t')]
    assert roster and len(roster)==len(manifest_agents), 'ROSTER_COUNT'
    assert b'[[ \"$(head -1 \"$1\")\" == \"---\" ]]' in candidate['scripts/lib.sh'],'IS_AGENT_FILE_RULE'
    roster_proof={'derived_sources':len(roster),'upstream_manifest_agent_lines':len(manifest_agents),'empty_division_markdown':0,'converter_rule':'same first-line exact --- as lib.sh is_agent_file'}
    # Read the observer as Python syntax, without importing or executing it.
    tree=ast.parse((p/'observe.py').read_text());checks=[];scripts=[]
    for n in tree.body:
        if isinstance(n,ast.Assign) and any(isinstance(x,ast.Name) and x.id=='checks' for x in n.targets):checks=ast.literal_eval(n.value)
        if isinstance(n,ast.For) and isinstance(n.target,ast.Name) and n.target.id=='script':scripts=ast.literal_eval(n.iter)
    planned={arg:argv for _,argv in checks for arg in argv if arg.startswith('scripts/')}
    planned.update({'scripts/'+n:['bash','scripts/'+n] for n in scripts})
    # These explicit calls are also statically required in the controller source.
    controller=(p/'observe.py').read_text()
    assert "['bash','scripts/test-convert-outputs.sh','--drift=strict']" in controller
    assert "['bash','scripts/test-convert-outputs.sh','--out='+str(out),'--drift=advisory']" in controller
    coverage=[]
    for variant,entries in workflows.items():
        assert len(entries)==6
        for path,text in entries.items():
            lines=text.splitlines();blocks=[]
            for i,line in enumerate(lines):
                match=re.match(r'^(\s*)run:\s*(.*)$',line)
                if not match:continue
                if match[2]=='|':
                    block=[];indent=len(match[1])
                    for v in lines[i+1:]:
                        if v.strip() and len(v)-len(v.lstrip())<=indent:break
                        block.append(v.strip())
                    blocks.append('\n'.join(block))
                else:blocks.append(match[2])
            for block in blocks:
                commands=[]
                for line in block.splitlines():
                    call=re.match(r'^(bash |python3 |\./)(scripts/[\w-]+\.(?:sh|py))(.*)$',line)
                    if not call:continue
                    prefix,name,tail=call.groups();tail=tail.strip()
                    row={'workflow_command':line}
                    if tail=='$CHANGED_FILES':
                        changed={n for n in set(sources['base'])|set(sources['candidate']) if sources['base'].get(n)!=sources['candidate'].get(n)}
                        assert changed=={row['path']for row in targets.values()},'CHANGED_PERSONA_SCOPE'
                        assert name in ['scripts/lint-agents.sh','scripts/check-agent-originality.sh']
                        invocation=['bash',name]+sorted(changed)
                        assert (repr(['bash',name])+'+changed_paths').replace(' ','') in controller.replace(' ',''),'CHANGED_AGENT_ARGV'
                        assert "changed_paths=sorted(row['path']for row in targets.values())" in controller,'CHANGED_PATH_DERIVATION'
                        row.update(state='EXECUTED_CHANGED_PERSONA',executed_argv=invocation)
                    elif name=='scripts/test-convert-outputs.sh':
                        assert tail=="${{ github.event_name == 'pull_request' && '--drift=advisory' || '' }}"
                        row['executed_argv']=[['bash',name,'--out=<generated>','--drift=advisory'],['bash',name,'--drift=strict']]
                        row['state']='ADVISORY_ALL_PRODUCTS_BASELINE_INDEPENDENT_NO_OUT_STRICT_AND_BOTH_NATIVE_MANIFESTS'
                    else:
                        assert not tail,('UNMAPPED_CI_ARGUMENTS',line)
                        expected=[prefix.strip(),name] if prefix!='./' else ['bash',name]
                        assert planned.get(name)==expected,('CI_ARGV_MISMATCH',name,planned.get(name),expected)
                        row.update(state='EXECUTED',executed_argv=expected)
                        if prefix=='./':row['shell_equivalence']='archive executable mode verified; existing #!/usr/bin/env bash is invoked with bash'
                    commands.append(row)
                coverage.append({'variant':variant,'workflow':path,'run_block':block,'project_commands':commands,'metadata_only':not commands})
    extras=['bash scripts/check-agent-originality.sh (documented full-roster audit beyond conditional CI)',
            'python3 scripts/test-hermes-plugin.py (documented unittest.main entrypoint beyond CI)']
    print(json.dumps({'metadata_preflight':'PASS','real_output_format_proof':formats,'roster_preflight':roster_proof,'source_files_modes_verified':counts,'workflow_run_blocks':coverage,'additional_checks_not_claimed_as_CI':extras}))
