from typing import ClassVar, List

import pymupdf

from ai_platform.utilities.input_parsers.base import DocumentParser, ParsedDocument


class PdfDocumentParser(DocumentParser):
    supported_content_types: ClassVar[List[str]] = ["application/pdf"]

    def parse(self, file_bytes: bytes, source_name: str) -> ParsedDocument:
        doc = pymupdf.open(stream=file_bytes, filetype="pdf")
        page_count = len(doc)
        pages = []
        for page in doc:
            text = page.get_text()
            if text.strip():
                pages.append(text)
        doc.close()

        return ParsedDocument(
            source_name=source_name,
            content_type="application/pdf",
            text="\n\n---\n\n".join(pages),
            page_count=page_count,
        )
