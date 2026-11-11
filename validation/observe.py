import os,sys,json,subprocess,shutil,time,hashlib,base64
from pathlib import Path
os.environ.update(PYTHONDONTWRITEBYTECODE='1',PATH='/usr/local/bin:/usr/bin:/bin',PYTHONPATH='/deps')
import yaml,tomllib,re,stat
assert yaml.__version__=='6.0.3' and yaml.__with_libyaml__ is False
assert os.getuid()==0
assert sys.version_info[:2]==(3,11) and os.uname().machine=='x86_64'
assert subprocess.check_output(['node','--version'],text=True).strip()=='v22.23.4'
print(json.dumps({'python':sys.version,'yaml':yaml.__version__,'yaml_module':yaml.__file__,'yaml_libyaml':yaml.__with_libyaml__,'platform':os.uname().machine,'uid':os.getuid()}),flush=True)
# Verify actual mount and direct-exec behavior before any repository process.
mounts=[line.strip() for line in Path('/proc/self/mountinfo').read_text().splitlines() if line.split()[4]=='/tmp']
assert len(mounts)==1 and ' - tmpfs ' in mounts[0] and 'noexec' not in mounts[0].split()[5].split(','),mounts
smoke=Path('/tmp/execution-smoke.sh');smoke.write_text('#!/bin/sh\nprintf RAM_EXEC_OK\\n\n');smoke.chmod(0o755)
smoke_result=subprocess.run([str(smoke)],capture_output=True,text=True,timeout=5)
print(json.dumps({'tmp_mount':mounts,'exec_smoke_exit':smoke_result.returncode,'exec_smoke_stdout':smoke_result.stdout}),flush=True)
assert smoke_result.returncode==0 and 'RAM_EXEC_OK' in smoke_result.stdout
sources=json.loads(Path('/control/sources.json').read_text());source_modes=json.loads(Path('/control/source-modes.json').read_text());results=[];products={};all_green=True
checks=[('tools',['bash','scripts/check-tools.sh']),('divisions',['bash','scripts/check-divisions.sh']),('runbooks',['bash','scripts/check-runbooks.sh']),('hermes-config',['bash','scripts/check-hermes-config-rewrite.sh']),('hermes-plugin',['python3','scripts/check-hermes-plugin.py']),('agent-lint',['bash','scripts/lint-agents.sh']),('originality-audit',['bash','scripts/check-agent-originality.sh']),('hermes-unit',['python3','scripts/test-hermes-plugin.py'])]
for script in ['test-convert-frontmatter.sh','test-convert-slug-collisions.sh','test-convert-symlink-output.sh','test-convert-fence-model.sh','test-agent-selection.sh','test-install-hermes-destination.sh','test-install-conversion-failure.sh','test-install-all-path-collision.sh','test-install-selection-completeness.sh','test-convert-parallel-failure.sh','test-frontmatter-closing.sh','test-lint-fences.sh','test-cli-usage.sh','test-install-continue-after-failure.sh','test-install.sh','test-install-openclaw-registration.sh','test-install-link-ownership.sh','test-install-parallel-logs.sh','test-folded-frontmatter.sh','test-lint-qwen-placeholders.sh']:
 checks.append((script,['bash','scripts/'+script]))
def call(tree,label,args,env):
 started=time.monotonic();p=subprocess.run(args,cwd='/tmp/'+tree,env=env,capture_output=True,text=True,timeout=300)
 row={'tree':tree,'label':label,'args':args,'exit':p.returncode,'seconds':time.monotonic()-started,'stdout':p.stdout,'stderr':p.stderr};results.append(row);print(json.dumps(row),flush=True);return p.returncode
for tree in ['candidate','base']:
 repo=Path('/tmp/'+tree);shutil.copytree('/'+tree,repo,symlinks=True,ignore=shutil.ignore_patterns('.git'))
 home=Path('/tmp/'+tree+'-home');home.mkdir();tmp=Path('/tmp/'+tree+'-tmp');tmp.mkdir()
 env=dict(os.environ,HOME=str(home),TMPDIR=str(tmp),XDG_CONFIG_HOME=str(home/'.config'),REASONIX_HOME='',REASONIX_SKILLS_DIR='')
 for rel,h in sources[tree].items():assert hashlib.sha256((repo/rel).read_bytes()).hexdigest()==h,(tree,rel)
 # A private RAM-only index supplies git ls-files; no history, commit or host Git data.
 env.update(GIT_CONFIG_NOSYSTEM='1',GIT_CONFIG_GLOBAL='/dev/null')
 subprocess.run(['git','-c','init.defaultBranch=validation','init','-q',str(repo)],env=env,check=True,timeout=10)
 subprocess.run(['git','-C',str(repo),'add','--all'],env=env,check=True,timeout=10)
 tracked=subprocess.check_output(['git','-C',str(repo),'ls-files','-z'],env=env,text=True,timeout=10).split('\0')
 assert set(filter(None,tracked))==set(sources[tree]),(tree,'RAM index differs from frozen source inventory')
 print(json.dumps({'tree':tree,'RAM_index_files':len(set(filter(None,tracked))),'commits_created':0}),flush=True)
 assert subprocess.check_output(['git','write-tree'],cwd=repo,env=env,text=True,timeout=10).strip()==json.loads(Path('/control/manifest.json').read_text())['source_trees'][tree],('INITIAL_GIT_TREE',tree)
 for rel,mode in source_modes[tree].items():assert stat.S_IMODE((repo/rel).stat().st_mode)==int(mode[-3:],8),('SOURCE_MODE',rel)
 for file in sorted((repo/'scripts').glob('*.sh')):assert call(tree,'syntax '+file.name,['bash','-n',str(file)],env)==0
 out=Path('/tmp/'+tree+'-products')
 gen=call(tree,'generate all tools',['bash','scripts/convert.sh','--tool','all','--parallel','--jobs','2','--out',str(out)],env)
 if gen!=0:all_green=False
 else:
  products[tree]={str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest() for p in out.rglob('*') if p.is_file()}
  preserved=[]
  for generated in out.rglob('*'):
   if not generated.is_file():continue
   rel=generated.relative_to(out);target_rel='integrations/'+rel.as_posix()
   if target_rel in sources[tree]:
    preserved.append(target_rel)
    continue
   destination=repo/'integrations'/rel;destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(generated,destination)
  print('RAM_COPY_PRESERVED_TRACKED '+json.dumps({'tree':tree,'paths':preserved}),flush=True)
 # Inventory proof includes transitive project entrypoints and candidate-only fixture.
 inventory={str(p.relative_to(repo)) for p in (repo/'scripts').iterdir() if p.is_file() and (p.name.startswith(('test-','check-')) and p.suffix in ['.sh','.py'] or p.name=='lint-agents.sh')}
 executed={arg for _,argv in checks for arg in argv if arg.startswith('scripts/')}
 executed|={'scripts/test-convert-outputs.sh','scripts/check-hermes-config-rewrite.py'}
 if tree=='candidate':executed.add('scripts/test-reasonix.sh')
 assert inventory==executed,('CHECK_INVENTORY',sorted(inventory-executed),sorted(executed-inventory))
 print('CHECK_INVENTORY '+json.dumps({'tree':tree,'paths':sorted(inventory),'transitive':['scripts/check-hermes-config-rewrite.py']}),flush=True)
 for label,args in checks:

  if call(tree,label,args,env)!=0:all_green=False
 if gen==0 and call(tree,'full product invariants',['bash','scripts/test-convert-outputs.sh','--out='+str(out),'--drift=advisory'],env)!=0:all_green=False
 if tree=='candidate':
  profiles=list(out.glob('reasonix/reasonix-agency-*/SKILL.md'));assert profiles
  expected_sources=[p for d in json.loads((repo/'divisions.json').read_text())['divisions'] for p in (repo/d).rglob('*.md') if p.read_text().splitlines()[0]=='---']
  assert len(profiles)==len(expected_sources),('PROFILE_SOURCE_COUNT',len(profiles),len(expected_sources))
  for profile in profiles:
   data=yaml.safe_load(profile.read_text().split('\n---\n',1)[0][4:]);name=data['name']
   assert re.fullmatch(r'reasonix-agency-[a-z0-9-]+',name) and len(name.encode('ascii'))<=64,('ASCII_PROFILE_NAME',name)
  if call(tree,'Reasonix contracts',['bash','scripts/test-reasonix.sh'],env)!=0:all_green=False
 for rel,h in sources[tree].items():assert hashlib.sha256((repo/rel).read_bytes()).hexdigest()==h,('test altered source',tree,rel)
# New fixture must fail against the old public CLI, rather than merely reflecting new implementation.
negdir=Path('/tmp/base/scripts/test-reasonix-negative.sh');negdir.write_bytes(Path('/candidate/scripts/test-reasonix.sh').read_bytes())
neg_home=Path('/tmp/negative-home');neg_home.mkdir();neg_env=dict(os.environ,HOME=str(neg_home),TMPDIR='/tmp',XDG_CONFIG_HOME=str(neg_home/'.config'))
neg=call('base','Reasonix negative control',['bash',str(negdir)],neg_env)
if not (neg==1 and "Unknown tool 'reasonix'" in results[-1]['stderr']):raise RuntimeError('Invalid negative control: expected original unsupported Reasonix exit1; observed '+str(neg))
old_changes=[]
if 'base' in products and 'candidate' in products:
 old_changes=[p for p in sorted(set(products['base'])|set(products['candidate'])) if not p.startswith('reasonix/') and products['base'].get(p)!=products['candidate'].get(p)]
 if old_changes:all_green=False
print(json.dumps({'unchanged_tool_product_differences':old_changes,'base_products':len(products.get('base',{})),'candidate_products':len(products.get('candidate',{}))}),flush=True)
if all_green:
 env=dict(os.environ,HOME='/tmp/candidate-home',TMPDIR='/tmp/candidate-tmp',XDG_CONFIG_HOME='/tmp/candidate-home/.config',REASONIX_HOME='',REASONIX_SKILLS_DIR='',GIT_CONFIG_GLOBAL='/dev/null',GIT_CONFIG_NOSYSTEM='1')
 if call('candidate','intentional manifest regeneration',['bash','scripts/test-convert-outputs.sh','--out=/tmp/candidate-products','--update'],env)!=0:all_green=False
 else:
  final_manifest=Path('/tmp/candidate/scripts/convert-outputs.sha256').read_bytes()
  fresh=Path('/tmp/strict-candidate');shutil.copytree('/candidate',fresh)
  (fresh/'scripts/convert-outputs.sha256').write_bytes(final_manifest)
  Path('/tmp/strict-home').mkdir();Path('/tmp/strict-tmp').mkdir()
  strict_env=dict(os.environ,HOME='/tmp/strict-home',TMPDIR='/tmp/strict-tmp',XDG_CONFIG_HOME='/tmp/strict-home/.config',REASONIX_HOME='',REASONIX_SKILLS_DIR='',GIT_CONFIG_GLOBAL='/dev/null',GIT_CONFIG_NOSYSTEM='1')
  subprocess.run(['git','init','-q'],cwd=fresh,env=strict_env,check=True,timeout=10)
  subprocess.run(['git','add','--all'],cwd=fresh,env=strict_env,check=True,timeout=10)
  assert set(filter(None,subprocess.check_output(['git','ls-files','-z'],cwd=fresh,env=strict_env,text=True,timeout=10).split('\0')))==set(sources['candidate'])
  assert call('strict-candidate','independent strict regeneration',['bash','scripts/test-convert-outputs.sh','--drift=strict'],strict_env)==0
  for rel,h in sources['candidate'].items():
   if rel!='scripts/convert-outputs.sha256':assert hashlib.sha256((fresh/rel).read_bytes()).hexdigest()==h,('strict source drift',rel)
  assert (fresh/'scripts/convert-outputs.sha256').read_bytes()==final_manifest
  assert not subprocess.check_output(['git','diff','--name-only'],cwd=fresh,env=strict_env,text=True,timeout=10).strip(),'STRICT_SOURCE_DRIFT'
  print('CANDIDATE_MANIFEST_BASE64 '+base64.b64encode(final_manifest).decode(),flush=True)
  print('FINAL_GIT_TREE '+subprocess.check_output(['git','write-tree'],cwd=fresh,env=strict_env,text=True,timeout=10).strip(),flush=True)
  print('FINAL_SOURCE_HASHES '+json.dumps({rel:hashlib.sha256((fresh/rel).read_bytes()).hexdigest() for rel in sources['candidate']}),flush=True)
summary={'all_green':all_green,'commands':len(results),'failures':[{'tree':x['tree'],'label':x['label'],'exit':x['exit']} for x in results if x['exit']!=0 and x['label']!='Reasonix negative control'],'negative_expected_exit':neg,'project_imports_on_host':False,'models':False}
print('V1_SUMMARY '+json.dumps(summary),flush=True)
assert all_green,summary
print('V1_EVIDENCE_COMPLETE',flush=True)
