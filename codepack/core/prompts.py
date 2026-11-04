"""Question templates to paste into the AI chat after the packed project.

Built-in templates ship with CodePack; users can edit them or add their own.
User templates live in ``user_config_dir()/prompts.json``; one with the same
name as a built-in overrides it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from codepack.core.apply.formats import DELETE_MARK, FILE_END, FILE_START
from codepack.core.paths import user_config_dir

SCHEMA_VERSION = 1
PROMPTS_FILENAME = "prompts.json"

TemplateSource = Literal["builtin", "user", "override"]

_FILE_FORMAT = (
    "請用「完整檔案格式」回答：每個要新增或修改的檔案，都用下面的格式寫出整份內容，不要用「…」或「其餘不變」省略:\n"
    "\n"
    f"{FILE_START.format(path='相對路徑')}\n"
    "(檔案完整內容)\n"
    f"{FILE_END}\n"
    "\n"
    "要刪除檔案就單獨寫一行:\n"
    f"{DELETE_MARK.format(path='相對路徑')}\n"
    "\n"
    "路徑請用上面文件中的相對路徑;<REDACTED:...> 佔位符請保持原樣。"
)

_DIFF_FORMAT = (
    "請用 unified diff 格式回答，放在 ```diff 程式碼區塊中:\n"
    "--- a/相對路徑\n"
    "+++ b/相對路徑\n"
    "@@ -起始行,行數 +起始行,行數 @@\n"
    "每個修改前後至少保留 3 行未變更的內容;新檔案的舊路徑用 /dev/null。\n"
    "<REDACTED:...> 佔位符請保持原樣。"
)

BUILTIN_TEMPLATES: tuple[tuple[str, str], ...] = (
    ("修改程式(完整檔案格式)", f"{_FILE_FORMAT}\n\n我想問:\n"),
    ("修改程式(diff 格式)", f"{_DIFF_FORMAT}\n\n我想問:\n"),
    ("只問問題(不改程式)", "請閱讀上面的程式碼後回答我的問題，不需要修改程式。\n\n我想問:\n"),
    (
        "找 bug / 除錯",
        "我遇到下面的問題，請找出原因並修正。\n\n"
        "現象 / 錯誤訊息:\n\n"
        "重現步驟:\n\n"
        f"{_FILE_FORMAT}\n",
    ),
    (
        "Code review",
        "請幫我審查上面的程式碼(或 git diff),依嚴重程度列出:\n"
        "1. 錯誤或會造成 bug 的地方\n"
        "2. 潛在問題(邊界情況、錯誤處理、執行緒安全、資源釋放)\n"
        "3. 可讀性與效能的改善建議\n"
        "每一點請附上檔案路徑與行號。先不要修改程式。\n\n"
        "特別注意:\n",
    ),
    (
        "解釋程式碼",
        "請解釋上面的程式碼：整體架構、主要模組的職責、資料如何流動，以及閱讀時要注意的地方。不需要修改程式。\n\n"
        "我特別想了解:\n",
    ),
)


@dataclass
class PromptTemplate:
    name: str
    text: str
    source: TemplateSource = field(default="user", compare=False)

    @property
    def builtin_name(self) -> bool:
        return self.source in ("builtin", "override")


def builtin_templates() -> list[PromptTemplate]:
    return [PromptTemplate(name, text, "builtin") for name, text in BUILTIN_TEMPLATES]


def builtin_text(name: str) -> str | None:
    return dict(BUILTIN_TEMPLATES).get(name)


def prompts_path() -> Path:
    return user_config_dir() / PROMPTS_FILENAME


def load_user_templates(path: Path | None = None) -> list[PromptTemplate]:
    path = path or prompts_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict) or int(data.get("schema_version", SCHEMA_VERSION)) > SCHEMA_VERSION:
        return []
    templates = []
    for item in data.get("templates", []):
        if isinstance(item, dict) and str(item.get("name", "")).strip():
            templates.append(PromptTemplate(str(item["name"]).strip(), str(item.get("text", ""))))
    return templates


def save_user_templates(templates: list[PromptTemplate], path: Path | None = None) -> None:
    path = path or prompts_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "schema_version": SCHEMA_VERSION,
        "templates": [{"name": t.name, "text": t.text} for t in templates],
    }
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def all_templates(path: Path | None = None) -> list[PromptTemplate]:
    """Built-ins first (user overrides applied), then the user's own templates."""
    user = {t.name: t for t in load_user_templates(path)}
    result = []
    for t in builtin_templates():
        override = user.pop(t.name, None)
        result.append(PromptTemplate(t.name, override.text, "override") if override else t)
    result.extend(user.values())
    return result


def find_template(name: str, path: Path | None = None) -> PromptTemplate:
    for t in all_templates(path):
        if t.name == name:
            return t
    raise KeyError(f"template {name!r} not found")


def set_template(name: str, text: str, path: Path | None = None) -> None:
    """Create or update a user template (editing a built-in stores an override).

    Saving a built-in's original text removes the override instead.
    """
    name = name.strip()
    if not name:
        raise ValueError("template name is empty")
    user = [t for t in load_user_templates(path) if t.name != name]
    if builtin_text(name) != text:
        user.append(PromptTemplate(name, text))
    save_user_templates(user, path)


def delete_template(name: str, path: Path | None = None) -> None:
    """Delete a user template, or restore a built-in to its default text."""
    user = load_user_templates(path)
    remaining = [t for t in user if t.name != name]
    if len(remaining) == len(user) and builtin_text(name) is not None:
        return  # built-in without override: nothing to do
    if len(remaining) == len(user):
        raise KeyError(f"template {name!r} not found")
    save_user_templates(remaining, path)
