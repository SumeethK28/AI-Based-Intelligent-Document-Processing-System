"""Create reproducible synthetic robustness variants; same development families."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import numpy as np
from PIL import Image
import pymupdf
from reportlab.pdfgen import canvas


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    args.output.resolve().relative_to(Path('results').resolve())
    if args.output.exists(): raise SystemExit('Choose a new directory.')
    base=json.loads(args.manifest.read_text()); cases={row['id']:row for row in base['documents']}
    args.output.mkdir(parents=True)
    rows=[]
    def record(name,parent,path,transform,fields=None):
        row=copy.deepcopy(cases[parent]);row.update(id=name,source=path.name,
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),category='transformed_project_synthetic',
            transformation=transform,ground_truth_provenance='generator_before_predictions')
        if fields is not None: row['expected_fields']=fields
        rows.append(row)
    source=args.manifest.parent/cases['pilot_invoice_match']['source']
    with pymupdf.open(source) as doc:
        pix=doc[0].get_pixmap(matrix=pymupdf.Matrix(2,2),alpha=False)
        image=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
    path=args.output/'invoice_rotated_90.png'; image.rotate(90,expand=True).save(path)
    record('invoice_rotated_90','pilot_invoice_match',path,{'rotation_degrees':90,'raster_scale':2})
    path=args.output/'invoice_low_resolution.png'; image.resize((260,360)).save(path)
    record('invoice_low_resolution','pilot_invoice_match',path,{'resolution':[260,360],'raster_scale':2})
    rng=np.random.default_rng(7001)
    noisy=np.clip(np.asarray(image).astype(float)+rng.normal(0,22,np.asarray(image).shape),0,255).astype('uint8')
    path=args.output/'invoice_noise.png';Image.fromarray(noisy).save(path)
    record('invoice_noise','pilot_invoice_match',path,{'noise':'Gaussian','sigma':22,'seed':7001})
    path=args.output/'invoice_two_columns.pdf'
    pdf=canvas.Canvas(str(path),pagesize=(650,900),invariant=1)
    pdf.setFont('Helvetica',16)
    for text,x,y in [('INVOICE',45,840),('Seller:',45,770),('Client:',345,770),
        ('Cedar Supply Ltd',45,730),('Orbit Research Ltd',345,730),
        ('Tax Id: 909-83-7738',45,690),('Tax Id: 997-22-1111',345,690),
        ('Invoice Number: INV-R7001',45,600),('Issue Date: 2026-10-14',45,560),
        ('PO Reference: PO-R7001',45,520),('Total: INR 1180.00',45,480)]:pdf.drawString(x,y,text)
    pdf.showPage();pdf.save()
    record('invoice_two_columns','pilot_invoice_match',path,{'layout':'Seller left, client right; two explicitly role-associated tax IDs'},
           {**cases['pilot_invoice_match']['expected_fields'],'tax_id':'909-83-7738'})
    path=args.output/'receipt_multipage.pdf'
    pdf=canvas.Canvas(str(path),pagesize=(650,900),invariant=1)
    fields=cases['pilot_receipt']['expected_fields']
    for page,lines in enumerate([['SALES RECEIPT','Receipt Number: R-R7001','Merchant: Cedar Store','Transaction Date: 2026-10-14'],
        ['SALES RECEIPT CONTINUED','Subtotal: USD 20.00','Tax: USD 2.00','Total: USD 22.00','Payment Method: Cash']]):
        pdf.setFont('Helvetica',16)
        for index,line in enumerate(lines):pdf.drawString(45,820-index*45,line)
        pdf.showPage()
    pdf.save();record('receipt_multipage','pilot_receipt',path,{'pages':2,'fields_split_across_pages':True});rows[-1]['pages']=2
    path=args.output/'invoice_missing_seller.pdf'
    pdf=canvas.Canvas(str(path),pagesize=(650,900),invariant=1);pdf.setFont('Helvetica',16)
    lines=['INVOICE','Invoice Number: INV-R7003','Issue Date: 2026-10-14','Client: Orbit Research Ltd','Total: INR 1180.00']
    for index,line in enumerate(lines):pdf.drawString(45,820-index*45,line)
    pdf.showPage();pdf.save()
    record('invoice_missing_seller','pilot_invoice_match',path,{'omission':'seller and PO reference'},
        {'invoice_number':'INV-R7003','issue_date':'2026-10-14','client':'Orbit Research Ltd','total':'INR 1180.00'})
    rows[-1].update(expected_status='manual_review',expected_department='Document Review',known_absent_fields=['seller','po_reference'])
    base.update(documents=rows,split='transformed_development_stress_not_final_test',
        limitations='Six transformations of familiar synthetic families, not six independent new industrial sources. Expected values derive from generator before stress predictions.')
    (args.output/'manifest.json').write_text(json.dumps(base,indent=2),encoding='utf-8')
    print('Created six synthetic stress variants with source hashes and transformation parameters. No model calls.')


if __name__=='__main__':main()
