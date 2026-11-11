"""Metadata-only packet, source mode and CI invocation checks."""
import ast, hashlib, json, re, tarfile
from pathlib import Path, PurePosixPath
def check(p):
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
    assert "['bash','scripts/test-reasonix.sh']" in controller
    planned['scripts/test-reasonix.sh']=['bash','scripts/test-reasonix.sh']
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
                        # The candidate adds docs/integration only, no persona path changes.
                        changed={n for n in set(sources['base'])|set(sources['candidate']) if sources['base'].get(n)!=sources['candidate'].get(n)}
                        assert not any(n.endswith('.md') and n.split('/')[0] not in ['README.md','integrations'] for n in changed),'CHANGED_PERSONA_PRECONDITION'
                        row['state']='CI_CONDITION_FALSE_NO_CHANGED_PERSONAS'
                    elif name=='scripts/test-convert-outputs.sh':
                        assert tail=="${{ github.event_name == 'pull_request' && '--drift=advisory' || '' }}"
                        row['executed_argv']=[['bash',name,'--out=<generated>','--drift=advisory'],['bash',name,'--drift=strict']]
                        row['state']='ADVISORY_ALL_PRODUCTS_AND_INDEPENDENT_NO_OUT_STRICT'
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
    print(json.dumps({'metadata_preflight':'PASS','roster_preflight':roster_proof,'source_files_modes_verified':counts,'workflow_run_blocks':coverage,'additional_checks_not_claimed_as_CI':extras}))
