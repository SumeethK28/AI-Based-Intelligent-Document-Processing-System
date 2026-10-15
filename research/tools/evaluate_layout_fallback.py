"""Small paired live-output layout study plus explicitly controlled omission probes.

One real extraction call per synthetic source; hybrid replay uses the same response.
Controlled probes remove the model tax ID to isolate fallback, and are not natural
live-model improvement results. No original database is opened or modified.
"""
import argparse
import copy
from dataclasses import asdict
import hashlib
import json
import platform
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont

from idp.agents.extraction_agent import ExtractionAgent
from idp.pipeline.document_pipeline import DocumentPipeline
from idp.ocr.rapidocr_engine import RapidOCREngine
from research_ablation import live_provider,RecordedProvider,parsed_fields
from research_metrics import equivalent


def outcome(value,expected):
    return 'abstention' if not value else 'correct' if equivalent('tax_id',value,expected) else 'incorrect'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if platform.python_version()!='3.14.6':raise SystemExit('Use Python 3.14.6 through uv.')
    args.output.resolve().relative_to(Path('results').resolve())
    if args.output.exists():raise SystemExit('Use a new directory.')
    args.output.mkdir(parents=True)
    samples=args.output/'samples';samples.mkdir()
    cases=[];font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',32)
    for index,name in enumerate(('seller_left','seller_right','ambiguous_seller_two_ids','stacked_roles','degraded','missing_role_label')):
        image=Image.new('RGB',(1900,1100),'white');draw=ImageDraw.Draw(image)
        draw.text((70,45),'INVOICE - SYNTHETIC RESEARCH SAMPLE',font=font,fill='black')
        draw.text((70,100),'Invoice Number: INV-LAY'+str(index+1),font=font,fill='black')
        draw.text((70,145),'Issue Date: 2026-10-14',font=font,fill='black')
        seller_x,client_x=(1030,70) if name=='seller_right' else (70,1030)
        seller_y,client_y=(215,515) if name=='stacked_roles' else (215,215)
        if name=='stacked_roles':client_x=70
        if name!='missing_role_label':draw.text((seller_x,seller_y),'Seller:',font=font,fill='black')
        draw.text((client_x,client_y),'Client:',font=font,fill='black')
        draw.text((seller_x,seller_y+50),'Cedar Supply Ltd',font=font,fill='black')
        draw.text((client_x,client_y+50),'Orbit Research Ltd',font=font,fill='black')
        draw.text((seller_x,seller_y+100),'Tax Id: 909-83-7738',font=font,fill='black')
        draw.text((client_x,client_y+100),'Tax Id: 997-22-1111',font=font,fill='black')
        if name=='ambiguous_seller_two_ids':draw.text((seller_x,seller_y+150),'Tax Id: 111-22-3333',font=font,fill='black')
        draw.text((70,800),'Total: INR 1180.00',font=font,fill='black')
        if name=='degraded':image=image.resize((380,220))
        path=samples/(name+'.png');image.save(path)
        cases.append({'id':name,'source':path.name,'source_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'seller':'Cedar Supply Ltd','client':'Orbit Research Ltd','seller_tax_id':'909-83-7738',
            'client_tax_id':'997-22-1111','ambiguous_tax_id':name=='ambiguous_seller_two_ids',
            'expected_tax_id':None if name=='ambiguous_seller_two_ids' else '909-83-7738',
            'ground_truth':'Fictional source geometry/values fixed by generator before OCR/model output. Third seller-column tax ID intentionally unresolved.',
            'category':'synthetic_development_layout_probe_not_independent_final_test'})
    (args.output/'ground_truth.json').write_text(json.dumps(cases,indent=2),encoding='utf-8')
    baseline=DocumentPipeline(RapidOCREngine());provider=live_provider();rows=[]
    for case in cases:
        row={'id':case['id'],'completed':False};begin=len(provider.records)
        try:
            result=baseline.process(samples/case['source'])
            fields=asdict(result.extracted_data) if result.extracted_data is not None else {}
            state={'document_type':'invoice','ocr_text':result.ocr.full_text,'ocr_confidence':result.ocr.average_confidence,
                'baseline_fields':fields,'baseline_document_type':result.classification.document_class.value,'agent_history':[],'errors':[]}
            (args.output/(case['id']+'_ocr.json')).write_text(json.dumps(asdict(result.ocr),indent=2),encoding='utf-8')
            ExtractionAgent(provider).run(state)
            raw=provider.parsed['AIExtractionResult']
            replay=RecordedProvider({'document_type':'invoice','confidence':1},raw)
            hybrid=ExtractionAgent(replay).run(state)
            b=parsed_fields(raw).get('tax_id');c=hybrid['extracted_fields'].get('tax_id')
            row.update(raw_model=raw,baseline_fields=fields,hybrid=hybrid,
                llm_only_tax_id=b,hybrid_tax_id=c,
                llm_outcome=outcome(b,case['expected_tax_id']),hybrid_outcome=outcome(c,case['expected_tax_id']),
                natural_correct_recovery=not equivalent('tax_id',b,case['expected_tax_id']) and equivalent('tax_id',c,case['expected_tax_id']),
                natural_incorrect_recovery=not b and bool(c) and not equivalent('tax_id',c,case['expected_tax_id']))
            omitted=copy.deepcopy(raw);omitted['tax_id']=None;omitted.get('field_evidence',{}).pop('tax_id',None)
            controlled=ExtractionAgent(RecordedProvider({'document_type':'invoice','confidence':1},omitted)).run(state)
            row['controlled_model_tax_id_omission']={'provider':'recorded live response with experimentally removed tax ID; simulated intervention',
                'tax_id':controlled['extracted_fields'].get('tax_id'),'outcome':outcome(controlled['extracted_fields'].get('tax_id'),case['expected_tax_id']),
                'fallback_used':controlled['fallback_used']}
            invalid=copy.deepcopy(state);invalid['baseline_fields']['seller_tax_id_evidence']='Fabricated evidence absent from OCR'
            rejected=ExtractionAgent(RecordedProvider({'document_type':'invoice','confidence':1},omitted)).run(invalid)
            row['controlled_missing_evidence_abstains']=not rejected['extracted_fields'].get('tax_id')
            conflict=copy.deepcopy(omitted);conflict['seller']='Conflicting seller absent from OCR'
            rejected=ExtractionAgent(RecordedProvider({'document_type':'invoice','confidence':1},conflict)).run(state)
            row['controlled_conflicting_seller_abstains']=not rejected['extracted_fields'].get('tax_id')
            row['completed']=True
        except Exception as error:row['error_type']=type(error).__name__
        row['live_response_records']=provider.records[begin:];rows.append(row)
        (args.output/'predictions.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
        print(json.dumps({'case':case['id'],'completed':row['completed'],'llm':row.get('llm_outcome'),'hybrid':row.get('hybrid_outcome'),'controlled':row.get('controlled_model_tax_id_omission',{}).get('outcome')}),flush=True)
        if not row['completed']:break
    complete=[row for row in rows if row['completed']]
    report={'python':platform.python_version(),'model':provider.model,'type_given':'invoice (classification not evaluated)',
        'source_count':len(cases),'attempted':len(rows),'completed':len(complete),
        'natural_correct_recoveries':sum(row['natural_correct_recovery'] for row in complete),
        'natural_incorrect_recoveries':sum(row['natural_incorrect_recovery'] for row in complete),
        'natural_hybrid_abstentions':sum(row['hybrid_outcome']=='abstention' for row in complete),
        'controlled_correct_recoveries':sum(row['controlled_model_tax_id_omission']['outcome']=='correct' for row in complete),
        'controlled_incorrect_recoveries':sum(row['controlled_model_tax_id_omission']['outcome']=='incorrect' for row in complete),
        'controlled_abstentions':sum(row['controlled_model_tax_id_omission']['outcome']=='abstention' for row in complete),
        'missing_evidence_abstentions':sum(row['controlled_missing_evidence_abstains'] for row in complete),
        'conflicting_seller_abstentions':sum(row['controlled_conflicting_seller_abstains'] for row in complete),
        'limitations':'Six correlated synthetic invoice probes, one live extraction each, type supplied. Controlled omissions/conflicts test fallback causally but do not demonstrate natural model improvement. No held-out industrial benefit claim. Ambiguous two-tax-ID seller block requires abstention.'}
    (args.output/'metrics.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
