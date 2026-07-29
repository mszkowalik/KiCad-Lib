"""Decide `flashable` from the bytes already in storage."""
from app.db import SessionLocal
from app import models as M
from app.services import storage
from app.routers.flasher import _looks_flashable

db = SessionLocal()
for a in db.query(M.FirmwareAsset).order_by(M.FirmwareAsset.id):
    data = storage.get_bytes(a.minio_key)
    ok = bool(data) and _looks_flashable(data, a.kind)
    a.flashable = ok
    print(f"  asset {a.id:<3} {a.filename[:42]:42} {len(data) if data else 0:>9} B -> "
          f"{'flashable' if ok else 'NOT FLASHABLE'}")
db.commit()
db.close()
