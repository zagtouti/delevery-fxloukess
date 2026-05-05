"""
routers/labels.py — v3 NEW
Generate printable PDF labels using reportlab.
Single label: GET /api/labels/{package_id}
Bulk labels:  POST /api/labels/bulk  {package_ids: [...]}
"""
import io
import logging
import qrcode

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from database import get_db
from models import Package, Station
from routers.auth import get_current_user
from utils import ev

logger = logging.getLogger("fxloukess.labels")
router = APIRouter()

# Label dimensions (mm → points: 1mm = 2.835pt)
LABEL_W  = 100 * 2.835   # 100mm wide
LABEL_H  = 70  * 2.835   # 70mm tall


def _make_pdf(packages: list[Package], station: Station | None) -> io.BytesIO:
    """Generate a PDF with one label per page for each package."""
    try:
        from reportlab.lib.pagesizes import landscape
        from reportlab.lib.units    import mm
        from reportlab.pdfgen       import canvas as rl_canvas
        from reportlab.lib          import colors
        from reportlab.graphics.barcode import code128
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="reportlab non installé — pip install reportlab",
        )

    buf  = io.BytesIO()
    page = (100 * mm, 70 * mm)
    c    = rl_canvas.Canvas(buf, pagesize=page)
    W, H = page

    for pkg in packages:
        # ── Background ────────────────────────────────────────────────────────
        c.setFillColor(colors.white)
        c.rect(0, 0, W, H, fill=1, stroke=0)

        # ── Header band ───────────────────────────────────────────────────────
        c.setFillColor(colors.HexColor("#16a34a"))
        c.rect(0, H - 14*mm, W, 14*mm, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 11)
        station_name = station.name if station else "fxloukess"
        c.drawString(3*mm, H - 9*mm, station_name)
        c.setFont("Helvetica", 8)
        c.drawRightString(W - 3*mm, H - 9*mm,
                          f"Fragile" if pkg.is_fragile else "")

        # ── Tracking ID / barcode ─────────────────────────────────────────────
        c.setFillColor(colors.black)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(3*mm, H - 20*mm, pkg.tracking_id)

        try:
            bc = code128.Code128(pkg.tracking_id, barHeight=8*mm, barWidth=0.6)
            bc.drawOn(c, 3*mm, H - 31*mm)
        except Exception:
            pass  # barcode optional

        # ── QR code (tracking URL) ────────────────────────────────────────────
        try:
            qr = qrcode.make(f"/track?t={pkg.tracking_id}")
            qr_buf = io.BytesIO()
            qr.save(qr_buf, format="PNG")
            qr_buf.seek(0)
            from reportlab.lib.utils import ImageReader
            c.drawImage(ImageReader(qr_buf), W - 22*mm, H - 34*mm,
                        width=20*mm, height=20*mm)
        except Exception:
            pass  # QR optional

        # ── Recipient ─────────────────────────────────────────────────────────
        c.setFont("Helvetica-Bold", 9)
        c.drawString(3*mm, H - 37*mm, "Destinataire:")
        c.setFont("Helvetica", 9)
        c.drawString(3*mm, H - 42*mm, pkg.recipient_name)
        c.drawString(3*mm, H - 47*mm, pkg.recipient_phone)

        # ── Address ───────────────────────────────────────────────────────────
        addr = f"{pkg.commune}, {pkg.wilaya}"
        c.setFont("Helvetica", 8)
        c.drawString(3*mm, H - 52*mm, addr)
        # Wrap long address
        full_addr = (pkg.address or "")[:60]
        c.drawString(3*mm, H - 56*mm, full_addr)

        # ── COD box ───────────────────────────────────────────────────────────
        c.setFillColor(colors.HexColor("#fef9c3"))
        c.roundRect(3*mm, 3*mm, 40*mm, 10*mm, 2*mm, fill=1, stroke=0)
        c.setFillColor(colors.HexColor("#a16207"))
        c.setFont("Helvetica-Bold", 8)
        c.drawString(5*mm, 5.5*mm, "COD:")
        c.setFont("Helvetica-Bold", 10)
        c.drawString(16*mm, 5.5*mm, f"{pkg.cod_amount:,.0f} DZD")

        # ── Fragile warning ───────────────────────────────────────────────────
        if pkg.is_fragile:
            c.setFillColor(colors.HexColor("#fef2f2"))
            c.roundRect(W - 28*mm, 3*mm, 25*mm, 10*mm, 2*mm, fill=1, stroke=0)
            c.setFillColor(colors.HexColor("#dc2626"))
            c.setFont("Helvetica-Bold", 8)
            c.drawCentredString(W - 15.5*mm, 5.5*mm, "⚠ FRAGILE")

        # ── Attempts ─────────────────────────────────────────────────────────
        c.setFillColor(colors.gray)
        c.setFont("Helvetica", 6)
        c.drawRightString(W - 3*mm, 2*mm, f"Tentatives: {pkg.attempts}")

        c.showPage()

    c.save()
    buf.seek(0)
    return buf


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/{package_id}")
async def single_label(
    package_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    pkg = db.query(Package).filter(
        Package.id         == package_id,
        Package.station_id == current_user.station_id,
    ).first()
    if not pkg:
        raise HTTPException(status_code=404, detail="Colis introuvable")

    station = db.query(Station).filter(
        Station.id == current_user.station_id
    ).first()
    buf = _make_pdf([pkg], station)
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={
            "Content-Disposition":
                f"inline; filename=label_{pkg.tracking_id}.pdf"
        },
    )


@router.post("/bulk")
async def bulk_labels(
    request_body: dict,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    package_ids = request_body.get("package_ids", [])
    if not package_ids:
        raise HTTPException(status_code=400, detail="package_ids requis")
    if len(package_ids) > 100:
        raise HTTPException(status_code=400, detail="Maximum 100 étiquettes par lot")

    pkgs = db.query(Package).filter(
        Package.id.in_(package_ids),
        Package.station_id == current_user.station_id,
    ).all()
    if not pkgs:
        raise HTTPException(status_code=404, detail="Aucun colis trouvé")

    station = db.query(Station).filter(
        Station.id == current_user.station_id
    ).first()
    buf = _make_pdf(pkgs, station)
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": "inline; filename=labels_bulk.pdf"
        },
    )
