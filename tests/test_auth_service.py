from services.auth_service import hashear_password, verificar_password, es_hash


def test_hash_y_verificacion():
    h = hashear_password("clave-segura")
    assert es_hash(h)
    assert "clave-segura" not in h
    assert verificar_password("clave-segura", h)
    assert not verificar_password("otra", h)


def test_mismo_password_distinto_hash():
    assert hashear_password("x") != hashear_password("x")


def test_compatibilidad_texto_plano():
    assert verificar_password("1234", "1234")
    assert not verificar_password("123", "1234")


def test_vacios_y_basura():
    assert not verificar_password("", "1234")
    assert not verificar_password("x", "")
    assert not verificar_password("x", "pbkdf2_sha256$roto")
