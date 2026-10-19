"""QR code generator service for UPI payments."""

import io
from pathlib import Path
from typing import Optional
import qrcode
from qrcode.image.pil import PilImage
from bot.config import config
from bot.utils.logger import logger


class QRService:
    @staticmethod
    def generate_upi_qr(
        amount: Optional[float] = None,
        save_path: Optional[Path] = None
    ) -> io.BytesIO:
        """
        Generate a standard NPCI UPI QR code.
        URL format: upi://pay?pa={upi_id}&pn={payee_name}&cu=INR(&am={amount})
        """
        upi_id = config.UPI_ID
        payee_name = config.UPI_PAYEE_NAME.replace(" ", "%20")
        
        upi_uri = f"upi://pay?pa={upi_id}&pn={payee_name}&cu=INR"
        if amount and amount > 0:
            upi_uri += f"&am={amount:.2f}"

        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=10,
            border=3,
        )
        qr.add_data(upi_uri)
        qr.make(fit=True)

        img: PilImage = qr.make_image(fill_color="black", back_color="white")

        output = io.BytesIO()
        img.save(output, format="PNG")
        output.seek(0)

        if save_path:
            try:
                save_path.parent.mkdir(parents=True, exist_ok=True)
                img.save(save_path, format="PNG")
            except Exception as e:
                logger.error(f"Failed to save QR code to {save_path}: {e}")

        return output

    @staticmethod
    def get_static_qr_path() -> Path:
        """Get or generate the default static UPI QR code image."""
        qr_file = config.DATABASE_PATH.parent / "qr" / "default_upi_qr.png"
        if not qr_file.exists():
            QRService.generate_upi_qr(save_path=qr_file)
        return qr_file
