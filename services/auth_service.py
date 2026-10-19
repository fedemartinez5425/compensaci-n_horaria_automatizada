"""
services/auth_service.py
─────────────────────────────────────────────────────────────────
Hash y verificación de contraseñas de acceso (Guardia / RRHH).
No conoce Google Sheets ni Streamlit.

Formato guardado: "pbkdf2_sha256$<iteraciones>$<salt_hex>$<hash_hex>".
Valores sin ese prefijo se tratan como texto plano (compatibilidad con
contraseñas cargadas antes de este cambio): siguen funcionando, y al
volver a cambiarlas desde el Panel RRHH quedan hasheadas.

Cuando la app migre a Azure, esto se reemplaza por login con cuentas
Microsoft (Entra ID) y deja de hacer falta.
"""
import hashlib
import hmac
import secrets

_PREFIJO     = "pbkdf2_sha256"
_ITERACIONES = 200_000


def hashear_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITERACIONES)
    return f"{_PREFIJO}${_ITERACIONES}${salt.hex()}${dk.hex()}"


def es_hash(valor: str) -> bool:
    return str(valor).startswith(_PREFIJO + "$")


def verificar_password(ingresada: str, guardada: str) -> bool:
    """True si `ingresada` coincide con `guardada` (hash o texto plano viejo)."""
    if not ingresada or not guardada:
        return False
    guardada = str(guardada)
    if not es_hash(guardada):
        return hmac.compare_digest(ingresada.encode("utf-8"), guardada.encode("utf-8"))
    try:
        _, iteraciones, salt_hex, hash_hex = guardada.split("$")
        dk = hashlib.pbkdf2_hmac(
            "sha256", ingresada.encode("utf-8"), bytes.fromhex(salt_hex), int(iteraciones)
        )
    except ValueError:
        return False
    return hmac.compare_digest(dk.hex(), hash_hex)
