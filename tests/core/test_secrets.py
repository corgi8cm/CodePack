from pathlib import Path

import pytest

from codepack.core.packer import PackOptions, build_pack
from codepack.core.scanner import scan_project
from codepack.core.scanners.secrets import (
    PLACEHOLDER_RE,
    SecretMasker,
    find_placeholders,
    load_or_create_key,
    unmask,
)

KEY = b"k" * 32

# Fake credentials assembled at runtime so this file never contains a real-looking literal.
AWS = "AKIA" + "IOSFODNN7EXAMPLE"
GOOGLE = "AIza" + "SyA" + "x" * 32
GITHUB = "ghp_" + "a1B2" * 9
OPENAI = "sk-" + "proj-" + "Z" * 30
ANTHROPIC = "sk-ant-" + "api03-" + "q" * 30
JWT = "eyJ" + "hbGciOiJIUzI1NiJ9" + ".eyJ" + "zdWIiOiIxMjM0NTY3ODkwIn0" + "." + "dozjgNryP4J3jVmNHl0w5N"
PEM = "-----BEGIN RSA PRIVATE KEY-----\nMIIEow\nabc\n-----END RSA PRIVATE KEY-----"


@pytest.fixture
def masker():
    return SecretMasker(key=KEY)


@pytest.mark.parametrize(
    "text,kind,value",
    [
        (f"key = '{AWS}'", "aws_access_key", AWS),
        (f"GOOGLE={GOOGLE}", "google_api_key", GOOGLE),
        (f"token: {GITHUB}", "github_token", GITHUB),
        (f"client = OpenAI(api={OPENAI!r})", "openai_key", OPENAI),
        (f"x = {ANTHROPIC}", "anthropic_key", ANTHROPIC),
        (f"Authorization: Bearer {JWT}", "jwt", JWT),
        ("url = 'postgres://admin:s3cr3t!@db.local/app'", "url_password", "s3cr3t!"),
        ('conn = "Server=db;User Id=sa;Password=Hunter2;"', "conn_password", "Hunter2"),
        ('DB_PASSWORD = "hunter22"', "password", "hunter22"),
        ('const char* kApiKey = "abcd1234";', "password", "abcd1234"),
        ('{"client_secret": "zzzz-yyyy"}', "password", "zzzz-yyyy"),
        ("host = 192.168.1.20", "private_ip", "192.168.1.20"),
        ("10.0.0.1", "private_ip", "10.0.0.1"),
        ("172.31.255.1:8080", "private_ip", "172.31.255.1"),
        (PEM, "private_key", PEM),
    ],
)
def test_detects_secrets(masker, text, kind, value):
    matches = masker.find(text)
    assert [(m.kind, m.value) for m in matches] == [(kind, value)]


@pytest.mark.parametrize(
    "text",
    [
        "version = '10.0.19041.1'",
        "ip = 8.8.8.8",
        "172.32.0.1",
        "127.0.0.1",
        "password = get_password()",
        'password = "${DB_PASSWORD}"',
        'token = "<your-token>"',
        'password = "***"',
        "PASSWORD_FIELD = 'pw'",  # too short
        "sk-short",
    ],
)
def test_ignores_non_secrets(masker, text):
    assert masker.find(text) == []


def test_mask_replaces_only_value_and_reports_line(masker):
    text = 'a = 1\nDB_PASSWORD = "hunter22"\n'
    masked, findings = masker.mask(text, "cfg.py")
    assert "hunter22" not in masked
    assert masked.startswith('a = 1\nDB_PASSWORD = "<REDACTED:password:')
    assert len(findings) == 1
    f = findings[0]
    assert (f.rel_path, f.line, f.kind) == ("cfg.py", 2, "password")
    assert "hunter22" not in f.preview


def test_placeholders_are_stable_and_keyed(masker):
    a = masker.placeholder("password", "hunter22")
    assert a == masker.placeholder("password", "hunter22")
    assert a != masker.placeholder("password", "hunter23")
    assert a != SecretMasker(key=b"other" * 8).placeholder("password", "hunter22")
    assert PLACEHOLDER_RE.fullmatch(a)


def test_overlapping_rules_prefer_specific(masker):
    # The value is both an OpenAI-style key and a quoted "api_key" assignment.
    matches = masker.find(f'api_key = "{OPENAI}"')
    assert [m.kind for m in matches] == ["openai_key"]


def test_already_masked_text_is_left_alone(masker):
    masked, _ = masker.mask('password = "hunter22"')
    again, findings = masker.mask(masked)
    assert again == masked and findings == []


def test_unmask_roundtrip(masker):
    original = f'password = "hunter22"\nhost = "10.1.2.3"\nkey = "{AWS}"\n'
    masked, _ = masker.mask(original)
    restored, unresolved = unmask(masked, masker.mapping(original))
    assert restored == original
    assert unresolved == []
    assert len(find_placeholders(masked)) == 3


def test_unmask_reports_unknown(masker):
    text, unresolved = unmask("x <REDACTED:password:deadbeef> y", {})
    assert text == "x <REDACTED:password:deadbeef> y"
    assert unresolved == ["<REDACTED:password:deadbeef>"]


def test_kind_filter():
    m = SecretMasker(key=KEY, kinds=["private_ip"])
    assert m.find('password = "hunter22"') == []
    assert len(m.find("10.0.0.1")) == 1


def test_key_file_created_and_reused(tmp_path: Path):
    path = tmp_path / "sub" / "mask.key"
    k1 = load_or_create_key(path)
    assert len(k1) == 32 and path.exists()
    assert load_or_create_key(path) == k1
    path.write_text("not hex", encoding="ascii")
    assert load_or_create_key(path) != k1  # regenerated


def test_default_key_lives_in_config_dir(isolated_config):
    SecretMasker()
    assert any(isolated_config.rglob("mask.key"))


def test_pack_masks_by_default(make_project):
    root = make_project({"cfg.py": 'DB_PASSWORD = "hunter22"\nHOST = "192.168.0.5"\n', "a.py": "x = 1\n"})
    scan = scan_project(root)
    masker = SecretMasker(key=KEY)
    result = build_pack(scan, ["a.py", "cfg.py"], masker=masker)
    assert "hunter22" not in result.text and "192.168.0.5" not in result.text
    assert [f.kind for f in result.findings] == ["password", "private_ip"]
    plain = build_pack(scan, ["cfg.py"], PackOptions(mask_secrets=False))
    assert "hunter22" in plain.text and plain.findings == []
