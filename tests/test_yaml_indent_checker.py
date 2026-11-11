"""Tests for yaml-indent-checker-cli. Standard library only."""

import ast
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SRC = ROOT / "src" / "yaml_indent_checker.py"

sys.path.insert(0, str(ROOT / "src"))
import yaml_indent_checker as yic
from yaml_indent_checker import (
    Problem, check_file, collect, parse_key_line, scan_text,
    strip_comment, value_kind,
)


def problems_as_tuples(text, indent_width=None):
    return [(p.line, p.reason) for p in scan_text(text, "test.yaml", indent_width)]


def run_cli(*args, stdin_text=None, cwd=None):
    return subprocess.run(
        [sys.executable, str(SRC), *args],
        input=stdin_text, capture_output=True, text=True,
        cwd=cwd or str(ROOT))


class StripCommentTests(unittest.TestCase):
    def test_trailing_comment_removed(self):
        self.assertEqual(strip_comment("a: 1 # note"), "a: 1 ")

    def test_full_line_comment(self):
        self.assertEqual(strip_comment("# full line"), "")

    def test_hash_inside_double_quotes_kept(self):
        self.assertEqual(strip_comment('a: "x # y"'), 'a: "x # y"')

    def test_hash_inside_single_quotes_kept(self):
        self.assertEqual(strip_comment("a: 'x # y'"), "a: 'x # y'")

    def test_hash_without_space_kept(self):
        self.assertEqual(strip_comment("url: http://x#y"),
                         "url: http://x#y")


class ParseKeyLineTests(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(parse_key_line("name: value"), ("name", "value"))

    def test_spaced_key(self):
        self.assertEqual(parse_key_line("my key: 1"), ("my key", "1"))

    def test_space_before_colon(self):
        self.assertEqual(parse_key_line("key : 1"), ("key", "1"))

    def test_empty_value(self):
        self.assertEqual(parse_key_line("key:"), ("key", ""))

    def test_double_quoted_key(self):
        self.assertEqual(parse_key_line('"name": 1'), ("name", "1"))

    def test_single_quoted_key(self):
        self.assertEqual(parse_key_line("'name': 1"), ("name", "1"))

    def test_not_a_key(self):
        self.assertIsNone(parse_key_line("just some text"))

    def test_url_value(self):
        self.assertEqual(parse_key_line("url: http://x"),
                         ("url", "http://x"))


class ValueKindTests(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(value_kind("")[0], "empty")

    def test_block_literal(self):
        self.assertEqual(value_kind("|")[0], "block")

    def test_block_folded(self):
        self.assertEqual(value_kind(">")[0], "block")

    def test_flow(self):
        self.assertEqual(value_kind("{a: 1}")[0], "flow")

    def test_quoted(self):
        self.assertEqual(value_kind('"x"')[0], "quoted")

    def test_scalar(self):
        self.assertEqual(value_kind("plain")[0], "scalar")

    def test_anchor_then_block(self):
        self.assertEqual(value_kind("&a |")[0], "block")


class CleanFileTests(unittest.TestCase):
    def test_two_space_nesting_passes(self):
        text = "app:\n  name: x\n  server:\n    host: h\n    port: 1\n"
        self.assertEqual(problems_as_tuples(text), [])

    def test_four_space_nesting_passes(self):
        text = "server:\n    host: h\n    tls:\n        on: true\n"
        self.assertEqual(problems_as_tuples(text), [])

    def test_flat_file_passes(self):
        self.assertEqual(problems_as_tuples("a: 1\nb: 2\n"), [])

    def test_empty_file_passes(self):
        self.assertEqual(problems_as_tuples(""), [])

    def test_comments_only_passes(self):
        self.assertEqual(problems_as_tuples("# note\n# more\n"), [])

    def test_single_indented_level_passes(self):
        # One indented line sets its own width; nothing contradicts it.
        self.assertEqual(problems_as_tuples("app:\n   name: x\n"), [])

    def test_list_items_pass(self):
        text = "items:\n  - one\n  - two\n  - three\n"
        self.assertEqual(problems_as_tuples(text), [])

    def test_nested_keys_under_list_item_pass(self):
        text = "- name: x\n  other: y\n- name: z\n  other: w\n"
        self.assertEqual(problems_as_tuples(text), [])

    def test_deeper_than_one_level_passes(self):
        # Skipping a level is legal YAML; 6 is a multiple of 2.
        text = "a:\n  b:\n      c: 1\n"
        self.assertEqual(problems_as_tuples(text), [])

    def test_quoted_value_with_colon_passes(self):
        text = 'app:\n  url: "https://example.com/docs"\n'
        self.assertEqual(problems_as_tuples(text), [])


class TabTests(unittest.TestCase):
    def test_leading_tab_flagged(self):
        found = problems_as_tuples("app:\n\tname: x\n")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0][0], 2)
        self.assertIn("tab character", found[0][1])

    def test_tab_after_spaces_flagged(self):
        found = problems_as_tuples("app:\n  \tname: x\n")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0][0], 2)

    def test_every_tabbed_line_reported(self):
        found = problems_as_tuples("app:\n\tname: x\n\tversion: 1\n")
        self.assertEqual([line for line, _ in found], [2, 3])

    def test_tab_inside_value_not_flagged(self):
        # A tab after the value is not indentation.
        self.assertEqual(problems_as_tuples("a: x\ty\n"), [])

    def test_tab_in_block_scalar_content_not_flagged(self):
        text = "notes: |\n\tTabbed literal text\n"
        self.assertEqual(problems_as_tuples(text), [])


class MixedWidthTests(unittest.TestCase):
    def test_three_spaces_in_two_space_file(self):
        found = problems_as_tuples("app:\n  name: x\n   version: 1\n")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0][0], 3)
        self.assertIn("3 spaces", found[0][1])
        self.assertIn("indent width of 2 spaces", found[0][1])

    def test_every_bad_line_reported(self):
        text = ("app:\n  name: x\n   version: 1\n    debug: true\n"
                "   server:\n     host: h\n")
        found = problems_as_tuples(text)
        self.assertEqual([line for line, _ in found], [3, 5, 6])

    def test_four_then_two_mixed(self):
        # First increase is 4, so 2-space lines are the odd ones out.
        text = "app:\n    name: x\n  version: 1\n"
        found = problems_as_tuples(text)
        self.assertEqual([line for line, _ in found], [3])
        self.assertIn("indent width of 4 spaces", found[0][1])

    def test_width_inferred_from_first_increase(self):
        # The first increase is 2, so a later 4-space line is fine.
        text = "a:\n  b:\n    c: 1\n  d: 2\n"
        self.assertEqual(problems_as_tuples(text), [])

    def test_six_spaces_in_two_space_file_passes(self):
        text = "a:\n  b:\n      c: 1\n"
        self.assertEqual(problems_as_tuples(text), [])


class SkippedLineTests(unittest.TestCase):
    def test_block_scalar_content_skipped(self):
        text = ("notes: |\n  any indent here\n     even this one\n"
                "next: 1\n")
        self.assertEqual(problems_as_tuples(text), [])

    def test_folded_scalar_content_skipped(self):
        text = "notes: >\n   folded\n      text\nnext: 1\n"
        self.assertEqual(problems_as_tuples(text), [])

    def test_block_scalar_ends_and_checking_resumes(self):
        text = ("notes: |\n  literal\napp:\n  name: x\n   bad: 1\n")
        found = problems_as_tuples(text)
        self.assertEqual([line for line, _ in found], [5])

    def test_flow_collection_lines_skipped(self):
        text = "key: [\n   1,\n     2]\nnext: 1\n"
        self.assertEqual(problems_as_tuples(text), [])

    def test_multiline_quoted_scalar_skipped(self):
        text = 'text: "one\n   two\n   three"\nnext: 1\n'
        self.assertEqual(problems_as_tuples(text), [])

    def test_blank_and_comment_lines_skipped(self):
        text = "app:\n\n  # a comment\n  name: x\n"
        self.assertEqual(problems_as_tuples(text), [])

    def test_document_marker_resets_block_state(self):
        text = "notes: |\n  literal\n---\napp:\n  name: x\n   bad: 1\n"
        found = problems_as_tuples(text)
        self.assertEqual([line for line, _ in found], [6])

    def test_wrapped_plain_value_line_is_checked(self):
        # A wrapped line at an odd indent is reported, not skipped.
        text = "app:\n  name: some long\n   wrapped value\n"
        found = problems_as_tuples(text)
        self.assertEqual([line for line, _ in found], [3])

    def test_wrapped_plain_value_at_multiple_passes(self):
        text = "name: some long\n  wrapped value\n"
        self.assertEqual(problems_as_tuples(text), [])


class IndentOptionTests(unittest.TestCase):
    def test_explicit_width_passes_matching_file(self):
        text = "app:\n  name: x\n"
        self.assertEqual(problems_as_tuples(text, 2), [])

    def test_explicit_width_flags_other_width(self):
        text = "server:\n   host: h\n"
        found = problems_as_tuples(text, 2)
        self.assertEqual([line for line, _ in found], [2])
        self.assertIn("expected indent width of 2 spaces", found[0][1])

    def test_explicit_width_three_flags_four_space_file(self):
        text = "server:\n    host: h\n    port: 1\n"
        found = problems_as_tuples(text, 3)
        self.assertEqual([line for line, _ in found], [2, 3])

    def test_explicit_width_zero_is_usage_error(self):
        result = run_cli("examples/good.yaml", "--indent", "0")
        self.assertEqual(result.returncode, 2)

    def test_explicit_width_beats_inference(self):
        # Inferred width would be 4; --indent 2 accepts 4-space lines.
        text = "server:\n    host: h\n"
        self.assertEqual(problems_as_tuples(text, 2), [])


class CheckFileTests(unittest.TestCase):
    def test_missing_file(self):
        found = check_file(ROOT / "no-such-file.yaml")
        self.assertEqual(len(found), 1)
        self.assertIn("No such file", found[0].reason)

    def test_non_utf8_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.yaml"
            path.write_bytes(b"a: \xff\xfe\n")
            found = check_file(path)
            self.assertEqual(len(found), 1)
            self.assertIn("not valid UTF-8", found[0].reason)

    def test_null_byte_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.yaml"
            path.write_bytes(b"a: 1\n\x00\n")
            found = check_file(path)
            self.assertEqual(len(found), 1)
            self.assertIn("null byte", found[0].reason)

    def test_crlf_line_endings(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "crlf.yaml"
            path.write_bytes(b"app:\r\n  name: x\r\n   bad: 1\r\n")
            found = check_file(path)
            self.assertEqual([p.line for p in found], [3])


class CollectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def test_folder_walks_yaml_and_yml_only(self):
        self.write("a.yaml", "x:\n  y: 1\n   bad: 1\n")
        self.write("b.yml", "x: 1\n")
        self.write("c.txt", "x:\n   bad: 1\n")
        checked, problems = collect([self.root])
        self.assertEqual({p.name for p in checked}, {"a.yaml", "b.yml"})
        self.assertEqual(len(problems), 1)

    def test_file_given_directly_checked_whatever_its_name(self):
        path = self.write("weird.txt", "x:\n  y: 1\n   bad: 1\n")
        checked, problems = collect([path])
        self.assertEqual(checked, [path])
        self.assertEqual(len(problems), 1)

    def test_git_folder_never_walked(self):
        git = self.root / ".git"
        git.mkdir()
        (git / "hooks.yaml").write_text("x:\n   bad: 1\n")
        self.write("a.yaml", "x: 1\n")
        checked, problems = collect([self.root])
        self.assertEqual([p.name for p in checked], ["a.yaml"])
        self.assertEqual(problems, [])

    def test_no_recursive_stops_at_top_level(self):
        self.write("a.yaml", "x: 1\n")
        self.write("sub/b.yaml", "x:\n   bad: 1\n")
        checked, problems = collect([self.root], recursive=False)
        self.assertEqual([p.name for p in checked], ["a.yaml"])
        self.assertEqual(problems, [])

    def test_exclude_skips_matching_files(self):
        self.write("a.yaml", "x:\n  y: 1\n   bad: 1\n")
        self.write("b.yaml", "x:\n  y: 1\n   bad: 1\n")
        checked, problems = collect([self.root], exclude=["b.yaml"])
        self.assertEqual([p.name for p in checked], ["a.yaml"])
        self.assertEqual(len(problems), 1)

    def test_missing_path_reported(self):
        checked, problems = collect([self.root / "missing.yaml"])
        self.assertEqual(checked, [])
        self.assertEqual(len(problems), 1)
        self.assertIn("no such file or folder", problems[0].reason)


class CliTests(unittest.TestCase):
    def test_clean_file_exit_zero(self):
        result = run_cli("examples/good.yaml")
        self.assertEqual(result.returncode, 0)
        self.assertIn("all YAML files are clean", result.stdout)

    def test_bad_file_exit_one(self):
        result = run_cli("examples/bad-mixed.yaml")
        self.assertEqual(result.returncode, 1)
        self.assertIn("3 problem(s)", result.stdout)

    def test_no_args_exit_two(self):
        result = run_cli()
        self.assertEqual(result.returncode, 2)

    def test_stdin(self):
        result = run_cli("--stdin",
                         stdin_text="app:\n  name: x\n   version: 1\n")
        self.assertEqual(result.returncode, 1)
        self.assertIn("<stdin>:3:", result.stdout)

    def test_stdin_with_path_is_error(self):
        result = run_cli("examples/good.yaml", "--stdin")
        self.assertEqual(result.returncode, 2)

    def test_stdin_clean(self):
        result = run_cli("--stdin", stdin_text="app:\n  name: x\n")
        self.assertEqual(result.returncode, 0)
        self.assertIn("all YAML files are clean", result.stdout)

    def test_json_output(self):
        result = run_cli("examples/configs/app.yaml", "--json")
        self.assertEqual(result.returncode, 1)
        data = json.loads(result.stdout)
        self.assertEqual(data["files_checked"], 1)
        self.assertEqual(data["files_with_problems"], 1)
        self.assertEqual(len(data["problems"]), 1)
        self.assertEqual(data["problems"][0]["line"], 3)
        self.assertIn("3 spaces", data["problems"][0]["reason"])
        self.assertIn("examples/configs/app.yaml:3:",
                      result.stderr)

    def test_json_clean(self):
        result = run_cli("examples/good.yaml", "--json")
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertEqual(data["problems"], [])
        self.assertEqual(data["files_with_problems"], 0)

    def test_version(self):
        result = run_cli("--version")
        self.assertEqual(result.returncode, 0)
        self.assertIn("1.0.0", result.stdout)

    def test_folder_run(self):
        result = run_cli("examples")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Checked 5 file(s), 6 problem(s) in 3 file(s).",
                      result.stdout)


class ExampleTests(unittest.TestCase):
    def test_sample_output_matches_fresh_run(self):
        expected = (ROOT / "examples" / "sample-output.md").read_text()
        block = re.search(r"```text\n(.*?)```", expected, re.S).group(1)
        result = run_cli("examples")
        self.assertEqual(result.stdout, block)

    def test_run_example_script(self):
        result = subprocess.run(
            ["sh", "examples/run-example.sh"],
            capture_output=True, text=True, cwd=str(ROOT))
        self.assertEqual(result.returncode, 0)
        expected = (ROOT / "examples" / "sample-output.md").read_text()
        block = re.search(r"```text\n(.*?)```", expected, re.S).group(1)
        self.assertEqual(result.stdout, block)

    def test_good_example_passes(self):
        result = run_cli("examples/good.yaml")
        self.assertEqual(result.returncode, 0)

    def test_server_example_passes(self):
        result = run_cli("examples/server.yaml")
        self.assertEqual(result.returncode, 0)

    def test_bad_tabs_example_fails(self):
        result = run_cli("examples/bad-tabs.yaml")
        self.assertEqual(result.returncode, 1)
        self.assertIn("2 problem(s)", result.stdout)

    def test_bad_mixed_example_fails(self):
        result = run_cli("examples/bad-mixed.yaml")
        self.assertEqual(result.returncode, 1)
        self.assertIn("3 problem(s)", result.stdout)

    def test_config_example_fails(self):
        result = run_cli("examples/configs/app.yaml")
        self.assertEqual(result.returncode, 1)
        self.assertIn("1 problem(s)", result.stdout)


class ReadmeTests(unittest.TestCase):
    def test_text_blocks_match_live_output(self):
        readme = (ROOT / "README.md").read_text()
        blocks = re.findall(r"```text\n(.*?)```", readme, re.S)
        self.assertTrue(blocks, "no ```text blocks found in README")
        live = []
        live.append(run_cli("examples/good.yaml").stdout)
        live.append(run_cli("examples/bad-mixed.yaml").stdout)
        live.append(run_cli("examples").stdout)
        live.append(run_cli("--stdin",
                            stdin_text="app:\n  name: x\n   version: 1\n").stdout)
        live.append(run_cli("examples/server.yaml",
                            "--indent", "3").stdout)
        joined = "\n".join(live)
        for block in blocks:
            self.assertIn(block.strip(), joined,
                          "README text block not in live output")

    def test_json_block_matches_live_output(self):
        readme = (ROOT / "README.md").read_text()
        match = re.search(r"```json\n(.*?)```", readme, re.S)
        self.assertIsNotNone(match, "no ```json block found in README")
        result = run_cli("examples/configs/app.yaml", "--json")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(match.group(1)),
                         json.loads(result.stdout))


class HygieneTests(unittest.TestCase):
    BANNED = ("TODO", "FIXME", "coming soon", "lorem", "placeholder")

    def test_no_banned_words_in_repo(self):
        hits = []
        for path in ROOT.rglob("*"):
            if not path.is_file():
                continue
            parts = path.relative_to(ROOT).parts
            if ".git" in parts or "__pycache__" in parts:
                continue
            if "tests" in parts:
                continue
            text = path.read_bytes().decode("utf-8", errors="ignore")
            for word in self.BANNED:
                if word in text:
                    hits.append(f"{path.relative_to(ROOT)}: {word}")
        self.assertEqual(hits, [])

    def test_no_third_party_imports(self):
        tree = ast.parse(SRC.read_text())
        stdlib = set(sys.stdlib_module_names)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertIn(alias.name.split(".")[0], stdlib)
            elif isinstance(node, ast.ImportFrom):
                self.assertIn(node.module.split(".")[0], stdlib)

    def test_gitignore_first_line_is_env(self):
        lines = (ROOT / ".gitignore").read_text().splitlines()
        self.assertEqual(lines[0], ".env")

    def test_license_present(self):
        self.assertTrue((ROOT / "LICENSE").exists())
        self.assertIn("MIT License", (ROOT / "LICENSE").read_text())

    def test_ci_file_present_and_runs_tests(self):
        ci = ROOT / ".github" / "workflows" / "ci.yml"
        self.assertTrue(ci.exists())
        text = ci.read_text()
        self.assertIn("python3 tests/test_yaml_indent_checker.py", text)
        self.assertIn("actions/checkout", text)
        self.assertIn("push", text)
        self.assertIn("pull_request", text)

    def test_no_absolute_local_paths(self):
        home = str(Path.home())
        for path in ROOT.rglob("*"):
            if not path.is_file():
                continue
            parts = path.relative_to(ROOT).parts
            if ".git" in parts or "__pycache__" in parts:
                continue
            if "tests" in parts:
                continue
            text = path.read_bytes().decode("utf-8", errors="ignore")
            self.assertNotIn(home, text, str(path))

    def test_readme_names_what_it_does_not_do(self):
        readme = (ROOT / "README.md").read_text()
        self.assertIn("does NOT do", readme)
        self.assertIn("does not parse YAML values", readme)


if __name__ == "__main__":
    unittest.main()
