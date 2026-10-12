"""Explicit serial local worker: run again after shutdown to resume queued jobs."""
import argparse
from idp.storage.repository import DocumentRepository
from idp.batch.service import BatchService
from idp.pipeline.agentic_pipeline import AgenticDocumentPipeline

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--database', default='data/idp.db')
    parser.add_argument('--batch')
    parser.add_argument('--max-items',type=int,default=50)
    args = parser.parse_args()
    service = BatchService(DocumentRepository(args.database))
    try:
        count = service.run(lambda:AgenticDocumentPipeline(args.database),args.batch,max_items=max(1,min(args.max_items,50)))
        print(f'Finished {count} queued items. Re-run this command to continue remaining work.')
    except RuntimeError:
        print('Another worker is already running. No work was taken over.')
