from dataclasses import dataclass
import hashlib
import re
from pathlib import Path

CATEGORIES = {"policies", "faqs", "product_guides"}


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Document:
    path: str
    document_id: str
    title: str
    version: str
    category: str
    body: str
    checksum: str


@dataclass(frozen=True)
class Chunk:
    document: Document
    ordinal: int
    section: str
    text: str
    content_hash: str


def load_documents(root: Path):
    root = root.resolve()
    if not root.is_dir():
        raise ValueError(f"Knowledge directory not found: {root}")
    docs, ids = [], set()
    paths = sorted(root.rglob("*.txt"))
    if not paths or len(paths) > 1000:
        raise ValueError("Knowledge directory must contain 1–1000 text documents")
    for path in paths:
        relative = path.relative_to(root)
        if (
            path.is_symlink()
            or not path.resolve().is_relative_to(root)
            or relative.parts[0] not in CATEGORIES
        ):
            raise ValueError(f"Unsupported path or symlink: {relative}")
        if path.stat().st_size > 256_000:
            raise ValueError(f"Document exceeds 256 KB: {relative}")
        raw = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
        header, separator, body = raw.partition("\n\n")
        metadata = dict(line.split(": ", 1) for line in header.splitlines() if ": " in line)
        if (
            not separator
            or not body.strip()
            or any(not metadata.get(k) for k in ["Title", "Document ID", "Language", "Version"])
        ):
            raise ValueError(f"Missing document metadata/body: {relative}")
        if metadata["Language"].lower() != "english":
            raise ValueError(f"Source documents must be English: {relative}")
        if metadata["Document ID"] in ids:
            raise ValueError(f"Duplicate Document ID: {metadata['Document ID']}")
        ids.add(metadata["Document ID"])
        docs.append(
            Document(
                relative.as_posix(),
                metadata["Document ID"],
                metadata["Title"],
                metadata["Version"],
                relative.parts[0],
                body.strip(),
                sha(raw),
            )
        )
    return docs


def chunk_document(doc: Document, max_words=220, overlap_words=32):
    if max_words < 20 or not 0 <= overlap_words < max_words:
        raise ValueError("Invalid chunk or overlap size")
    sections, heading, paragraphs = [], doc.title, []
    for block in re.split(r"\n\s*\n", doc.body):
        block = block.strip()
        if block == doc.title:
            continue
        if "\n" not in block and len(block.split()) <= 16 and not block.endswith((".", "!", ";")):
            if paragraphs:
                sections.append((heading, "\n\n".join(paragraphs)))
                paragraphs = []
            heading = block
        else:
            paragraphs.append(block)
    if paragraphs:
        sections.append((heading, "\n\n".join(paragraphs)))
    chunks = []
    for section, body in sections:
        words = body.split()
        for start in range(0, len(words), max_words - overlap_words):
            text = " ".join(words[start : start + max_words])
            content_hash = sha(f"{doc.title}\n{section}\n{text}")
            chunks.append(Chunk(doc, len(chunks), section, text, content_hash))
            if start + max_words >= len(words):
                break
    if not chunks:
        raise ValueError(f"Document has no indexable content: {doc.path}")
    return chunks
