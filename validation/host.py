"""One sealed, offline hosted Docker proof; no contribution execution on Mac."""
from pathlib import Path, PurePosixPath
import base64, hashlib, json, os, shutil, subprocess, sys, tarfile, time, urllib.request
sys.dont_write_bytecode=True
P=Path(__file__).resolve().parent
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def verify():
    m=json.loads((P/'manifest.json').read_text())
    actual={str(f.relative_to(P)) for f in P.rglob('*') if f.is_file()}
    assert actual==set(m['files'])|{'manifest.json'},'PAYLOAD_SCOPE'
    for n,h in m['files'].items(): assert sha(P/n)==h,('PAYLOAD_HASH',n)
    assert (P/'workflow.yml').read_bytes()==(P.parent/'.github/workflows/agency-capture-evidence-1275-i1.yml').read_bytes(),'WORKFLOW_DRIFT'
    tree=set(subprocess.check_output(['git','ls-tree','-r','--name-only','HEAD'],text=True).splitlines())
    assert tree=={'validation/'+n for n in m['files']}|{'validation/manifest.json','.github/workflows/agency-capture-evidence-1275-i1.yml'},'TREE_SCOPE'
    header=subprocess.check_output(['git','cat-file','-p','HEAD'],text=True).split('\n\n',1)[0]
    assert not any(l.startswith('parent ') for l in header.splitlines()),'PARENTLESS'
    from packet_check import check
    check(P)
    return m
if sys.argv[1:]==['--verify-only']:
    m=verify();print(json.dumps({'state':'METADATA_ONLY_EXACT_PACKET','files':len(m['files'])}));sys.exit(0)
assert os.environ.get('RUNNER_ENVIRONMENT')=='github-hosted'
assert os.environ.get('GITHUB_REPOSITORY')=='leninworld/agency-agents'
assert os.environ.get('GITHUB_RUN_ATTEMPT')=='1'
origin=int(os.environ['PACKET_ORIGIN']);end=origin+1500
W=Path(os.environ['RUNNER_TEMP']).resolve()/'agency-capture-evidence-1275-i1';assert not W.exists();W.mkdir()
E=W/'evidence';E.mkdir();record={'state':'INCOMPLETE','origin':origin,'containers':[]};owned=[]
def run(label,args,cap=120):
    remaining=min(cap,end-time.time()-90);assert remaining>0,'COMMON_DEADLINE'
    with (E/(label+'.stdout')).open('xb') as out,(E/(label+'.stderr')).open('xb') as err:
        p=subprocess.run(list(map(str,args)),stdout=out,stderr=err,timeout=remaining)
    assert p.returncode==0,(label,p.returncode)
def unpack(archive,root):
    assert not root.exists();root.mkdir()
    with tarfile.open(archive) as t:
        members=t.getmembers();assert len(members)<=4096 and sum(x.size for x in members)<=32*2**20,'SOURCE_SIZE'
        for item in members:
            n=PurePosixPath(item.name)
            assert not n.is_absolute() and '..' not in n.parts and (item.isfile() or item.isdir()),'SOURCE_PATH_OR_KIND'
        for item in members:
            f=root/item.name
            if item.isdir():f.mkdir(parents=True,exist_ok=True)
            else:
                f.parent.mkdir(parents=True,exist_ok=True)
                with f.open('xb') as out:shutil.copyfileobj(t.extractfile(item),out)
                f.chmod(item.mode&0o777)
def fingerprints(root):return {str(f.relative_to(root)):sha(f) for f in root.rglob('*') if f.is_file()}
def inspect(name):return json.loads(subprocess.check_output(['docker','inspect',name],text=True,timeout=10))[0]
def lane(label,script,tag=None):
    name=f'agency-capture-evidence-1275-i1-{os.environ["GITHUB_RUN_ID"]}-{label}'
    missing=subprocess.run(['docker','inspect',name],capture_output=True,text=True,timeout=10)
    assert missing.returncode and 'No such object' in missing.stderr,'CONTAINER_COLLISION'
    # Record ownership before creation so a timed-out create can be recovered by name.
    owned.append(name)
    args=['docker','create','--name',name,'--label','controlplane.run='+os.environ['GITHUB_RUN_ID'],
          '--platform','linux/amd64','--network','none','--read-only','--cap-drop','ALL',
          '--security-opt','no-new-privileges','--memory','2g','--memory-swap','2g',
          '--cpus','2','--pids-limit','256','--log-driver','none',
          '--tmpfs','/tmp:rw,nosuid,nodev,exec,size=1g',
          '--env','PYTHONDONTWRITEBYTECODE=1','--env','PYTHONPATH=/deps']
    if tag:args+=['--env','NATIVE_TAG='+tag]
    for src,dst in [(P,'/control'),(W/'base','/base'),(W/'candidate','/candidate'),
                    (W/'deps','/deps'),(W/'cache','/cache')]:
        args+=['--mount',f'type=bind,src={src},dst={dst},readonly']
    args+=['--entrypoint','/usr/bin/python3',M['image'],'-B','/control/'+script]
    run(label+'-create',args,30)
    obj=inspect(name)
    assert obj['Config']['Labels']['controlplane.run']==os.environ['GITHUB_RUN_ID']
    h=obj['HostConfig'];assert h['ReadonlyRootfs'] and h['NetworkMode']=='none'
    assert h['Memory']==h['MemorySwap']==2*2**30 and h['PidsLimit']==256 and h['NanoCpus']==2*10**9
    assert {x['Destination']:x['RW'] for x in obj['Mounts']}=={x:False for x in ['/control','/base','/candidate','/deps','/cache']}
    proc=None
    try:
        with (E/(label+'.stdout')).open('xb') as out,(E/(label+'.stderr')).open('xb') as err:
            proc=subprocess.Popen(['docker','start','-a',name],stdout=out,stderr=err)
            while proc.poll() is None:
                assert time.time()<end-90,'COMMON_DEADLINE'
                assert shutil.disk_usage(W).free>=2*2**30,'DISK_FLOOR'
                assert sum(f.stat().st_size for f in E.rglob('*') if f.is_file())<=32*2**20,'LOG_BOUND'
                with (E/'docker-samples.jsonl').open('a') as sample:
                    sample.write(json.dumps({'label':label,'at':time.time(),'stats':subprocess.check_output(['docker','stats','--no-stream','--format','{{json .}}',name],text=True,timeout=10).strip()})+'\n')
                time.sleep(2)
            assert proc.returncode==0,(label,proc.returncode)
        state=inspect(name)['State'];assert not state['Running'] and state['ExitCode']==0 and not state['OOMKilled'],state
        record['containers'].append({'label':label,'name':name,'state':state})
    finally:
        if proc is not None and proc.poll() is None:
            subprocess.run(['docker','stop','--time','5',name],capture_output=True,timeout=15,check=True)
            proc.wait(timeout=15)
try:
    M=verify();assert M['state']=='SEALED_FOR_ONE_RUN' and M['validation_attempt']==1 and M['max_validation_attempts']==2
    assert M['candidate_contains_unapplied_proposal'] is False,'UNAPPLIED_SOURCE_DELTA_NOT_YET_AUTHORIZED'
    assert os.environ['GITHUB_REF']==M['ref'] and end-time.time()>=900,'INSUFFICIENT_ORIGINAL_TIME'
    mem={l.split(':')[0]:int(l.split()[1])*1024 for l in Path('/proc/meminfo').read_text().splitlines()}
    assert mem['MemAvailable']>=4*2**30 and len(os.sched_getaffinity(0))>=2,'HOST_CAPACITY'
    assert shutil.disk_usage(W).free>=6*2**30,'INITIAL_DISK'
    record['admission']={'memory':mem,'free_disk':shutil.disk_usage(W).free,'cpus':sorted(os.sched_getaffinity(0))}
    inputs=json.loads((P/'sources.json').read_text())
    for variant in ['base','candidate']:
        unpack(P/(variant+'.tar.gz'),W/variant)
        assert fingerprints(W/variant)==inputs[variant],('SOURCE_FINGERPRINT',variant)
    unpack(P/'yaml.tar.gz',W/'deps')
    assert fingerprints(W/'deps')==json.loads((P/'yaml-fingerprints.json').read_text()),'YAML_CACHE'
    (W/'cache').mkdir()
    run('image',['docker','pull','--platform','linux/amd64',M['image']],180)
    image=json.loads(subprocess.check_output(['docker','image','inspect',M['image']],text=True,timeout=15))[0]
    assert image['Os']=='linux' and image['Architecture']=='amd64','IMAGE_PLATFORM'
    # Required interpreter/parser/toolchain check happens inside the offline observer.
    lane('full','observe.py')
    full=(E/'full.stdout').read_text()
    assert 'V1_EVIDENCE_COMPLETE' in full
    summaries=[json.loads(line.split(' ',1)[1]) for line in full.splitlines() if line.startswith('V1_SUMMARY ')]
    assert len(summaries)==1 and summaries[0]['all_green'] and summaries[0]['native_manifest_changes']==[['agent',slug]for slug in sorted(M['targets'])],'FULL_SUMMARY'
    (E/'summary.json').write_text(json.dumps(summaries[0],indent=2)+'\n')
    for variant in ['base','candidate']:assert fingerprints(W/variant)==inputs[variant],'INPUT_DRIFT'
    record['state']='COMPLETE'
except BaseException as exc:record['error']=repr(exc);raise
finally:
    for name in owned:
        try:
            query=subprocess.run(['docker','inspect',name],capture_output=True,text=True,timeout=10)
            if query.returncode:
                assert 'No such object' in query.stderr;continue
            obj=json.loads(query.stdout)[0]
            assert obj['Config']['Labels']['controlplane.run']==os.environ['GITHUB_RUN_ID'],'RECOVERY_OWNERSHIP'
            if obj['State']['Running']:subprocess.run(['docker','stop','--time','5',name],capture_output=True,check=True,timeout=15)
            state=inspect(name)['State']
            record.setdefault('terminal_states',[]).append({'name':name,'state':state})
            if state['Running'] or state['OOMKilled']:record['state']='INCOMPLETE'
        except BaseException as exc:record.setdefault('recovery_errors',[]).append(repr(exc));record['state']='INCOMPLETE'
    record['elapsed_seconds']=time.time()-origin
    (E/'host.json').write_text(json.dumps(record,indent=2)+'\n')
assert record['state']=='COMPLETE','INCOMPLETE_PROOF'
