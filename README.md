# yaml-indent-checker-cli

Check YAML files use consistent indentation, fail CI when a tab or a mixed width slips in.

[![CI](https://github.com/haiderstudio/yaml-indent-checker-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/haiderstudio/yaml-indent-checker-cli/actions/workflows/ci.yml) [![Licence: MIT](https://img.shields.io/badge/Licence-MIT-yellow.svg)](LICENSE)

## What it does

`yaml_indent_checker` reads a YAML file and checks two things
about every line: that it uses spaces only for indentation (YAML
forbids tabs outright), and that its indentation is a multiple of
the file's own indent width — the width the file itself uses, found
from the first step down in indentation. Each bad line is reported
with the file and line number, and the tool exits 1 when any
problem is found, so it can fail a CI run. A clean file exits 0.

- A tab in YAML is a hard error, and mixed indentation silently
  re-nests a mapping — a value lands under the wrong key with no
  error at all. This tool catches both before the file ships,
  and points at the exact line.
- Every bad line is reported, not just the first: a file with
  three wrong lines fails with three reports, at lines 3, 5,
  and 6.
- The width is found per file, not fixed: a 2-space file and a
  4-space file both pass, because each is consistent with
  itself. A file with no indented lines has nothing to check
  and passes.
- `--indent N` fixes the width instead of inferring it: every
  indent must then be a multiple of N, so a team that has
  agreed on 2 spaces can enforce it.
- Blank lines and comments are skipped. Lines inside block
  scalars (`|` and `>`) are skipped — that text is literal
  content, and any indent is allowed there. Lines inside
  multi-line flow collections and quoted scalars are skipped
  too. A file given directly on the command line is always
  checked, whatever its name. A folder is walked for `.yaml`
  and `.yml` files, recursively by default
  (`--no-recursive` stops at the top level). `.git` folders
  are never walked, and directory links are never followed.
  `--exclude` skips files and folders by name pattern.
- `--json` prints the result as JSON (the human-readable lines
  go to standard error), and `--stdin` checks one YAML file read
  from standard input.

## Who it is for

Anyone who edits YAML by hand — developers writing CI configs,
Docker Compose files, GitHub Actions workflows, and app settings,
and anyone who has lost a setting to a tab or a mixed indent
and only found out when something broke.

## What it does NOT do

- It does not parse YAML values. It cannot tell you whether a
  file is valid YAML in any other way — a file can pass this
  check and still fail a real YAML parser for another reason.
- It does not check duplicate keys. That is what
  yaml-duplicate-key-checker-cli does; indentation is a
  different check on the same files.
- It does not check the indentation of text inside a block
  scalar (`|` and `>`). That text is literal content, not
  structure, and any indent is allowed there.
- It does not check whether a value is the right type, or
  whether a key is spelled the way some other tool expects.
  That is a schema's job, not an indent check.
- It does not convert or rewrite anything. It is report-only,
  and it never touches the network.
- It uses no YAML library at all — the Python standard library
  has no YAML parser, so this tool is a hand-rolled line scanner
  (see "How it works" below), not a full parser.

## How this differs

- A GitHub search for `"yaml-indent-checker-cli"` returns
  0 results, and a search for `yaml indent checker` returns
  1 result (checked Nov 10, 2026): sspooky13/yaml-standards,
  11 stars — a style guide for YAML files, not a checker
  CLI with a CI gate. No dedicated tool owns this job.
- Repo #57 (yaml-duplicate-key-checker-cli) checks duplicate
  keys; indentation is a different check on the same files.

## How it works

The scanner reads lines and records the indentation of every
line that carries structure — mapping keys, list items, and
plain values — while skipping block scalars, flow collections,
quoted scalars, blank lines, and comments. The file's indent
width is the first increase in indentation between one
structural line and the next: a file that goes from 0 to 2
spaces, then 2 to 4, uses 2-space indents. Every indented
line must then be a multiple of that width. A plain value that
runs over several lines is read as structure, not skipped, so
a wrapped line at an odd indent is reported — keep wrapped
lines at a multiple of your indent width.

## Install

Python 3.10 or newer, nothing else to install.

```sh
git clone https://github.com/haiderstudio/yaml-indent-checker-cli.git
cd yaml-indent-checker-cli
```

## Usage

Check one clean file:

```sh
python3 src/yaml_indent_checker.py examples/good.yaml
```

```text
OK — 1 file(s) checked, all YAML files are clean.
```

Check a file with mixed indentation:

```sh
python3 src/yaml_indent_checker.py examples/bad-mixed.yaml
```

```text
examples/bad-mixed.yaml:3: indentation of 3 spaces is not a multiple of the file's indent width of 2 spaces
examples/bad-mixed.yaml:5: indentation of 3 spaces is not a multiple of the file's indent width of 2 spaces
examples/bad-mixed.yaml:6: indentation of 5 spaces is not a multiple of the file's indent width of 2 spaces
Checked 1 file(s), 3 problem(s) in 1 file(s).
```

The exit code is 1, so a CI run fails.

Check a whole folder:

```sh
python3 src/yaml_indent_checker.py examples
```

```text
examples/bad-mixed.yaml:3: indentation of 3 spaces is not a multiple of the file's indent width of 2 spaces
examples/bad-mixed.yaml:5: indentation of 3 spaces is not a multiple of the file's indent width of 2 spaces
examples/bad-mixed.yaml:6: indentation of 5 spaces is not a multiple of the file's indent width of 2 spaces
examples/bad-tabs.yaml:2: tab character used for indentation (YAML forbids tabs for indentation)
examples/bad-tabs.yaml:3: tab character used for indentation (YAML forbids tabs for indentation)
examples/configs/app.yaml:3: indentation of 3 spaces is not a multiple of the file's indent width of 2 spaces
Checked 5 file(s), 6 problem(s) in 3 file(s).
```

Check one file from standard input:

```sh
printf 'app:\n  name: x\n   version: 1\n' | python3 src/yaml_indent_checker.py --stdin
```

```text
<stdin>:3: indentation of 3 spaces is not a multiple of the file's indent width of 2 spaces
Checked 1 file(s), 1 problem(s) in 1 file(s).
```

Enforce a width of 3 spaces on a 4-space file:

```sh
python3 src/yaml_indent_checker.py examples/server.yaml --indent 3
```

```text
examples/server.yaml:3: indentation of 4 spaces is not a multiple of the expected indent width of 3 spaces (--indent 3)
examples/server.yaml:4: indentation of 4 spaces is not a multiple of the expected indent width of 3 spaces (--indent 3)
examples/server.yaml:5: indentation of 4 spaces is not a multiple of the expected indent width of 3 spaces (--indent 3)
examples/server.yaml:6: indentation of 8 spaces is not a multiple of the expected indent width of 3 spaces (--indent 3)
examples/server.yaml:7: indentation of 8 spaces is not a multiple of the expected indent width of 3 spaces (--indent 3)
examples/server.yaml:8: indentation of 4 spaces is not a multiple of the expected indent width of 3 spaces (--indent 3)
Checked 1 file(s), 6 problem(s) in 1 file(s).
```

Machine-readable output:

```sh
python3 src/yaml_indent_checker.py examples/configs/app.yaml --json
```

```json
{
  "files_checked": 1,
  "problems": [
    {
      "file": "examples/configs/app.yaml",
      "line": 3,
      "reason": "indentation of 3 spaces is not a multiple of the file's indent width of 2 spaces"
    }
  ],
  "files_with_problems": 1
}
```

## Examples

- `examples/good.yaml` — a clean config: nested mappings, a
  list, a block scalar holding lines at odd indents, and a
  quoted value holding a colon. Passes.
- `examples/bad-mixed.yaml` — three problems in one file: a
  2-space file with 3-space and 5-space lines. Fails with
  exit 1.
- `examples/bad-tabs.yaml` — two lines indented with tabs.
  Fails with exit 1.
- `examples/server.yaml` — a clean server config, indented
  four spaces, showing a different width is fine as long as
  it is consistent. Passes.
- `examples/configs/app.yaml` — one mixed-width line, in a
  subfolder. Fails with exit 1.
- `sh examples/run-example.sh` runs the checker on the whole
  `examples/` folder. Its output is in
  `examples/sample-output.md`.

## How it is tested

```sh
python3 tests/test_yaml_indent_checker.py
```

The tests cover: comment stripping (trailing comments, hashes
inside quotes), key parsing (plain, quoted, spaced keys, URLs,
lines that are not keys), value kinds (empty, block, folded,
flow, quoted, scalar, anchored), clean files (2-space and
4-space nesting, flat files, single indented level, lists,
nested keys under list items, deeper-than-one-level nesting),
tabs (leading, after spaces, every tabbed line, tabs inside
values and block scalars passing), mixed widths (exact line
numbers, first-increase inference, 4-then-2 files), skipped
lines (block and folded scalars, flow collections, multi-line
quoted scalars, blank and comment lines, document markers,
wrapped plain values), `--indent` (matching, mismatching,
and zero), file errors (missing, non-UTF-8, null byte, CRLF),
folder walking (`.yaml`/`.yml` only, `.git` skipped,
`--no-recursive`, `--exclude`, direct files, missing paths),
exit codes 0/1/2, `--stdin`, `--json`, `--version`, and the
bundled examples (the sample output is compared byte-for-byte
against a fresh run, and the outputs quoted in this README
are checked against real runs).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

MIT — see [LICENSE](LICENSE).

## Original work

This tool was written from scratch for this repo. The scanner
is hand-rolled because the Python standard library has no YAML
parser; the indentation problem it solves is the same silent
failure family as repo #57 (yaml-duplicate-key-checker-cli),
a different check on the same files. The code, the wording,
and the tests are original.
