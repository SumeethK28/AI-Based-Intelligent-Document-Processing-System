"""Prepare a balanced study pack and local timer; never fabricate human observations."""
import argparse,csv,json,hashlib
from pathlib import Path
from reportlab.pdfgen import canvas

HTML='''<!doctype html><html><head><meta charset="utf-8"><title>Document study recording</title>
<style>body{font:16px system-ui;max-width:1100px;margin:30px auto;padding:20px}label{display:block;margin:12px 0}input,select,button{font:inherit;padding:8px}input{min-width:300px}#fields{display:grid;grid-template-columns:1fr 1fr;gap:10px}aside{background:#eef3f7;padding:18px}button{margin:5px}textarea{width:95%;height:80px}</style></head>
<body><h1>Manual versus assisted document study</h1><aside>Research recording only. No payment or legal action. Follow your coordinator's assignment. Ground truth is kept separately. No participants or timing results are prefilled.</aside>
<label>Participant code <input id="participant" placeholder="Assigned anonymous code"></label>
<label>Condition <select id="arm"><option>manual</option><option>assisted</option></select></label>
<label>Assigned case <select id="task"></select></label><a id="source" target="_blank">Open source document</a>
<p id="reference"></p><p>Start when the source is first available. In assisted mode include upload/processing in elapsed time; pause active time only while waiting for AI or during a recorded interruption.</p>
<button id="start">Start task</button><button id="wait">Pause active time: AI wait</button><button id="break">Pause active time: interruption</button><button id="resume">Resume active time</button><p id="status">Not started</p>
<label>Import this case's actual application JSON (assisted only)<input type="file" id="import" accept=".json"></label>
<div id="fields"></div><label>Route <select id="route"><option value="">Choose decision</option><option>Procurement</option><option>Finance</option><option>Expense Processing</option><option>Legal</option><option>Document Review</option><option>Risk Review</option></select></label>
<label>Reason / exceptions checked<textarea id="reason"></textarea></label><label>Workload rating 1–7 <input id="workload" type="number" min="1" max="7"></label>
<button id="finish">Finish and download measured record</button><p>The coordinator scores the record against the separate ground truth. Do not inspect ground truth during a task.</p>
<script>const tasks=TASK_DATA;const $=id=>document.getElementById(id);let begin=null,segment=null,active=0,wait=0,breaks=0,pausedAt=null,pauseKind=null,imported={},events=[];
tasks.forEach(t=>{let o=document.createElement('option');o.value=t.id;o.textContent=t.id+' / '+t.type;$('task').append(o)});
function render(){if(begin)return;let t=tasks.find(x=>x.id===$('task').value);$('source').href=t.source;$('reference').replaceChildren();if(t.reference){let a=document.createElement('a');a.href=t.reference;a.target='_blank';a.textContent='Open reference Purchase Order';$('reference').append(a)}$('fields').replaceChildren();t.fields.forEach(f=>{let l=document.createElement('label');l.textContent=f+' ';let i=document.createElement('input');i.dataset.field=f;l.append(i);$('fields').append(l)});$('import').disabled=$('arm').value!=='assisted'}
$('task').onchange=render;$('arm').onchange=render;render();
function addActive(now){if(segment!==null){active+=now-segment;segment=null}}
function finishPause(now){if(pausedAt!==null){if(pauseKind==='AI wait')wait+=now-pausedAt;else breaks+=now-pausedAt;pausedAt=null;pauseKind=null}}
$('start').onclick=()=>{if(begin||!$('participant').value.trim())return;begin=performance.now();segment=begin;events.push({event:'start',offset_ms:0});$('task').disabled=true;$('arm').disabled=true;$('status').textContent='Active recording'};
function pause(kind){if(begin===null||pausedAt!==null)return;let now=performance.now();addActive(now);pausedAt=now;pauseKind=kind;events.push({event:kind,offset_ms:now-begin});$('status').textContent='Paused: '+kind}
$('wait').onclick=()=>{if($('arm').value==='assisted')pause('AI wait')};$('break').onclick=()=>pause('interruption');$('resume').onclick=()=>{if(begin===null||pausedAt===null)return;let now=performance.now();finishPause(now);segment=now;events.push({event:'resume',offset_ms:now-begin});$('status').textContent='Active recording'};
$('import').onchange=async()=>{if($('arm').value!=='assisted'||begin===null)return;let data=JSON.parse(await $('import').files[0].text());let state=data.state||data.full_result||data;imported=state.extracted_fields||{};document.querySelectorAll('[data-field]').forEach(i=>i.value=imported[i.dataset.field]||'');events.push({event:'import_actual_AI_output',offset_ms:performance.now()-begin})};
$('finish').onclick=()=>{if(begin===null||!$('route').value)return;let now=performance.now();addActive(now);finishPause(now);let fields={};document.querySelectorAll('[data-field]').forEach(i=>fields[i.dataset.field]=i.value);let record={participant_id:$('participant').value.trim(),case_id:$('task').value,arm:$('arm').value,active_seconds:active/1000,elapsed_seconds:(now-begin)/1000,AI_wait_seconds:wait/1000,interruption_seconds:breaks/1000,fields,route:$('route').value,reason:$('reason').value,workload_rating:$('workload').value,corrections_after_import:Object.keys(imported).length?Object.keys(fields).filter(k=>fields[k]!==String(imported[k]||'')).length:null,events,completion_status:'submitted_unscored'};let a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(record,null,2)],{type:'application/json'}));a.download=record.participant_id+'_'+record.case_id+'_'+record.arm+'.json';a.click();URL.revokeObjectURL(a.href);$('status').textContent='Record exported. Close/reopen this page for the next assigned task.';$('finish').disabled=true};
</script></body></html>'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.resolve().relative_to(Path('results').resolve())
    if args.output.exists():raise SystemExit('Choose a new directory.')
    args.output.mkdir(parents=True);(args.output/'sources').mkdir()
    truth=[];tasks=[]
    labels={'po_number':'PO Number','order_date':'Order Date','vendor':'Vendor','buyer':'Buyer',
        'invoice_number':'Invoice Number','issue_date':'Issue Date','seller':'Seller','client':'Client','po_reference':'PO Reference',
        'receipt_number':'Receipt Number','subtotal':'Subtotal','tax':'Tax','total':'Total','payment_method':'Payment Method',
        'contract_title':'Contract Title','party_a':'Party A','party_b':'Party B','effective_date':'Effective Date','expiration_date':'Expiration Date','contract_value':'Contract Value'}
    for group,seller,buyer in [('A','Cedar Study Ltd','Orbit Study Ltd'),('B','Maple Study Ltd','Nova Study Ltd')]:
        cases=[('purchase_order','PURCHASE ORDER',{'po_number':'PO-STUDY-'+group,'order_date':'2026-10-14','vendor':seller,'buyer':buyer,'total':'INR 100.00'},'Procurement'),
            ('invoice','INVOICE',{'invoice_number':'INV-STUDY-'+group,'issue_date':'2026-10-14','seller':seller,'client':buyer,'po_reference':'PO-STUDY-'+group,'total':'INR 110.00'},'Document Review'),
            ('receipt','SALES RECEIPT',{'receipt_number':'R-STUDY-'+group,'seller':seller,'issue_date':'2026-10-14','subtotal':'USD 20.00','tax':'USD 2.00','total':'USD 22.00','payment_method':'Cash'},'Expense Processing'),
            ('contract','Study Services Agreement',{'contract_title':'Study Services Agreement','party_a':seller,'party_b':buyer,'effective_date':'2026-10-14','expiration_date':'2027-10-14','contract_value':'EUR 250.00'},'Legal')]
        for kind,title,fields,route in cases:
            case_id=group+'_'+kind;path=args.output/'sources'/(case_id+'.pdf')
            page=canvas.Canvas(str(path),invariant=1);page.setFont('Helvetica',14)
            lines=[title,'SYNTHETIC STUDY ONLY - NO BUSINESS TRANSACTION',*[labels[k]+': '+v for k,v in fields.items() if k!='contract_title']]
            for index,line in enumerate(lines):page.drawString(40,780-index*38,line)
            page.showPage();page.save()
            truth.append({'id':case_id,'group':group,'type':kind,'fields':fields,'route':route,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                'reason':'Invoice is INR 10.00 above referenced PO' if kind=='invoice' else 'All metadata checks pass; no high-value trigger',
                'provenance':'Synthetic generator, no participants/model predictions'})
            tasks.append({'id':case_id,'type':kind,'fields':list(fields),'source':'sources/'+path.name,
                'reference':'sources/'+group+'_purchase_order.pdf' if kind=='invoice' else None})
    (args.output/'coordinator_ground_truth.json').write_text(json.dumps(truth,indent=2),encoding='utf-8')
    (args.output/'study_timer.html').write_text(HTML.replace('TASK_DATA',json.dumps(tasks)),encoding='utf-8')
    with (args.output/'planned_assignments.csv').open('w',newline='',encoding='utf-8') as stream:
        writer=csv.writer(stream);writer.writerow(['planned_slot','participant_id_unassigned','period','arm','group','task_order'])
        for slot,sequence in enumerate([(('manual','A'),('assisted','B')),(('assisted','B'),('manual','A')),(('manual','B'),('assisted','A')),(('assisted','A'),('manual','B'))],1):
            for period,(arm,group) in enumerate(sequence,1):writer.writerow([slot,'',period,arm,group,'purchase_order;invoice;receipt;contract'])
    with (args.output/'scored_observations_template.csv').open('w',encoding='utf-8') as stream:
        stream.write('participant_id,case_id,arm,order,active_seconds,elapsed_seconds,AI_wait_seconds,interruption_seconds,correct_fields,expected_fields,route_correct,false_approval,corrections,exception_seconds,workload_rating,completion_status\n')
    print('Prepared eight synthetic sources, balanced planned slots, separate coordinator truth and an empty local study recorder. No human observations or savings generated.')


if __name__=='__main__':main()
