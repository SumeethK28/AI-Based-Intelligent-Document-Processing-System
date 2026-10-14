"""Conservative retained-source cleanup; preserve document and audit records."""
from datetime import datetime,timezone
from idp.batch.service import BatchService
from idp.security.auth import AuthService


class GovernanceService:
    def __init__(self,repository): self.repository=repository

    def candidates(self):
        self.repository.require('governance')
        with self.repository._connect() as db:
            rows=db.execute('''SELECT i.id,i.filename,i.retain_until,i.document_id,i.state,i.attempts,c.case_status,
              EXISTS(SELECT 1 FROM review_events e WHERE e.document_id=i.document_id) AS has_events,
              EXISTS(SELECT 1 FROM documents d WHERE json_extract(d.full_result,'$.matched_document_id')=i.document_id) AS dependent
              FROM batch_items i LEFT JOIN review_cases c ON c.document_id=i.document_id
              WHERE i.state IN ('completed','duplicate','review_required','failed')''').fetchall()
        result=[]
        for row in rows:
            item=dict(row)
            try: expired=datetime.fromisoformat(item['retain_until'])<datetime.now(timezone.utc)
            except (ValueError,TypeError): expired=False
            # Linked model originals and audit events are necessary references: never remove their sources.
            eligible=expired and item['document_id'] is None and item['state']=='failed' and item['attempts']>=5 and not item['has_events'] and not item['dependent']
            result.append({**item,'eligible':eligible,'reason':'Expired unlinked source with exhausted retries only' if eligible else 'Preserved: retryable source, active case, processing original, audit reference, dependency or unexpired retention'})
        return result

    def cleanup(self,item_id,*,confirmed=False):
        principal=self.repository.require('governance')
        if confirmed is not True: raise ValueError('Explicit source cleanup confirmation required.')
        with self.repository._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            candidate=next((item for item in self.candidates() if item['id']==item_id),None)
            if not candidate or not candidate['eligible']: raise ValueError('Source must be preserved because it is unexpired or referenced.')
            row=dict(db.execute('SELECT * FROM batch_items WHERE id=?',(item_id,)).fetchone())
            path=BatchService(self.repository).source(row)
            # source() verifies resolved containment, no symlink, size and stored hash. No recursive deletion.
            path.unlink()
            AuthService(self.repository).event('retained_source_cleanup','allowed',str(item_id),principal['id'],db)
        return True
