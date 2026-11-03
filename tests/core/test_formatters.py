import xml.etree.ElementTree as ET

import pytest

from codepack.core.formatters import PackDocument, PackedFile, available_formats, get_formatter
from codepack.core.formatters.markdown import fence_for


@pytest.fixture
def doc():
    return PackDocument(
        project_name="demo",
        tree="demo/\n└── a.cpp",
        files=[
            PackedFile("a.cpp", "cpp", "int main() {}\n"),
            PackedFile("README.md", "markdown", "```py\nx\n```"),
            PackedFile("weird.xml", "xml", "<a>]]></a> & <b/>"),
        ],
    )


def test_registry():
    assert available_formats() == ["markdown", "xml", "plain"]
    assert get_formatter("md").name == "markdown"
    assert get_formatter("TXT").name == "plain"
    assert get_formatter("xml").extension == ".xml"
    with pytest.raises(ValueError):
        get_formatter("yaml")


def test_fence_for():
    assert fence_for("no fences") == "```"
    assert fence_for("```x```") == "````"
    assert fence_for("`````") == "``````"


def test_markdown(doc):
    out = get_formatter("markdown").render(doc)
    assert out.startswith("# Project: demo\n")
    assert "## Directory Structure\n\n```text\ndemo/\n└── a.cpp\n```" in out
    assert "### `a.cpp`\n\n```cpp\nint main() {}\n```\n" in out
    # inner fence must not close the outer block early
    assert "````markdown\n```py\nx\n```\n````" in out


def test_markdown_preamble_and_no_tree():
    d = PackDocument("p", tree="", files=[PackedFile("x.py", "python", "1")], preamble="  Review this.  ")
    out = get_formatter("markdown").render(d)
    assert "Review this.\n" in out
    assert "Directory Structure" not in out


def test_xml_is_well_formed_and_preserves_content(doc):
    out = get_formatter("xml").render(doc)
    root = ET.fromstring(out)
    assert root.tag == "project" and root.get("name") == "demo"
    assert root.find("directory_structure").text.strip() == "demo/\n└── a.cpp"
    files = root.find("files").findall("file")
    assert [f.get("path") for f in files] == ["a.cpp", "README.md", "weird.xml"]
    assert files[0].get("language") == "cpp"
    assert files[2].text.strip() == "<a>]]></a> & <b/>"


def test_xml_preamble_escaped():
    d = PackDocument("p", files=[], preamble="a < b")
    root = ET.fromstring(get_formatter("xml").render(d))
    assert root.find("instructions").text.strip() == "a < b"


def test_plain(doc):
    out = get_formatter("plain").render(doc)
    assert out.startswith("Project: demo\n")
    assert "Directory Structure\n" in out
    assert "File: a.cpp\n" in out
    assert "int main() {}\n" in out
