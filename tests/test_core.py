import tempfile, unittest
from pathlib import Path
from instruction_clash.core import analyze
from instruction_clash.cli import main


def repo(files):
    d = Path(tempfile.mkdtemp())
    for name, text in files.items():
        p = d / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return d


def kinds(r):
    return [(f.kind, f.severity) for f in r["findings"]]


class T(unittest.TestCase):
    def test_package_manager_clash(self):
        r = analyze(repo({"CLAUDE.md": "Run `pnpm install`.", "AGENTS.md": "Run `npm install`."}))
        self.assertTrue(any(f.kind == "clash" and "package manager" in f.message for f in r["findings"]))

    def test_no_clash_when_consistent(self):
        r = analyze(repo({"CLAUDE.md": "@AGENTS.md\n", "AGENTS.md": "Use pnpm. Run pytest."}))
        self.assertEqual(r["findings"], [])
        self.assertEqual(r["effective"]["claude-code"], ["CLAUDE.md", "AGENTS.md"])

    def test_orphan_agents_md(self):
        r = analyze(repo({"CLAUDE.md": "hello", "AGENTS.md": "x"}))
        self.assertIn(("orphan", "warn"), kinds(r))

    def test_agents_only_no_claude(self):
        r = analyze(repo({"AGENTS.md": "x"}))
        self.assertIn(("orphan", "warn"), kinds(r))

    def test_directive_clash(self):
        r = analyze(repo({
            "CLAUDE.md": "Always add type hints to public functions.",
            ".cursorrules": "Never add type hints to public functions."}))
        self.assertIn(("directive-clash", "error"), kinds(r))

    def test_prohibition_not_read_as_recommendation(self):
        r = analyze(repo({"CLAUDE.md": "Use pnpm.", "AGENTS.md": "Do not use yarn; use pnpm."}))
        self.assertEqual([f for f in r["findings"] if f.kind == "clash"], [])

    def test_code_fence_import_ignored(self):
        r = analyze(repo({"CLAUDE.md": "```\n@AGENTS.md\n```", "AGENTS.md": "x"}))
        self.assertIn(("orphan", "warn"), kinds(r))

    def test_copilot_shadow(self):
        r = analyze(repo({".github/copilot-instructions.md": "a", "AGENTS.md": "b"}))
        self.assertIn(("shadow", "warn"), kinds(r))

    def test_indentation_clash(self):
        r = analyze(repo({"CLAUDE.md": "Use 2-space indentation.", "GEMINI.md": "Use 4 spaces."}))
        self.assertTrue(any("Indentation" in f.message for f in r["findings"]))

    def test_cursor_mdc_discovered(self):
        r = analyze(repo({".cursor/rules/a.mdc": "Use tabs for indentation.", "CLAUDE.md": "Use 2 spaces."}))
        self.assertIn(".cursor/rules/a.mdc", r["files"])
        self.assertTrue(any("Indentation" in f.message for f in r["findings"]))

    def test_cli_exit_codes(self):
        bad = repo({"CLAUDE.md": "pnpm install", "AGENTS.md": "npm install"})
        good = repo({"CLAUDE.md": "@AGENTS.md", "AGENTS.md": "pnpm install"})
        warn = repo({"CLAUDE.md": "hi", "AGENTS.md": "pnpm"})
        self.assertEqual(main([str(bad)]), 1)
        self.assertEqual(main([str(good)]), 0)
        self.assertEqual(main([str(warn)]), 0)
        self.assertEqual(main([str(warn), "--strict"]), 1)


if __name__ == "__main__":
    unittest.main()
