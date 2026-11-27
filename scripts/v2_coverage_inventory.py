"""Read only retained synthetic-test reports (not credentials or arbitrary logs)."""
import hashlib,json
from pathlib import Path
PREFIXES=('remaining-case-','first-multiturn-','semantic-','dialogue-semantic-','closeout-','g02-','g04-','g05-','guess-confirm-','retain-','flash-1017-safety')
def collect(root):
    paths=[]
    for p in root.iterdir():
        if not p.name.startswith(PREFIXES):continue
        if p.suffix=='.json' and not p.name.endswith('.started.json'):paths.append(p)
        elif p.is_dir() and not any(x in p.name for x in ('frozen','source','preparation')):
            paths.extend(p/name for name in ('result.json','supervisor.json'))
    qa=Path('/home/ubuntu/multica_workspaces/titan-q0u7-aa9ba699e3d3/tita-88-a96590e5792e/workdir')
    paths.extend(qa/name for name in ('g02-actual-review/report.json','g04-remaining-review/report.json','g05-actual-review/report.json','final-nondevice-audit/semantic-check.json','final-nondevice-audit/audit.json'))
    inventory=[];rows=[]
    def visit(value,source,path,pointer='',case=None):
        if isinstance(value,dict):
            source=value.get('source',value.get('source_sha',source));case=value.get('id',value.get('label',case))
            for key in ('actual_complete_ack_texts','actual_ack_texts','new_played_text','synthetic_played'):
                texts=value.get(key)
                if isinstance(texts,list) and all(isinstance(t,str) for t in texts):
                    rows.append(dict(report=str(path),pointer=pointer,source=source,case=case,
                        input=value.get('synthetic_input',value.get('input')),ack_kind=key,texts=texts,
                        state=value.get('game_after',dict(mode=value.get('mode'),roles=value.get('roles'),rules=value.get('synthetic_rules',value.get('rules')))),
                        status=value.get('status'),local_help=value.get('local_help')))
            for key,item in value.items():visit(item,source,path,pointer+'/'+str(key),case)
        elif isinstance(value,list):
            for n,item in enumerate(value):visit(item,source,path,pointer+'/'+str(n),case)
    for p in sorted(set(paths)):
        entry=dict(report=str(p),read='unknown');inventory.append(entry)
        try:
            raw=p.read_bytes()
            if len(raw)>16*1024*1024:entry['read']='too_large';continue
            entry['sha256']=hashlib.sha256(raw).hexdigest();value=json.loads(raw);entry['read']='read'
            visit(value,value.get('source') if isinstance(value,dict) else None,p)
        except PermissionError:entry['read']='permission_denied_not_bypassed'
        except FileNotFoundError:entry['read']='missing'
        except (ValueError,TypeError):entry['read']='invalid_json'
    return dict(scope='retained_synthetic_reports_only_no_claim_all_private_artifacts_read',inventory=inventory,evidence_rows=rows)
if __name__=='__main__':
    result=collect(Path('/home/ubuntu/tech/v2-delivery'))
    Path('docs/testing/v2/finite-coverage/inventory.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(reports=len(result['inventory']),read=sum(x['read']=='read' for x in result['inventory']),rows=len(result['evidence_rows']))))
