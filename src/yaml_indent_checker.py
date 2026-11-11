"""yaml-indent-checker-cli: check YAML files use consistent indentation, fail CI when they do not.

Reads one or more YAML files (or folders of them), checks every line
uses spaces only for indentation (YAML forbids tabs) and that the
indentation width is the same throughout each file, and reports each
bad line with the file and line number. Report-only: it never
rewrites a file. Exit 0 when every file is clean, 1 when any problem
is found, 2 for a usage error.

The scanner is hand-rolled and uses the Python standard library
only: the standard library has no YAML parser, so this tool reads
lines and tracks indentation level by level. That is enough to know
that a tab is wrong anywhere, and that a line indented 3 spaces in
a 2-space file is wrong, without ever parsing a value.

How the width is found: the file's indent width is the first
increase in indentation between one structural line and the next —
a file that goes from 0 to 2 spaces, then 2 to 4, uses 2-space
indents. Every indented line must then be a multiple of that width.
A file with no indented lines has nothing to check and passes. With
--indent N the width is fixed instead of inferred: every indent
must be a multiple of N.

Lines that are not structure are skipped, so they can never cause a
false failure: blank lines and comments, lines inside block scalars
(| and >), and lines inside multi-line flow collections and quoted
scalars. A plain value that runs over several lines is read as
structure, not skipped: a wrapped line sits at whatever indent the
author chose, and this tool checks that indent like any other, so
keep wrapped lines at a multiple of your indent width.

What it does not do: it does not parse YAML values, so it cannot
tell you whether a file is valid YAML in any other way — a file can
pass this check and still fail a real YAML parser for another
reason. It does not check duplicate keys (that is what
yaml-duplicate-key-checker-cli does). It does not check the
indentation of text inside a block scalar: that text is literal
content, not structure, and any indent is allowed there.
"""

import argparse
import fnmatch
import json
import os
import re
import sys
from pathlib import Path

__version__ = "1.0.0"

DOUBLE_KEY_RE = re.compile(r'"((?:[^"\\]|\\.)*)"\s*:(\s|$)')
SINGLE_KEY_RE = re.compile(r"'((?:[^']|'')*)'\s*:(\s|$)")
PLAIN_KEY_RE = re.compile(r"(.+?)\s*:(\s|$)")
ANCHOR_OR_TAG_RE = re.compile(r"([&!][^\s]*)\s*")


class Problem:
    """One problem in one file: path, line number, plain reason."""

    def __init__(self, path, line, reason):
        self.path = path
        self.line = line
        self.reason = reason

    def text(self):
        return f"{self.path}:{self.line}: {self.reason}"

    def as_dict(self):
        return {"file": self.path, "line": self.line, "reason": self.reason}


def strip_comment(line):
    """Remove a trailing YAML comment: '#' outside quotes, at the start or after whitespace."""
    in_single = False
    in_double = False
    i = 0
    while i < len(line):
        ch = line[i]
        if in_single:
            if ch == "'":
                if i + 1 < len(line) and line[i + 1] == "'":
                    i += 2
                    continue
                in_single = False
        elif in_double:
            if ch == "\\":
                i += 2
                continue
            if ch == '"':
                in_double = False
        else:
            if ch == "'":
                in_single = True
            elif ch == '"':
                in_double = True
            elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
                return line[:i]
        i += 1
    return line


def flow_delta(text):
    """Net change in flow-collection depth from one line, quotes ignored."""
    depth = 0
    in_single = False
    in_double = False
    i = 0
    while i < len(text):
        ch = text[i]
        if in_single:
            if ch == "'":
                if i + 1 < len(text) and text[i + 1] == "'":
                    i += 2
                    continue
                in_single = False
        elif in_double:
            if ch == "\\":
                i += 2
                continue
            if ch == '"':
                in_double = False
        else:
            if ch == "'":
                in_single = True
            elif ch == '"':
                in_double = True
            elif ch in "{[":
                depth += 1
            elif ch in "}]":
                depth -= 1
        i += 1
    return depth


def quote_closes(text, quote):
    """True when a quoted scalar starting with `quote` closes within `text`.

    `text` starts just after the opening quote.
    """
    i = 0
    while i < len(text):
        ch = text[i]
        if quote == '"':
            if ch == "\\":
                i += 2
                continue
            if ch == '"':
                return True
        else:
            if ch == "'":
                if i + 1 < len(text) and text[i + 1] == "'":
                    i += 2
                    continue
                return True
        i += 1
    return False


def unescape_double(raw):
    """Undo the escapes in the inside of a double-quoted YAML key."""
    out = []
    i = 0
    while i < len(raw):
        ch = raw[i]
        if ch == "\\" and i + 1 < len(raw):
            nxt = raw[i + 1]
            mapping = {"n": "\n", "t": "\t", "r": "\r",
                       "\\": "\\", '"': '"', "0": "\0"}
            out.append(mapping.get(nxt, nxt))
            i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def parse_key_line(content):
    """Parse one mapping-entry line (comment already stripped).

    Returns (key, value) or None when the line is not a mapping entry.
    Quoted keys count the same as plain keys.
    """
    match = DOUBLE_KEY_RE.match(content)
    if match:
        return (unescape_double(match.group(1)),
                content[match.end():].strip())
    match = SINGLE_KEY_RE.match(content)
    if match:
        return (match.group(1).replace("''", "'"),
                content[match.end():].strip())
    match = PLAIN_KEY_RE.match(content)
    if not match:
        return None
    key = match.group(1).strip()
    if not key or key[0] in "{}[],&*!|>%@`":
        return None
    if key.startswith("? "):
        key = key[2:].strip()
        if not key:
            return None
    return (key, content[match.end():].strip())


def value_kind(value):
    """Classify what follows a key's colon, after anchor/tag markers.

    Returns ("empty" | "block" | "flow" | "quoted" | "scalar", rest),
    where rest is the value with any anchor/tag markers removed.
    """
    rest = value
    while True:
        match = ANCHOR_OR_TAG_RE.match(rest)
        if not match:
            break
        rest = rest[match.end():]
    if not rest:
        return ("empty", "")
    if rest[0] in "|>":
        return ("block", rest)
    if rest[0] in "{[":
        return ("flow", rest)
    if rest[0] in "\"'":
        return ("quoted", rest)
    return ("scalar", rest)


def scan_text(text, label, indent_width=None):
    """Check one YAML document (as text) and return its problems.

    Tabs in indentation and lines whose indentation is not a
    multiple of the file's width are reported at their own lines.
    The width is the first increase in indentation between two
    structural lines, unless --indent fixed it. Every problem is
    reported, not just the first.
    """
    problems = []
    structural = []  # (lineno, indent) for lines that carry structure
    block_indent = None  # indent of a key owning a block scalar
    flow_depth = 0       # > 0 while inside a multi-line flow collection
    quote_char = None    # open quote while inside a multi-line quoted scalar

    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip("\r").rstrip()
        stripped = strip_comment(line).strip()
        if not stripped:
            continue
        leading = line[:len(line) - len(line.lstrip(" \t"))]
        if flow_depth > 0:
            flow_depth += flow_delta(line)
            if flow_depth <= 0:
                flow_depth = 0
            continue
        if quote_char is not None:
            if quote_closes(line, quote_char):
                quote_char = None
            continue
        if block_indent is not None:
            if len(leading) > block_indent:
                continue
            block_indent = None
        if stripped == "---" or stripped.startswith("--- "):
            block_indent = None
            flow_depth = 0
            quote_char = None
            continue
        if stripped == "..." or stripped.startswith("... "):
            block_indent = None
            flow_depth = 0
            quote_char = None
            continue
        if "\t" in leading:
            problems.append(Problem(
                label, lineno,
                "tab character used for indentation "
                "(YAML forbids tabs for indentation)"))
            continue
        indent = len(leading)
        # Strip list-item markers: the dash carries the indent, the
        # key inside the item sits two spaces further in.
        content_start = indent
        while True:
            rest = line[content_start:]
            if rest == "-":
                content_start = None
                break
            if rest.startswith("- "):
                content_start += 2
                while (content_start < len(line)
                       and line[content_start] == " "):
                    content_start += 1
                continue
            break
        if content_start is None:
            structural.append((lineno, indent))
            block_indent = None
            flow_depth = 0
            quote_char = None
            continue
        content = strip_comment(line[content_start:]).strip()
        if not content:
            structural.append((lineno, indent))
            continue
        structural.append((lineno, indent))
        if content[0] in "{[":
            flow_depth = flow_delta(content)
            if flow_depth <= 0:
                flow_depth = 0
            block_indent = None
            quote_char = None
            continue
        parsed = parse_key_line(content)
        if parsed is None:
            # A plain scalar: a list item, or a bare value. It is
            # structure, and its indent is checked like any other.
            block_indent = None
            flow_depth = 0
            quote_char = None
            continue
        key, value = parsed
        key_indent = content_start
        # What follows the key decides what the next lines mean.
        kind, rest = value_kind(value)
        block_indent = None
        flow_depth = 0
        quote_char = None
        if kind == "block":
            block_indent = key_indent
        elif kind == "flow":
            flow_depth = flow_delta(rest)
            if flow_depth <= 0:
                flow_depth = 0
        elif kind == "quoted":
            if not quote_closes(rest[1:], rest[0]):
                quote_char = rest[0]

    if indent_width is None:
        width = None
        previous = None
        for _, indent in structural:
            if previous is not None and indent > previous:
                width = indent - previous
                break
            previous = indent
        if width is None:
            return problems
        width_note = f"the file's indent width of {width} spaces"
    else:
        width = indent_width
        width_note = (f"the expected indent width of {width} spaces "
                      f"(--indent {width})")

    for lineno, indent in structural:
        if indent % width != 0:
            problems.append(Problem(
                label, lineno,
                f"indentation of {indent} spaces is not a multiple of "
                f"{width_note}"))
    problems.sort(key=lambda p: p.line)
    return problems


def check_file(path, indent_width=None):
    """Check one file and return its problems."""
    label = str(path)
    try:
        data = Path(path).read_bytes()
    except OSError as exc:
        return [Problem(label, 1, f"cannot read file: {exc.strerror or exc}")]
    if b"\x00" in data:
        return [Problem(label, 1, "file contains a null byte, not a YAML file")]
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return [Problem(label, 1, "file is not valid UTF-8")]
    return scan_text(text, label, indent_width)


def is_yaml_name(path):
    """True when a file name looks like a YAML file."""
    return path.name.lower().endswith((".yaml", ".yml"))


def collect(paths, recursive=True, exclude=(), indent_width=None):
    """Gather the files to check and their problems.

    A file given directly is always checked, whatever its name. A
    folder is walked for .yaml and .yml files, recursively by
    default. `.git` folders are never walked, and directory links
    are never followed.
    """
    checked = []
    problems = []
    for given in paths:
        path = Path(given)
        if path.is_file():
            checked.append(path)
            problems.extend(check_file(path, indent_width))
        elif path.is_dir():
            for root, dirs, files in os.walk(path, followlinks=False):
                dirs[:] = sorted(d for d in dirs
                                 if d != ".git"
                                 and not any(fnmatch.fnmatch(d, pat)
                                             for pat in exclude))
                for name in sorted(files):
                    candidate = Path(root) / name
                    if not is_yaml_name(candidate):
                        continue
                    if any(fnmatch.fnmatch(name, pat) for pat in exclude):
                        continue
                    checked.append(candidate)
                    problems.extend(check_file(candidate, indent_width))
                if not recursive:
                    break
        else:
            problems.append(Problem(str(given), 1, "no such file or folder"))
    return checked, problems


def main(argv=None):
    """Entry point. Returns the exit code: 0 clean, 1 problems, 2 usage."""
    parser = argparse.ArgumentParser(
        prog="yaml_indent_checker",
        description="Check YAML files use consistent indentation.")
    parser.add_argument("paths", nargs="*", metavar="PATH",
                        help="YAML file or folder to check")
    parser.add_argument("--stdin", action="store_true",
                        help="check one YAML file read from standard input")
    parser.add_argument("--json", action="store_true",
                        help="print the result as JSON (human lines go to standard error)")
    parser.add_argument("--no-recursive", action="store_true",
                        help="do not walk into subfolders")
    parser.add_argument("--exclude", action="append", default=[],
                        metavar="PATTERN",
                        help="skip files and folders matching this name pattern")
    parser.add_argument("--indent", type=int, default=None, metavar="N",
                        help="enforce indent width N instead of inferring it")
    parser.add_argument("--version", action="version",
                        version=f"%(prog)s {__version__}")
    args = parser.parse_args(argv)

    if args.indent is not None and args.indent < 1:
        parser.error("--indent must be 1 or more")
    if args.stdin:
        if args.paths:
            parser.error("--stdin takes no paths")
        text = sys.stdin.read()
        checked = ["<stdin>"]
        problems = scan_text(text, "<stdin>", args.indent)
    else:
        if not args.paths:
            parser.error("give at least one file or folder, or use --stdin")
        checked, problems = collect(args.paths,
                                    recursive=not args.no_recursive,
                                    exclude=args.exclude,
                                    indent_width=args.indent)

    files_with_problems = len({p.path for p in problems})
    if args.json:
        result = {
            "files_checked": len(checked),
            "problems": [p.as_dict() for p in problems],
            "files_with_problems": files_with_problems,
        }
        print(json.dumps(result, indent=2))
        for problem in problems:
            print(problem.text(), file=sys.stderr)
    else:
        for problem in problems:
            print(problem.text())
        if problems:
            print(f"Checked {len(checked)} file(s), "
                  f"{len(problems)} problem(s) in {files_with_problems} file(s).")
        else:
            print(f"OK — {len(checked)} file(s) checked, "
                  f"all YAML files are clean.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
