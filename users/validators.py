"""
Validadores para o app users.
"""

import re
from django.core.exceptions import ValidationError
from django.core.files.images import get_image_dimensions
from django.utils.deconstruct import deconstructible


@deconstructible
class HexColorValidator:
    """Validador para cores hexadecimais."""

    message = "Insira uma cor hexadecimal válida (ex: #FF0000 ou #ff0000)"
    code = "invalid_hex_color"

    def __call__(self, value):
        """Valida se o valor é uma cor hex válida."""
        if not value:  # None, "", etc. são permitidos (campos opcionais)
            return

        # Padrão para cor hex: # seguido de 6 dígitos hexadecimais
        hex_pattern = re.compile(r"^#[0-9A-Fa-f]{6}$")

        if not hex_pattern.match(value):
            raise ValidationError(self.message, code=self.code)


@deconstructible
class ImageFileValidator:
    """Validador para upload de imagens com restrições de tamanho e formato."""

    def __init__(self, max_size_mb=2, allowed_formats=None):
        self.max_size_mb = max_size_mb
        self.max_size_bytes = max_size_mb * 1024 * 1024
        self.allowed_formats = allowed_formats or ["JPEG", "PNG", "GIF", "WEBP"]

    def __call__(self, file):
        """Valida o arquivo de imagem."""
        if not file:
            return

        # Validar tamanho do arquivo
        if file.size > self.max_size_bytes:
            raise ValidationError(
                f"O arquivo é muito grande. Tamanho máximo permitido: {self.max_size_mb}MB"
            )

        # Validar se é uma imagem válida e obter dimensões
        try:
            width, height = get_image_dimensions(file)
        except Exception:
            raise ValidationError("Arquivo não é uma imagem válida.")

        if width is None or height is None:
            raise ValidationError("Não foi possível determinar as dimensões da imagem.")

        # Validar dimensões mínimas (opcional)
        min_width, min_height = 50, 50  # pixels
        if width < min_width or height < min_height:
            raise ValidationError(
                f"Imagem muito pequena. Dimensões mínimas: {min_width}x{min_height} pixels"
            )

        # Validar dimensões máximas (opcional)
        max_width, max_height = 2000, 2000  # pixels
        if width > max_width or height > max_height:
            raise ValidationError(
                f"Imagem muito grande. Dimensões máximas: {max_width}x{max_height} pixels"
            )

        # Reset file pointer para outras validações
        file.seek(0)


def validate_hex_color(value):
    """Função wrapper para validação de cor hex."""
    validator = HexColorValidator()
    validator(value)


def validate_logo_image(file):
    """Função wrapper para validação de imagem de logo."""
    validator = ImageFileValidator(
        max_size_mb=2, allowed_formats=["JPEG", "PNG", "GIF", "WEBP"]
    )
    validator(file)
