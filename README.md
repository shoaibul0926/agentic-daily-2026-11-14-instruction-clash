# instruction-clash

A zero-dependency Python CLI that finds **contradictions between the instruction files different coding agents load** (`CLAUDE.md`, `AGENTS.md`, `GEMINI.md`, `.cursorrules`, `.cursor/rules/*.mdc`, `.github/copilot-instructions.md`, `.windsurfrules`) and shows **which agent actually receives which file**.

## The real need behind it

Practitioners keep reporting the same failure: teams end up with several agent instruction files that quietly disagree, and each agent follows a different rule set.

Evidence found while researching (2026-11-14; read via search-result excerpts, since most of these hosts were unreachable from the research sandbox, so details are as reported there):

- Practitioner write-ups on keeping `CLAUDE.md`, `AGENTS.md` and `.cursorrules` in sync describe repos with four files giving four versions of the same rules, and note that *"contradictions fail silently"*, with no resolution rule from the vendors. ([getunblocked.com: Keeping CLAUDE.md, AGENTS.md, and .cursorrules in Sync](https://getunblocked.com/blog/keeping-claude-md-agents-md-cursorrules-in-sync/); [dev.to: Keep AGENTS.md and CLAUDE.md in sync: 5 user-side fixes](https://dev.to/yurukusa/keep-agentsmd-and-claudemd-in-sync-5-user-side-fixes-and-where-each-quietly-breaks-35p5))
- Loader gaps: Claude Code issue reports that a repo with only `AGENTS.md` is silently ignored ([claude-code #6235](https://claudeissues.com/issue/6235-feature-request-support-agents-md), [#39615](https://claudeissues.com/issue/39615-bug-claude-code-does-not-read-agents-md-at-conversation-start)), and Copilot CLI applies only `copilot-instructions.md` when `AGENTS.md` also exists (github/copilot-cli #489, as summarised in the same search results).

Existing linters (ctxlint, cclint, etc.) check **one file** for stale paths and dead commands. I found no tool focused on **cross-file contradiction and per-agent loading**. That narrower gap is what this fills. Caveat: agent loading behaviour is version-specific and changes often; the warnings say "reported" for that reason and you should verify on your version.

## What it does

1. Discovers instruction files and follows `@path` imports (Claude Code style, up to 5 hops, ignoring code fences).
2. Prints the **effective set** per agent (e.g. `claude-code <- CLAUDE.md, AGENTS.md`).
3. Reports:
   - **clash** (error): files naming mutually exclusive choices: JS package manager, Python test runner / installer / formatter, JS formatter, indentation, quote style. Lines with prohibitions ("do not use yarn") are not counted as recommendations.
   - **directive-clash** (error): an "always/must/prefer X" in one file vs "never/avoid/do not X" in another (token-overlap match).
   - **orphan** (warn): `AGENTS.md` that Claude Code will not load because `CLAUDE.md` lacks `@AGENTS.md`.
   - **shadow** (warn): known reported shadowing combinations.
4. Exit code `1` on errors (and on warnings with `--strict`), so it can run in CI.

## Run

```bash
python3 -m instruction_clash /path/to/repo        # human output
python3 -m instruction_clash . --json             # machine-readable
python3 -m instruction_clash . --strict           # fail on warnings too
python3 -m unittest discover -s tests             # 11 tests
```

Example:

```
What each agent actually receives:
  claude-code  <- CLAUDE.md
  codex        <- AGENTS.md

[WARN ] orphan: AGENTS.md exists but CLAUDE.md does not import it ... Add a line `@AGENTS.md` to CLAUDE.md.
[ERROR] clash: JS package manager: CLAUDE.md says pnpm but AGENTS.md says npm
```

## Limits

Heuristic, English-only, regex-based: it catches common, high-signal contradictions, not semantic ones. Extend `CATEGORIES` in `instruction_clash/core.py` to add your own mutually exclusive choices.
