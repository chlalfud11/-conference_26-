import json,csv,random,sys
sys.path.insert(0,'.');import measure_judge as mj
R={t:[json.loads(l) for l in open(f'logs/bakeoff_tmpl/{t}.jsonl')] for t in ('tmpl_new','tmpl_v2')}
rows=[]
for t,rs in R.items():
    ts=[x for r in rs for x in r['turns']];print(t,'agree',sum(x['decision']==x['expected_decision'] for x in ts),'judge',sum(mj.judge(x['response']) for x in ts),'distinct',len({x['response'] for x in ts}))
    for r in rs:
        for i,x in enumerate(r['turns'],1):rows.append({'model':t,'scenario':r['scenario_id'],'turn':i,'player':x['player'],'response':x['response']})
print('same decisions',sum(a['decision']==b['decision'] for ra,rb in zip(R['tmpl_new'],R['tmpl_v2']) for a,b in zip(ra['turns'],rb['turns'])))
random.Random(9).shuffle(rows);key={}
w=csv.DictWriter(open('labels/template_rating2.csv','w',encoding='utf-8-sig',newline=''),fieldnames=['id','player','response','natural','note']);w.writeheader()
for i,r in enumerate(rows,1):key[f'c{i:03d}']=r;w.writerow({'id':f'c{i:03d}','player':r['player'],'response':r['response'],'natural':'','note':''})
json.dump(key,open('logs/bakeoff_tmpl/sheet_key2.json','w'),ensure_ascii=False,indent=1)
print('SHEET_OK', len(rows))
