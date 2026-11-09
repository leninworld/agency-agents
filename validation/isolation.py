"""Compare native manifests and generated products at exact agent boundaries."""
import json
from pathlib import Path
TARGET='growth-hacker'
NAME='Growth Hacker'
def manifest(text):
    out={}
    for line in text.splitlines():
        if line.startswith('#') or not line:continue
        k,n,h=line.split('\t');assert k in ['agent','tool','contract'] and len(h)==64
        assert (k,n) not in out;out[k,n]=h
    assert out
    return out

def require_target_only(a,b):
    assert a.keys()==b.keys(),'MANIFEST_KEYS_CHANGED'
    changed={k for k in a if a[k]!=b[k]}
    assert changed=={('agent',TARGET)},('UNRELATED_MANIFEST_DRIFT',sorted(changed))
    return sorted(changed)

def strip_section(data,names):
    # Same exact known source-name boundaries as upstream Layer B, not any ## line.
    lines=data.decode().splitlines(keepends=True);out=[];target=False;count=0
    for line in lines:
        header=line.rstrip()[3:] if line.startswith('## ') else None
        if header in names:
            target=header==NAME
            if target:count+=1;out.append('<GROWTH_HACKER_SECTION>\n')
        if not target:out.append(line)
    assert count==1,('AMBIGUOUS_TARGET_SECTION',count)
    return ''.join(out)

def strip_json(data):
    obj=json.loads(data);items=obj if isinstance(obj,list) else obj['agents']
    assert sum(isinstance(x,dict) and x.get('slug')==TARGET for x in items)==1
    kept=[x for x in items if not (isinstance(x,dict) and x.get('slug')==TARGET)]
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
        assert owners and set(owners)=={TARGET},('UNRELATED_PRODUCT_FILE',path,owners)

def fixtures():
    facts=json.loads(Path('/control/format-proofs.json').read_text())
    assert facts['target_name']==NAME and facts['target_slug']==TARGET and facts['json_form']=='list'
    assert set(facts['headers'].values())=={'## '+NAME}
    a={('agent',TARGET):'a'*64,('agent','other'):'b'*64,('tool','windsurf'):'c'*64}
    b=dict(a);b['agent',TARGET]='d'*64;require_target_only(a,b)
    negatives=0
    for key in [('agent','other'),('tool','windsurf')]:
        bad=dict(b);bad[key]='e'*64
        try:require_target_only(a,bad)
        except AssertionError:negatives+=1
        else:raise AssertionError('Manifest fixture accepted unrelated drift')
    text=('Preamble\n'+facts['headers']['windsurf']+'\nold\n## Other\npreserved\n').encode();good=text.replace(b'old',b'new');bad=good.replace(b'preserved',b'corrupted')
    names={NAME,'Other'}
    for path in ['windsurf/.windsurfrules','aider/CONVENTIONS.md']:
        product_pair(path,text,good,names,{TARGET,'other'})
        try:product_pair(path,text,bad,names,{TARGET,'other'})
        except AssertionError:negatives+=1
        else:raise AssertionError('Aggregate fixture accepted unrelated drift')
    entry={k:'fixture' for k in facts['json_entry_keys']};entry.update(slug=TARGET,body='old',name=NAME)
    other=dict(entry,slug='other',body='preserved',name='Other')
    x=json.dumps([entry,other]).encode()
    y=x.replace(b'old',b'new');bad=y.replace(b'preserved',b'corrupted');path='hermes/agency-agents-router/data/agents.json'
    product_pair(path,x,y,names,{TARGET,'other'})
    try:product_pair(path,x,bad,names,{TARGET,'other'})
    except AssertionError:negatives+=1
    else:raise AssertionError('JSON fixture accepted unrelated drift')
    product_pair('opencode/agents/growth-hacker.md',b'a',b'b',names,{TARGET,'other'})
    try:product_pair('opencode/agents/other.md',b'a',b'b',names,{TARGET,'other'})
    except AssertionError:negatives+=1
    else:raise AssertionError('File fixture accepted unrelated drift')
    assert negatives==6
    return {'success_fixtures':5,'rejected_failure_fixtures':negatives,'real_json_parser':True}
