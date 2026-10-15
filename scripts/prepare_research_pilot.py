"""Create a labeled synthetic pilot before predictions; never overwrite datasets."""
import argparse
import hashlib
import json
from pathlib import Path
from reportlab.pdfgen import canvas


CASES=[
    ('pilot_po','purchase_order','PURCHASE ORDER',{'po_number':'PO-R7001','order_date':'2026-10-14','vendor':'Cedar Supply Ltd','buyer':'Orbit Research Ltd','total':'INR 1180.00'},'pending_department_review','Procurement',[]),
    ('pilot_invoice_match','invoice','INVOICE',{'invoice_number':'INV-R7001','issue_date':'2026-10-14','seller':'Cedar Supply Ltd','client':'Orbit Research Ltd','total':'INR 1180.00','po_reference':'PO-R7001'},'pending_department_review','Finance',[]),
    ('pilot_invoice_mismatch','invoice','INVOICE',{'invoice_number':'INV-R7002','issue_date':'2026-10-14','seller':'Cedar Supply Ltd','client':'Orbit Research Ltd','total':'INR 1250.00','po_reference':'PO-R7001'},'manual_review','Document Review',[]),
    ('pilot_receipt','receipt','SALES RECEIPT',{'receipt_number':'R-R7001','seller':'Cedar Store','issue_date':'2026-10-14','subtotal':'USD 20.00','tax':'USD 2.00','total':'USD 22.00','payment_method':'Cash'},'pending_department_review','Expense Processing',['Cash tendered: USD 50.00','Change returned: USD 28.00']),
    ('pilot_contract','contract','Research Services Agreement',{'contract_title':'Research Services Agreement','contract_number':'C-R7001','party_a':'Cedar Services Ltd','party_b':'Orbit Research Ltd','effective_date':'2026-10-14','expiration_date':'2027-10-14','contract_value':'EUR 250.00','governing_law':'India'},'pending_department_review','Legal',[]),
    ('pilot_contract_three_parties','contract','Research Services Agreement',{'contract_title':'Research Services Agreement','contract_number':'C-R7002','party_a':'Cedar Services Ltd','party_b':'Orbit Research Ltd','effective_date':'2026-10-14','expiration_date':'2027-10-14','contract_value':'EUR 250.00','governing_law':'India'},'manual_review','Document Review',['Party C: Vega Research Ltd','All three parties agree to these terms.']),
]

LABELS={'po_number':'PO Number','order_date':'Order Date','vendor':'Vendor','buyer':'Buyer','total':'Total',
        'invoice_number':'Invoice Number','issue_date':'Issue Date','seller':'Seller','client':'Client','po_reference':'PO Reference',
        'receipt_number':'Receipt Number','subtotal':'Subtotal','tax':'Tax','payment_method':'Payment Method',
        'contract_title':'Contract Title','contract_number':'Contract Number','party_a':'Party A','party_b':'Party B',
        'effective_date':'Effective Date','expiration_date':'Expiration Date','contract_value':'Contract Value','governing_law':'Governing Law'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    args.output.resolve().relative_to(Path('results').resolve())
    if args.output.exists(): raise SystemExit('Choose a new dataset directory.')
    args.output.mkdir(parents=True)
    manifest={'permission':'project_generated_synthetic_external_processing_allowed',
        'provenance':'Authored by this project with fictional organizations/identifiers. Not corporate records or real contracts.',
        'split':'development_pilot_not_final_held_out_test','creation':'Fixed generator CASES before model output; no sampled/tuned predictions.',
        'limitations':'Six single-page clean English PDFs; two invoice cases share a template and PO dependency. No independent human adjudication.',
        'documents':[]}
    for name,kind,title,fields,status,department,extras in CASES:
        source=args.output/(name+'.pdf')
        pdf=canvas.Canvas(str(source),pagesize=(650,900),invariant=1)
        pdf.setFont('Helvetica-Bold',19); pdf.drawString(42,848,title)
        pdf.setFont('Helvetica',10);pdf.drawString(42,822,'SYNTHETIC RESEARCH SAMPLE - NOT A BUSINESS TRANSACTION')
        pdf.setFont('Helvetica',14)
        lines=[LABELS[key]+': '+value for key,value in fields.items() if key!='contract_title']+extras
        if kind=='receipt': lines=[line.replace('Seller:','Merchant:').replace('Issue Date:','Transaction Date:') for line in lines]
        for index,line in enumerate(lines): pdf.drawString(42,775-index*37,line)
        pdf.showPage();pdf.save()
        manifest['documents'].append({'id':name,'source':source.name,'sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
            'source_family':'pilot_invoice_pair' if kind=='invoice' else 'pilot_contract_pair' if kind=='contract' else name,
            'type':kind,'category':'project_generated_synthetic','layout':'single_column_labeled_fields',
            'pages':1,'language':'English','expected_fields':fields,'expected_status':status,'expected_department':department,
            'expected_violations':['po_total_mismatch'] if 'mismatch' in name else ['unsupported_parties'] if 'three_parties' in name else [],
            'source_lines':[title,*lines],'ground_truth_provenance':'generator_before_predictions',
            'contract_parties':[fields['party_a'],fields['party_b'],*(['Vega Research Ltd'] if 'three_parties' in name else [])] if kind=='contract' else []})
    (args.output/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print('Created six synthetic PDFs and frozen generator ground truth. No OCR/model calls.')


if __name__=='__main__': main()
