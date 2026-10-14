"""Business UI for persisted jobs; no hidden in-memory background worker."""
import json
import hashlib
import uuid
from pathlib import Path

import streamlit as st

from idp.batch.ingestion import preview, inspect_file
from idp.batch.service import BatchService, TERMINAL


def bulk_page(repository, pipeline_factory, record_table):
    repository.require('batches')
    service = BatchService(repository)
    st.info('Document text is sent to Groq when processing starts. Use authorized files only.')
    st.caption('Up to 50 PDF/PNG/JPEG files, 20 MB each, 100 MB and 100 pages per batch, 10 pages per PDF. ZIP is not supported.')
    with st.expander('Create a batch',expanded=True):
        name = st.text_input('Batch name',value='Document batch',max_chars=200)
        description = st.text_area('Batch description (optional)',max_chars=2000)
        uploads = st.file_uploader('Choose batch documents',type=['pdf','png','jpg','jpeg'],accept_multiple_files=True,key='batch_uploads',max_upload_size=20)
        force = st.checkbox('Force reprocessing for this batch',help='Reruns AI for stored documents and resets their review decisions.')
        if uploads:
            files = [(file.name,file.getvalue()) for file in uploads]
            rows, accepted = preview(files,repository)
            record_table([{key:row.get(key) for key in ('filename','size_bytes','pages','accepted','duplicate','message')} for row in rows])
            st.caption(f'{len(accepted)} accepted · {len(rows)-len(accepted)} rejected. Only accepted files are submitted.')
            confirmed = st.checkbox('I confirm the accepted files may be retained locally and processed with Groq.')
            if st.button('Submit batch',type='primary',disabled=not confirmed or not accepted):
                fingerprint = hashlib.sha256(json.dumps([name,description,force,[(row['file_hash'],row['filename']) for row,_ in accepted]]).encode()).hexdigest()
                if st.session_state.get('batch_fingerprint') != fingerprint:
                    st.session_state['batch_fingerprint'] = fingerprint
                    st.session_state['batch_request_key'] = uuid.uuid4().hex
                token = st.session_state['batch_request_key']
                try:
                    batch_id = service.submit(files,request_key=token,name=name,description=description,force=force)
                    st.session_state['selected_batch'] = batch_id
                    st.success('Batch saved. Start or resume processing below.')
                except Exception:
                    st.error('Batch could not be saved. Check local disk access and retry.')
    st.subheader('Batch history')
    history = service.history()
    if not history:
        st.info('No batches yet. Accepted sources and progress will persist after submission.')
        return
    record_table([{key:job[key] for key in ('id','name','created_at','items','queued','processing','failed')} for job in history])
    jobs = {job['id']:job for job in history}
    selected = st.selectbox('Open batch',list(jobs),format_func=lambda key:jobs[key]['name']+' · '+key[:8],key='selected_batch')
    items = service.items(selected)
    summary = service.summary(selected)
    counts = summary['counts']
    for column,label,value in zip(st.columns(5),('Submitted','Completed','Duplicates','Failures','Needs review'),
            (len(items),counts['completed'],counts['duplicate'],counts['failed'],counts['review_required'])):
        column.metric(label,value)
    terminal = sum(item['state'] in TERMINAL for item in items)
    progress_bar = st.progress(terminal/len(items),text=f'{terminal} of {len(items)} finished')
    status = st.empty()
    current = [item['filename'] for item in items if item['state']=='processing']
    if current:
        status.info('Processing: '+', '.join(current))
    st.caption('Processing is serial. This button runs locally while the application is running. To continue independently of the browser, use the explicit local worker described in docs/milestone3_operations.md. Refresh reads persisted progress; shutdown requires starting the worker again.')
    consent=st.checkbox('I authorize external Groq processing of the OCR text in this batch.',key='batch_ai_consent') if not repository.internal else True
    if st.button('Start / resume batch',disabled=not consent or not (counts['queued'] or counts['processing']),type='primary'):
        def update(item,state):
            status.info(f"{item['filename']} · {state.replace('_',' ')}")
            current_items = service.items(selected)
            done = sum(value['state'] in TERMINAL for value in current_items)
            progress_bar.progress(done/len(items),text=f'{done} of {len(items)} finished')
        try:
            service.run(pipeline_factory,selected,progress=update,ai_consent=consent)
            st.rerun()
        except RuntimeError:
            st.info('Another worker is running. Refresh to monitor its progress.')
        except Exception:
            st.error('Worker interrupted. Saved progress is retained; restart or resume to continue.')
    if st.button('Refresh progress'):
        st.rerun()
    record_table(summary['items'])
    st.caption(f"Measured latest-attempt processing time: {summary['measured_processing_seconds']:.2f} seconds. No throughput estimate is implied.")
    with st.expander('Batch outcomes and financial totals',expanded=True):
        st.json(summary['distributions'])
        record_table(summary['financial_totals'])
        st.caption('Unique invoice values by currency and safety category. Duplicate uploads are counted once. These are extracted values, not paid balances.')
    if repository.internal:
        st.download_button('Download batch JSON',json.dumps(summary,indent=2),file_name=f'batch_{selected}.json',mime='application/json')
        st.download_button('Download batch CSV',service.csv(summary['items']),file_name=f'batch_{selected}.csv',mime='text/csv')
    else:
        from idp.ui.security import download_control
        download_control(repository,'Download batch JSON','batch_json',{'batch_id':selected},'secure_batch_json')
        download_control(repository,'Download batch CSV','batch_csv',{'batch_id':selected},'secure_batch_csv')
    chosen = st.selectbox('Inspect batch item',[item['id'] for item in items],format_func=lambda key:next(item['filename'] for item in items if item['id']==key),key='batch_item')
    item = next(item for item in items if item['id']==chosen)
    if item['safe_error']:
        st.error(item['safe_error'])
    with st.expander('Attempt history'):
        record_table(service.attempts(chosen))
    if item['state']=='failed' and st.button('Retry failed item',disabled=item['attempts']>=5):
        try:
            service.retry(chosen)
            st.rerun()
        except (ValueError,RuntimeError,FileNotFoundError):
            st.error('Retry unavailable: another worker is active, the attempt limit was reached or source is unavailable.')
    if item['document_id']:
        from idp.ui.console import document_detail
        document = repository.get_document(item['document_id'])
        document_detail(repository,document,'batch',run_id=item['run_id'])
    st.caption('Retained sources stay local. Authentication and department scope are enforced; operating-system storage permissions and disk encryption remain necessary. Sources with active cases or audit references cannot be cleaned up.')


def retained_details(repository, document_id, record_table, *, expanded=False):
    repository.access.document(document_id)
    service = BatchService(repository)
    with repository._connect() as db:
        items = [dict(row) for row in db.execute('''SELECT i.*,b.name AS batch_name FROM batch_items i
            JOIN batch_jobs b ON b.id=i.batch_id WHERE i.document_id=? ORDER BY i.id DESC''',(document_id,))]
    with st.expander('Batch membership and retained source',expanded=expanded):
        if not items:
            st.caption('No retained batch source exists for this legacy or single-document upload.')
            return
        keys=('batch_id','batch_name','state','run_id','retain_until') if repository.internal or repository.access.principal()['role']=='Administrator' else ('state','run_id','retain_until')
        record_table([{key:item[key] for key in keys} for item in items])
        item = items[0]
        if not repository.internal:
            from idp.ui.security import download_control
            st.caption('Sensitive source previews are not placed in Streamlit public media storage. Request an authorized, hash-verified source download.')
            download_control(repository,'Download retained source','source',{'item_id':item['id']},f'secure_source_{document_id}')
            return
        try:
            path = service.source(item)
            data = path.read_bytes()
            if inspect_file(item['filename'],data)['file_hash'] != item['file_hash']:
                raise ValueError('Retained source changed')
            if path.suffix.lower() != '.pdf':
                st.image(data,width=550)
            else:
                import pymupdf
                with pymupdf.open(path) as pdf:
                    st.image(pdf[0].get_pixmap(matrix=pymupdf.Matrix(1,1)).tobytes('png'),width=550)
                st.caption('First page of retained PDF. Download the source to inspect all pages.')
            st.download_button('Download retained source',data,file_name=item['filename'],key=f'source_{document_id}')
        except Exception:
            st.warning('Retained source is unavailable or cannot be previewed.')
