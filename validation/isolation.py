"""Proven manifest/product isolation, generalized to the three capture personas."""
import hashlib,json
from pathlib import Path
TARGETS={'reality-checker':'Reality Checker','evidence-collector':'Evidence Collector','senior-project-manager':'Senior Project Manager'}
TARGET_ROWS={slug:{'name':name,'path':path}for (slug,name),path in zip(TARGETS.items(),['testing/testing-reality-checker.md','testing/testing-evidence-collector.md','project-management/project-manager-senior.md'])}
def load_targets(data):
    def unique(pairs):
        result={}
        for key,value in pairs:
            assert key not in result,('DUPLICATE_TARGET_METADATA_KEY',key)
            result[key]=value
        return result
    obj=json.loads(data,object_pairs_hook=unique)
    assert obj==TARGET_ROWS,'MISSING_EXTRA_OR_CHANGED_TARGET_METADATA'
    return obj

def manifest(text):
    out={}
    for line in text.splitlines():
        if line.startswith('#') or not line:continue
        k,n,h=line.split('\t');assert k in ['agent','tool','contract'] and len(h)==64
        assert all(c in '0123456789abcdef' for c in h),'MANIFEST_HASH'
        assert (k,n) not in out,'DUPLICATE_MANIFEST_KEY'
        out[k,n]=h
    assert out
    return out

def require_target_only(a,b):
    assert a.keys()==b.keys(),'MANIFEST_KEYS_CHANGED'
    changed={k for k in a if a[k]!=b[k]}
    assert changed=={('agent',slug) for slug in TARGETS},('UNRELATED_OR_MISSING_MANIFEST_DRIFT',sorted(changed))
    return sorted(changed)

def strip_section(data,names):
    lines=data.decode().splitlines(keepends=True);out=[];target=None;counts={name:0 for name in TARGETS.values()}
    for line in lines:
        header=line.rstrip()[3:] if line.startswith('## ') else None
        if header in names:
            target=header if header in counts else None
            if target:counts[target]+=1;out.append('<TARGET_SECTION:'+target+'>\n')
        if target is None:out.append(line)
    assert all(n==1 for n in counts.values()),('AMBIGUOUS_TARGET_SECTIONS',counts)
    return ''.join(out)

def strip_json(data):
    obj=json.loads(data);items=obj if isinstance(obj,list) else obj['agents']
    assert isinstance(items,list),'JSON_AGENT_LIST'
    counts={slug:sum(isinstance(x,dict) and x.get('slug')==slug for x in items)for slug in TARGETS}
    assert all(n==1 for n in counts.values()),('AMBIGUOUS_TARGET_ENTRIES',counts)
    kept=[x for x in items if not (isinstance(x,dict) and x.get('slug') in TARGETS)]
    if isinstance(obj,list):return kept
    obj['agents']=kept;return obj

def product_pair(path,a,b,names,slugs):
    if path in ['windsurf/.windsurfrules','aider/CONVENTIONS.md']:
        assert strip_section(a,names)==strip_section(b,names),'UNRELATED_AGGREGATE_SECTION'
    elif path=='hermes/agency-agents-router/data/agents.json':
        assert strip_json(a)==strip_json(b),'UNRELATED_JSON_ENTRY'
    else:
        parts=Path(path).parts[1:];owners=[]
        for comp in parts[:-1]:
            s=comp[len('agency-'):] if comp.startswith('agency-') else comp
            if s in slugs:owners.append(s)
        stem=Path(parts[-1]).stem
        if stem in slugs:owners.append(stem)
        assert len(set(owners))==1 and set(owners)<=set(TARGETS),('UNRELATED_PRODUCT_FILE',path,owners)

def compare_products(a,b,names,slugs,read_pair=None):
    """The actual entry point: select changes, preserve paths, then normalize owners."""
    assert a.keys()==b.keys(),'PRODUCT_PATH_SET_CHANGED'
    changed=sorted(path for path in a if a[path]!=b[path])
    assert changed,'NO_GENERATED_CHANGE'
    for path in changed:
        left,right=(a[path],b[path]) if read_pair is None else read_pair(path)
        product_pair(path,left,right,names,slugs)
    return changed

def fixtures():
    facts=json.loads(Path('/control/format-proofs.json').read_text())
    assert facts['targets']==TARGETS and facts['json_form']=='list'
    assert facts['headers']=={tool:['## '+name for name in TARGETS.values()]for tool in ['windsurf','aider']}
    successes=negatives=0
    def good(fn,*args):
        nonlocal successes
        print("ISOLATION_FIXTURE_INPUT "+json.dumps({"function":fn.__name__,"expected":"accept","args_repr":repr(args)}),flush=True)
        fn(*args);successes+=1
    def bad(fn,*args):
        nonlocal negatives
        print("ISOLATION_FIXTURE_INPUT "+json.dumps({"function":fn.__name__,"expected":"reject","args_repr":repr(args)}),flush=True)
        try:fn(*args)
        except (AssertionError,ValueError,KeyError):negatives+=1
        else:raise AssertionError('Isolation fixture unexpectedly accepted')
    encoded=json.dumps(TARGET_ROWS)
    good(load_targets,encoded)
    for slug in TARGET_ROWS:
        missing=dict(TARGET_ROWS);missing.pop(slug);bad(load_targets,json.dumps(missing))
    extra=dict(TARGET_ROWS);extra['unsupported']={'name':'Other','path':'other.md'};bad(load_targets,json.dumps(extra))
    bad(load_targets,encoded[:-1]+',"reality-checker":'+json.dumps(TARGET_ROWS['reality-checker'])+'}')
    wrong={slug:dict(row)for slug,row in TARGET_ROWS.items()};wrong['reality-checker']['path']='other.md';bad(load_targets,json.dumps(wrong))
    native={('agent',slug):'a'*64 for slug in TARGETS};native['agent','other']='b'*64;native['tool','windsurf']='c'*64
    candidate={key:('d'*64 if key[0]=='agent' and key[1]in TARGETS else value)for key,value in native.items()}
    good(require_target_only,native,candidate)
    for key in [('agent','other'),('tool','windsurf')]:
        altered=dict(candidate);altered[key]='e'*64;bad(require_target_only,native,altered)
    for slug in TARGETS:
        altered=dict(candidate);altered['agent',slug]=native['agent',slug];bad(require_target_only,native,altered)
    altered=dict(candidate);altered['agent','unsupported']='e'*64;bad(require_target_only,native,altered)
    duplicate='agent\treality-checker\t'+'a'*64+'\n';bad(manifest,duplicate+duplicate)
    good(manifest,duplicate)
    names=set(TARGETS.values())|{'Other'};slugs=set(TARGETS)|{'other'}
    text=('Preamble\n'+''.join('## '+name+'\nold\n'for name in TARGETS.values())+'## Other\npreserved\n').encode()
    entries=[dict({k:'fixture'for k in facts['json_entry_keys']},slug=slug,name=name,body='old')for slug,name in TARGETS.items()]
    entries.append(dict(entries[0],slug='other',name='Other',body='preserved'))
    base={'windsurf/.windsurfrules':text,'aider/CONVENTIONS.md':text,'hermes/agency-agents-router/data/agents.json':json.dumps(entries).encode(),'opencode/agents/other.md':b'preserved'}
    for slug in TARGETS:base['opencode/agents/'+slug+'.md']=b'old'
    # An unchanged target output is valid when this tool doesn't emit edited sections.
    base['openclaw/agents/reality-checker/SOUL.md']=b'unchanged persona section'
    changed={path:data.replace(b'old',b'new')for path,data in base.items()};good(compare_products,base,changed,names,slugs)
    for path in ['windsurf/.windsurfrules','aider/CONVENTIONS.md','hermes/agency-agents-router/data/agents.json','opencode/agents/other.md']:
        altered=dict(changed);altered[path]=altered[path].replace(b'preserved',b'corrupted');bad(compare_products,base,altered,names,slugs)
    altered=dict(changed);altered['unsupported/output.md']=b'x';bad(compare_products,base,altered,names,slugs)
    bad(compare_products,base,dict(base),names,slugs)
    for path in ['windsurf/.windsurfrules','aider/CONVENTIONS.md']:
        altered=dict(changed);altered[path]=altered[path].replace(b'## Reality Checker\n',b'## Not A Target\n');bad(compare_products,base,altered,names,slugs)
        altered=dict(changed);altered[path]+=b'## Reality Checker\nduplicate\n';bad(compare_products,base,altered,names,slugs)
    path='hermes/agency-agents-router/data/agents.json'
    altered=dict(changed);altered[path]=json.dumps(entries+[entries[0]]).encode();bad(compare_products,base,altered,names,slugs)
    altered=dict(changed);altered[path]=json.dumps(entries[1:]).encode();bad(compare_products,base,altered,names,slugs)
    for slug in TARGETS:
        a={'opencode/agents/'+slug+'.md':b'old'};b={k:b'new'for k in a};good(compare_products,a,b,names,slugs)
    # Production supplies known hashes and reads only changed products, preserving RAM.
    hashes=lambda values:{path:hashlib.sha256(data).hexdigest()for path,data in values.items()}
    good(compare_products,hashes(base),hashes(changed),names,slugs,lambda path:(base[path],changed[path]))
    corrupted=dict(changed);corrupted['opencode/agents/other.md']=b'corrupted'
    print('ISOLATION_CALLBACK_INPUT '+json.dumps({'args_repr':repr((base,corrupted))}),flush=True)
    bad(compare_products,hashes(base),hashes(corrupted),names,slugs,lambda path:(base[path],corrupted[path]))
    assert successes==8 and negatives==26,(successes,negatives)
    return {'success_fixtures':successes,'rejected_failure_fixtures':negatives,'actual_entrypoint':'compare_products','real_json_parser':True,'negative_input_retained':'fixture definitions and native stdout retained'}
