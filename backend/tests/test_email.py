import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from email_service import MAGIC_LINK_TEMPLATES


def test_magic_link_templates_exist():
    assert "fr" in MAGIC_LINK_TEMPLATES
    assert "en" in MAGIC_LINK_TEMPLATES
    assert "es" in MAGIC_LINK_TEMPLATES


def test_magic_link_template_has_placeholder():
    for lang in ("fr", "en", "es"):
        assert "{magic_url}" in MAGIC_LINK_TEMPLATES[lang]["body"]
