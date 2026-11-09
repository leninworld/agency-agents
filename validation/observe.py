import os,sys,json,subprocess,shutil,time,hashlib,base64
from pathlib import Path
os.environ.update(PYTHONDONTWRITEBYTECODE='1',PATH='/usr/local/bin:/usr/bin:/bin',PYTHONPATH='/deps')
import yaml,tomllib,re,stat
from isolation import manifest,require_target_only,product_pair,fixtures,TARGET
print("ISOLATION_FIXTURES "+json.dumps(fixtures()),flush=True)
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
manifests={}
baseline_strict_exit=None
for tree in ['base','candidate']:
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
 # Cheap syntax/changed-agent checks precede expensive conversion and full suites.
 assert call(tree,'changed-agent lint',['bash','scripts/lint-agents.sh','marketing/marketing-growth-hacker.md'],env)==0
 assert call(tree,'changed-agent originality',['bash','scripts/check-agent-originality.sh','marketing/marketing-growth-hacker.md'],env)==0
 persona=(repo/'marketing/marketing-growth-hacker.md').read_text()
 if tree=='base':assert '**Winner Rate**: 30%' in persona
 else:assert '**Winner Rate**:' not in persona and '**Experiment Rigor**:' in persona and '**Decision Quality**:' in persona
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
 assert inventory==executed,('CHECK_INVENTORY',sorted(inventory-executed),sorted(executed-inventory))
 print('CHECK_INVENTORY '+json.dumps({'tree':tree,'paths':sorted(inventory),'transitive':['scripts/check-hermes-config-rewrite.py']}),flush=True)
 for label,args in checks:

  if call(tree,label,args,env)!=0:all_green=False
 if gen==0 and call(tree,'full product invariants',['bash','scripts/test-convert-outputs.sh','--out='+str(out),'--drift=advisory'],env)!=0:all_green=False
 for rel,h in sources[tree].items():assert hashlib.sha256((repo/rel).read_bytes()).hexdigest()==h,('test altered source',tree,rel)
 if tree=='base':
  baseline_strict_exit=call(tree,'observed baseline strict',['bash','scripts/test-convert-outputs.sh','--drift=strict'],env)
 assert call(tree,'RAM-only native manifest',['bash','scripts/test-convert-outputs.sh','--out='+str(out),'--update'],env)==0
 manifests[tree]=manifest((repo/'scripts/convert-outputs.sha256').read_text())
 for rel,h in sources[tree].items():
  if rel!='scripts/convert-outputs.sha256':assert hashlib.sha256((repo/rel).read_bytes()).hexdigest()==h,('post-native source drift',tree,rel)
changed_native=require_target_only(manifests['base'],manifests['candidate'])
assert products['base'].keys()==products['candidate'].keys(),'PRODUCT_PATH_SET_CHANGED'
names=set();slugs=set()
for division in json.loads(Path('/base/divisions.json').read_text())['divisions']:
 for f in (Path('/base')/division).rglob('*.md'):
  text=f.read_text()
  if not text.startswith('---\n'):continue
  front=yaml.safe_load(text.split('\n---',1)[0][4:]);names.add(front['name'])
# The native manifest's agent keys are the converter's exact slugs.
slugs={n for (kind,n) in manifests['base'] if kind=='agent'}
changed=[n for n in products['base'] if products['base'][n]!=products['candidate'][n]]
assert changed,'NO_GENERATED_CHANGE'
for path in changed:
 product_pair(path,(Path('/tmp/base-products')/path).read_bytes(),(Path('/tmp/candidate-products')/path).read_bytes(),names,slugs)
for tree in ['base','candidate']:
 for rel,h in sources[tree].items():assert hashlib.sha256((Path('/'+tree)/rel).read_bytes()).hexdigest()==h,('immutable input drift',tree,rel)
summary={'all_green':all_green,'commands':len(results),'baseline_strict_exit':baseline_strict_exit,'failures':[{'tree':r['tree'],'label':r['label'],'exit':r['exit']} for r in results if r['exit']!=0 and r['label']!='observed baseline strict'],'native_manifest_changes':changed_native,'changed_products':changed,'product_counts':{k:len(v) for k,v in products.items()},'no_models_or_providers':True,'no_manifest_source_commit':True,'source_files':{k:len(v) for k,v in sources.items()}}
print('V1_SUMMARY '+json.dumps(summary),flush=True)
assert all_green,summary
print('V1_EVIDENCE_COMPLETE',flush=True)
