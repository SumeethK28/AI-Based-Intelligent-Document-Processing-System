"""Explicit serial local worker: run again after shutdown to resume queued jobs."""
from idp.security import INTERNAL
import argparse
import os
from dotenv import load_dotenv
from idp.storage.repository import DocumentRepository
from idp.batch.service import BatchService
from idp.pipeline.agentic_pipeline import AgenticDocumentPipeline

if __name__ == '__main__':
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument('--database', default=os.getenv('IDP_DATABASE_PATH','data/idp.db'))
    parser.add_argument('--batch')
    parser.add_argument('--max-items',type=int,default=50)
    args = parser.parse_args()
    service = BatchService(DocumentRepository(args.database, _capability=INTERNAL))
    try:
        count = service.run(lambda:AgenticDocumentPipeline(args.database, _capability=INTERNAL),args.batch,max_items=max(1,min(args.max_items,50)))
        print(f'Finished {count} queued items. Re-run this command to continue remaining work.')
    except RuntimeError:
        print('Another worker is already running. No work was taken over.')
