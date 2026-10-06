"""A file download names any file (2026-10-07).

Run from `api/`:
    python -m pytest tests/costs/test_file_names.py -q
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))


def test_a_file_name_with_polish_letters_can_be_served():
    """Found 2026-10-07: six supplier originals answered 500, because an HTTP
    header is latin-1 and their names carried "Ł"."""
    from app.routers.util import content_disposition

    h = content_disposition("inline", "FS-613 KOŁODZIEJCZYK.pdf")
    h.encode("latin-1")                                     # what Starlette does
    assert h == ("inline; filename=\"FS-613 KOLODZIEJCZYK.pdf\"; "
                 "filename*=UTF-8''FS-613%20KO%C5%81ODZIEJCZYK.pdf")
    assert content_disposition("attachment", 'a"b.pdf') == 'attachment; filename="ab.pdf"'
