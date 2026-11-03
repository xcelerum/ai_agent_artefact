"""Private local subprocess: bounded extraction; stdout is never customer output."""

import json
from pathlib import Path
import re
import resource
import sys
import unicodedata

from pypdf import PdfReader


def extract(path: Path) -> dict:
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CPU, (8, 8))
    if not 0 < path.stat().st_size <= 10 * 1024 * 1024:
        raise ValueError('PDF size limit')
    reader = PdfReader(path, strict=True)
    if reader.is_encrypted or not 1 <= len(reader.pages) <= 20:
        raise ValueError('Unsupported PDF')
    pages, total = [], 0
    for index, page in enumerate(reader.pages, 1):
        contents = page.get_contents()
        if contents is not None and len(contents.get_data()) > 2 * 1024 * 1024:
            raise ValueError('PDF content limit')
        text = page.extract_text(extraction_mode='layout') or ''
        total += len(text)
        if total > 200000:
            raise ValueError('PDF text limit')
        normalized = ''.join(c for c in unicodedata.normalize('NFD', text.casefold())
                             if not unicodedata.combining(c))
        markers = set(re.findall(r'(?:pagina|page)\s+(\d+)\b', normalized))
        printed = int(next(iter(markers))) if len(markers) == 1 else None
        pages.append({'pdf_page': index, 'printed_page': printed, 'text': text})
    return {'pages': pages}


if __name__ == '__main__':
    try:
        print(json.dumps(extract(Path(sys.argv[1])), ensure_ascii=True))
    except Exception:
        # Parser diagnostics go to captured stderr, never a customer-facing exception.
        sys.exit(2)
