"""Reply formats the AI is asked to use, so its answer can be applied back."""

from __future__ import annotations

REPLY_NONE = "none"
REPLY_FILES = "files"
REPLY_DIFF = "diff"
REPLY_FORMATS = (REPLY_NONE, REPLY_FILES, REPLY_DIFF)

FILE_START = "=== FILE: {path} ==="
FILE_END = "=== END FILE ==="
DELETE_MARK = "=== DELETE: {path} ==="

_COMMON = (
    "Use paths relative to the project root, exactly as they appear in this document. "
    "Keep every <REDACTED:...> placeholder exactly as written; they stand for values that were removed. "
    "You may explain your changes in any language outside these blocks."
)

FILES_INSTRUCTIONS = f"""## Reply format

When you change code, give the COMPLETE new content of every file you create or modify, each wrapped exactly like this:

{FILE_START.format(path="path/to/file.ext")}
<entire file content, no omissions>
{FILE_END}

To delete a file, write a single line: {DELETE_MARK.format(path="path/to/file.ext")}

Never abbreviate with "..." or "rest unchanged"; the file is replaced by what you write. {_COMMON}
"""

DIFF_INSTRUCTIONS = f"""## Reply format

When you change code, reply with a unified diff inside a ```diff code block:

```diff
--- a/path/to/file.ext
+++ b/path/to/file.ext
@@ -10,7 +10,8 @@
 unchanged context line
-removed line
+added line
```

Include at least 3 unchanged context lines around every change. Use /dev/null as the old path for new files and as the new path for deleted files. {_COMMON}
"""


def reply_instructions(fmt: str) -> str:
    if fmt == REPLY_FILES:
        return FILES_INSTRUCTIONS
    if fmt == REPLY_DIFF:
        return DIFF_INSTRUCTIONS
    return ""
