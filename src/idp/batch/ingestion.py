"""Strict bounds before OCR: no archive ingestion or client-supplied storage paths."""
import hashlib
import tempfile
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import pymupdf


@dataclass(frozen=True)
class Limits:
    files: int = 50
    file_bytes: int = 20 * 1024 * 1024
    batch_bytes: int = 100 * 1024 * 1024
    pages: int = 10
    batch_pages: int = 100
    pixels: int = 16_000_000
    rendered_pixels: int = 40_000_000


def inspect_file(filename, data, limits=Limits()):
    name = Path(str(filename).replace('\\', '/')).name
    extension = Path(name).suffix.lower()
    if extension not in {'.pdf','.png','.jpg','.jpeg'}:
        raise ValueError('Only PDF, PNG and JPEG documents are supported. ZIP archives are not accepted.')
    if not data or len(data) > limits.file_bytes:
        raise ValueError('Document is empty or exceeds the 20 MB per-file limit.')
    pages = 1
    if extension == '.pdf':
        if not data.startswith(b'%PDF-'):
            raise ValueError('PDF signature does not match the file extension.')
        try:
            with pymupdf.open(stream=data, filetype='pdf') as doc:
                if doc.is_encrypted or doc.is_repaired or not 0 < len(doc) <= limits.pages:
                    raise ValueError('PDF is damaged, encrypted or exceeds the page limit.')
                pages = len(doc)
                pixels = [int(p.rect.width * 2 + 1) * int(p.rect.height * 2 + 1) for p in doc]
                if max(pixels) > limits.pixels or sum(pixels) > limits.rendered_pixels:
                    raise ValueError('PDF page dimensions exceed safe rendering limits.')
        except Exception as error:
            raise ValueError('PDF is damaged, encrypted or exceeds safe document limits.') from error
    else:
        signature = data.startswith(b'\x89PNG\r\n\x1a\n') if extension == '.png' else data.startswith(b'\xff\xd8\xff')
        if not signature:
            raise ValueError('Image signature does not match the file extension.')
        # Header dimensions before allocating a decoded image (Pillow is a Streamlit dependency).
        from PIL import Image
        import io
        try:
            with Image.open(io.BytesIO(data)) as image:
                if image.width * image.height > limits.pixels or getattr(image, 'n_frames', 1) != 1:
                    raise ValueError('Image dimensions exceed safe limits or image is animated.')
                image.verify()
            if cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR) is None:
                raise ValueError('Image could not be decoded.')
        except Exception as error:
            raise ValueError('Image is damaged or exceeds safe dimension limits.') from error
    return {'filename': name[:240], 'file_hash': hashlib.sha256(data).hexdigest(), 'size_bytes':len(data), 'pages':pages, 'extension':extension}


def preview(files, repository, limits=Limits()):
    rows, accepted, seen = [], [], set()
    size = pages = 0
    for index, (name, data) in enumerate(files):
        try:
            if index >= limits.files:
                raise ValueError('A batch accepts at most 50 documents.')
            info = inspect_file(name, data, limits)
            if size + len(data) > limits.batch_bytes or pages + info['pages'] > limits.batch_pages:
                raise ValueError('Batch exceeds the total size or page limit.')
            duplicate = repository.find_by_hash(info['file_hash']) is not None or info['file_hash'] in seen
            size += len(data)
            pages += info['pages']
            seen.add(info['file_hash'])
            rows.append({**info, 'accepted':True, 'duplicate':duplicate, 'message':'Cached if already stored' if duplicate else 'Ready'})
            accepted.append((info, data))
        except ValueError as error:
            rows.append({'filename': Path(str(name).replace('\\','/')).name, 'size_bytes':len(data), 'accepted':False, 'duplicate':False, 'message':str(error)})
    return rows, accepted
