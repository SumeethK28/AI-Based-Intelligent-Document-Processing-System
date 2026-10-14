"""Input minimization and conservative warning signals; not a prompt-injection classifier."""
import json
import re


def provider_text(text,*,classification=False):
    if len(text)>200000:
        raise ValueError('OCR exceeds the supported external-processing text bound.')
    if classification:
        text=re.sub(r'\b[A-Z]{2}\d{2}[A-Z0-9 ]{10,30}\b','[financial identifier omitted]',text)
        text=re.sub(r'(?im)(tax\s*(?:id|number)\s*[:#]?\s*)[A-Z0-9-]{6,}',r'\1[identifier omitted]',text)
        # Do not silently truncate a potentially different document section.
    return json.dumps({'untrusted_document_text':text},ensure_ascii=False)


def injection_signal(text):
    return bool(re.search(r'ignore\s+(?:all\s+)?(?:previous|system|above)\s+instructions|(?:system|assistant)\s*:\s*(?:approve|ignore)|reveal\s+(?:the\s+)?(?:api\s*key|secret)|override\s+(?:validation|routing|policy)',text,re.I))
