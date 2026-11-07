import os,json,subprocess,shutil,hashlib,tarfile,re,struct
from pathlib import Path,PurePosixPath
ROOT=Path('/control');cache=Path('/cache');assets=json.loads((ROOT/'native-assets.json').read_text())[os.environ['NATIVE_TAG']]
expected=next(x for x in assets['assets'] if x['name']=='reasonix-linux-amd64.tar.gz')
def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
 return h.hexdigest()
archive=cache/assets['tag']/expected['name'];assert archive.stat().st_size==expected['size'] and 'sha256:'+sha(archive)==expected['digest']
for rel,digest in json.loads((ROOT/'sources.json').read_text())['candidate'].items():assert sha(Path('/candidate')/rel)==digest,rel
vendor=Path('/tmp/vendor');vendor.mkdir();binary=vendor/'reasonix'
with tarfile.open(archive,'r:gz') as package:
 members=package.getmembers();assert len(members)<=2048 and sum(m.size for m in members)<=256*2**20
 for item in members:
  name=PurePosixPath(item.name);assert not name.is_absolute() and '..' not in name.parts and not item.issym() and not item.islnk()
 selected=[m for m in members if PurePosixPath(m.name).name=='reasonix' and m.isfile()]
 assert len(selected)==1 and 0<selected[0].size<=128*2**20
 with package.extractfile(selected[0]) as source,binary.open('xb') as target:shutil.copyfileobj(source,target,1024*1024)
binary.chmod(0o755)
with binary.open('rb') as f:header=f.read(64)
assert header[:4]==b'\x7fELF' and header[4]==2 and header[5]==1 and struct.unpack('<H',header[18:20])[0]==62
print(json.dumps({'official_tag':assets['tag'],'release_source_ref':assets['source_commit'],'archive_sha256':sha(archive),'executable_sha256':sha(binary),'architecture':'Linux AMD64 ELF','archive_extraction':'single regular executable into RAM','license_sha256':sha(ROOT/'VENDOR-LICENSE')}),flush=True)
repo=Path('/tmp/agency');shutil.copytree('/candidate',repo,symlinks=True,ignore=shutil.ignore_patterns('.git'))
home=Path('/tmp/home');home.mkdir();project=Path('/tmp/project');project.mkdir()
env=dict(os.environ,HOME=str(home),REASONIX_HOME='/tmp/reasonix-home',XDG_CONFIG_HOME=str(home/'.config'),TMPDIR='/tmp',PYTHONDONTWRITEBYTECODE='1',GIT_CONFIG_GLOBAL='/dev/null',GIT_CONFIG_NOSYSTEM='1',GOMAXPROCS='1',NO_COLOR='1',TERM='dumb',PATH='/usr/local/bin:/usr/bin:/bin')
records=[]
def call(label,args,cwd=repo):
 if args[0]==str(binary):assert args[1:]==['--version'] or args[1:]==['subagent','list','--dir',str(project)]
 p=subprocess.run(args,cwd=cwd,env=env,capture_output=True,text=True,timeout=45)
 row={'label':label,'args':args,'exit':p.returncode,'stdout':p.stdout,'stderr':p.stderr};records.append(row);print(json.dumps(row),flush=True);assert p.returncode==0,label;return p
call('official CLI version',[str(binary),'--version'])
call('generate all Reasonix profiles',['bash','scripts/convert.sh','--tool','reasonix'])
expected_names={p.parent.name for p in (repo/'integrations/reasonix').glob('reasonix-agency-*/SKILL.md')};assert expected_names and all(n.startswith('reasonix-agency-') for n in expected_names)
call('install global profiles',['bash','scripts/install.sh','--tool','reasonix','--no-interactive'])
call('generate inline coexistence control',['bash','scripts/convert.sh','--tool','antigravity'])
call('install project inline skill',['bash','scripts/install.sh','--tool','antigravity','--no-interactive','--agent','frontend-developer','--path',str(project/'.agents/skills')])
def profiles(label):
 p=call(label,[str(binary),'subagent','list','--dir',str(project)],cwd=project)
 found=[]
 for line in p.stdout.splitlines():
  match=re.match(r'^(reasonix-agency-\S+)\s+\[([^\]]+)\]',line)
  if match:found.append((match.group(1),{x.strip() for x in match.group(2).split(',')}))
 assert len(found)==len(expected_names) and len(dict(found))==len(expected_names) and set(dict(found))==expected_names,(label,len(found))
 for name,attrs in found:
  assert 'manual' in attrs and not any(x.startswith(('model=','effort=')) or x=='read-only' for x in attrs),(name,attrs)
 return dict(found)
global_profiles=profiles('real loader global profiles with project inline coexistence')
assert all('global' in attrs for attrs in global_profiles.values())
call('install project override',['bash','scripts/install.sh','--tool','reasonix','--no-interactive','--agent','frontend-developer','--path',str(project/'.reasonix/skills')])
scoped=profiles('real loader project override without duplicate names')
chosen='reasonix-agency-frontend-developer';assert 'project' in scoped[chosen]
assert all('global' in attrs for name,attrs in scoped.items() if name!=chosen)
assert (project/'.agents/skills/agency-frontend-developer/SKILL.md').is_file()
print(json.dumps({'listed_profiles':len(expected_names),'manual_global_profiles':len(expected_names),'project_override_profiles':1,'other_global_profiles':len(expected_names)-1,'inline_control_preserved':True,'model_calls':0,'provider_calls':0,'subagent_run_or_try_commands':0,'host_execution':False,'network':'none'}),flush=True)
print('OFFICIAL_CLI_LIST_COMPATIBILITY_PASS',flush=True)
