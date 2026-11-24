"""Agent Skills served over MCP: the Skills extension io.modelcontextprotocol/skills.

Beta revision, https://github.com/modelcontextprotocol/ext-skills specification/beta/skills.mdx
(SEP-2640), against base protocol 2026-07-28. A skill is a directory with a SKILL.md in the Agent
Skills format: YAML frontmatter with name and description, name equal to the directory name. Every
file of the directory is the resource skill://<name>/<file path>. skills/list and skills/get return
the skill's entry: the SKILL.md URI, the frontmatter as JSON and every file with its SHA-256 digest
and size. Each directory of a skill is a directory resource that resources/directory/read lists.

The files are read once, when the catalog is made, so an entry and the bytes it describes are one
snapshot. A skill that breaks the format or the extension's per-skill limits is left out with a
line on stderr; the server still serves its other skills and its tools.
"""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import quote, unquote

EXTENSION = "io.modelcontextprotocol/skills"
DIRECTORY_MIME = "inode/directory"
SCHEME = "skill://"
# The two per-skill limits every conforming host accepts (skills.mdx, Limits).
MAX_RESOURCES = 512
MAX_BYTES = 16 * 1024 * 1024
# Agent Skills: name is 1 to 64 lowercase letters, digits and single hyphens; description 1 to 1024.
NAME = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
NAME_MAX, DESCRIPTION_MAX = 64, 1024
MIME = {".md": "text/markdown", ".txt": "text/plain", ".json": "application/json",
        ".py": "text/x-python", ".sh": "text/x-shellscript", ".js": "text/javascript",
        ".mjs": "text/javascript", ".html": "text/html", ".svg": "image/svg+xml",
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".pdf": "application/pdf"}
TEXT = {"application/json", "image/svg+xml"}
FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|\Z)", re.S)
FIELD = re.compile(r"([A-Za-z0-9_-]+):[ \t]+(\S.*?)[ \t]*\Z")
NOT_STRING = re.compile(r"(~|null|Null|NULL|true|True|TRUE|false|False|FALSE"
                        r"|[-+]?(\.inf|\.Inf|\.INF|\.nan|\.NaN|\.NAN)"
                        r"|[-+]?(\d[\d_]*)?(\.\d*)?([eE][-+]?\d+)?|0[xo][0-9a-fA-F]+)")


class SkillError(ValueError):
    pass


def digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def uri(skill: str, file: str | None = None) -> str:
    segments = [skill, *(file.split("/") if file else [])]
    return SCHEME + "/".join(quote(segment, safe="") for segment in segments)


def canonical(value) -> str | None:
    """The canonical form of a skill:// URI (segments decoded and encoded again), or None."""
    if not isinstance(value, str) or not value.startswith(SCHEME):
        return None
    rest = value[len(SCHEME):]
    if not rest or rest.endswith("/"):
        return None
    try:
        segments = [unquote(segment, errors="strict") for segment in rest.split("/")]
    except UnicodeDecodeError:
        return None
    if any(segment in ("", ".", "..") for segment in segments):
        return None
    return SCHEME + "/".join(quote(segment, safe="") for segment in segments)


def frontmatter(text: str) -> dict:
    """SKILL.md frontmatter as JSON, for frontmatter of `key: string` lines only; else SkillError.

    A value is a plain, single-quoted or double-quoted string. Nested maps, lists, block scalars
    and plain values YAML reads as numbers, booleans or null are refused, so an entry never shows a
    frontmatter that differs from what a YAML parser reads in the file.
    """
    match = FRONTMATTER.match(text)
    if not match:
        raise SkillError("SKILL.md must begin with YAML frontmatter between --- lines")
    fields = {}
    for line in match.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        field = FIELD.fullmatch(line)
        if not field:
            raise SkillError(f'frontmatter line is not a "key: value" string: {line}')
        key, raw = field.groups()
        if key in fields:
            raise SkillError(f"frontmatter repeats {key}")
        fields[key] = scalar(key, raw)
    return fields


def scalar(key: str, raw: str) -> str:
    if raw.startswith("'"):
        if not re.fullmatch(r"'(?:[^']|'')*'", raw):
            raise SkillError(f"{key}: unterminated single-quoted string")
        return raw[1:-1].replace("''", "'")
    if raw.startswith('"'):
        try:
            value = json.loads(raw)
        except ValueError:
            value = None
        if not isinstance(value, str):
            raise SkillError(f"{key}: a double-quoted string this server reads must also be valid JSON")
        return value
    if re.match(r"[\[\]{}&*!|>%@`,?:-]", raw) or ": " in raw or re.search(r"\s#", raw):
        raise SkillError(f"{key}: plain value has YAML syntax; quote it")
    if NOT_STRING.fullmatch(raw):
        raise SkillError(f"{key}: plain value is not a string; quote it")
    return raw


def text_of(data: bytes):
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def read_skill(directory: Path):
    name = directory.name
    markdown = (directory / "SKILL.md").read_bytes()
    fields = frontmatter(markdown.decode("utf-8"))
    if fields.get("name") != name:
        raise SkillError(f"frontmatter name {fields.get('name')} must equal the directory name {name}")
    if not NAME.fullmatch(name) or len(name) > NAME_MAX:
        raise SkillError(f"name {name} must be 1 to {NAME_MAX} lowercase letters, digits and single hyphens")
    description = fields.get("description")
    if not isinstance(description, str) or not description.strip() or len(description) > DESCRIPTION_MAX:
        raise SkillError(f"description must be 1 to {DESCRIPTION_MAX} characters")
    files, directories, total = {}, {uri(name): []}, 0
    for path in sorted(directory.rglob("*")):
        relative = path.relative_to(directory).as_posix()
        parent = uri(name, relative.rpartition("/")[0] or None)
        if path.is_symlink() or not (path.is_dir() or path.is_file()):
            raise SkillError(f"{relative} is neither a file nor a directory")
        if path.is_dir():
            directories[uri(name, relative)] = []
            directories[parent].append({"uri": uri(name, relative), "name": path.name, "mimeType": DIRECTORY_MIME})
            continue
        data = markdown if relative == "SKILL.md" else path.read_bytes()
        total += len(data)
        mime = "text/markdown" if relative == "SKILL.md" else MIME.get(
            path.suffix.lower(), "text/plain" if text_of(data) is not None else "application/octet-stream")
        text = text_of(data) if mime.startswith("text/") or mime in TEXT else None
        files[uri(name, relative)] = (mime, data, text)
        directories[parent].append({"uri": uri(name, relative), "name": path.name, "mimeType": mime, "size": len(data)})
    if len(files) > MAX_RESOURCES:
        raise SkillError(f"{len(files)} files exceed the {MAX_RESOURCES} resources a skill may have")
    if total > MAX_BYTES:
        raise SkillError(f"{total} bytes exceed the {MAX_BYTES} bytes a skill may have")
    entry = {"uri": uri(name, "SKILL.md"), "frontmatter": fields,
             "resources": [{"uri": key, "digest": digest(data), "size": len(data)}
                           for key, (_mime, data, _text) in files.items()]}
    return entry, files, directories


class Catalog:
    """The skills of the given roots: each subdirectory with a SKILL.md is one skill."""

    def __init__(self, roots, log=lambda line: print(line, file=sys.stderr)):
        self.entries, self.files, self.directories = {}, {}, {}
        for root in roots:
            root = Path(root)
            if not root.is_dir():
                continue
            for directory in sorted(root.iterdir()):
                if not (directory / "SKILL.md").is_file():
                    continue
                try:
                    entry, files, directories = read_skill(directory)
                except (OSError, UnicodeDecodeError, SkillError) as error:
                    log(f"Riff skill {directory.name} is not served: {error}")
                    continue
                if entry["uri"] in self.entries:
                    log(f"Two Riff skills are named {entry['uri']}; the second is not served")
                    continue
                self.entries[entry["uri"]] = entry
                self.files.update(files)
                self.directories.update(directories)

    def __len__(self):
        return len(self.entries)

    def list(self):
        return list(self.entries.values())

    def get(self, value):
        return self.entries.get(canonical(value))

    def read(self, value):
        key = canonical(value)
        if key not in self.files:
            return None
        mime, data, text = self.files[key]
        if text is None:
            return [{"uri": key, "mimeType": mime, "blob": base64.b64encode(data).decode("ascii")}]
        return [{"uri": key, "mimeType": mime, "text": text}]

    def directory(self, value):
        return self.directories.get(canonical(value))
