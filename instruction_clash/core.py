"""Find contradictions between the agent instruction files in a repo.

Different coding agents load different files (CLAUDE.md, AGENTS.md,
.cursorrules, copilot-instructions.md, ...). When those files disagree, each
agent silently follows a different rule set. This module discovers the files,
works out which agent loads which, and reports contradictions.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# agent -> (files it reads natively, may import others via @path)
NATIVE = {
    "claude-code": ["CLAUDE.md", "CLAUDE.local.md", ".claude/CLAUDE.md"],
    "codex": ["AGENTS.md"],
    "copilot": [".github/copilot-instructions.md"],
    "cursor": [".cursorrules", ".cursor/rules/*.mdc"],
    "gemini-cli": ["GEMINI.md"],
    "windsurf": [".windsurfrules"],
}

# Mutually exclusive choices. Two files naming different members = clash.
CATEGORIES = {
    "JS package manager": {
        "npm": r"\bnpm (?:install|i|ci|run|test|exec)\b|\buse npm\b",
        "pnpm": r"\bpnpm\b",
        "yarn": r"\byarn\b",
        "bun": r"\bbun (?:install|run|test|add)\b|\buse bun\b",
    },
    "Python test runner": {
        "pytest": r"\bpytest\b",
        "unittest": r"\bunittest\b",
        "nose": r"\bnose2?\b",
    },
    "Python env/installer": {
        "uv": r"\buv (?:sync|run|pip|add)\b|\buse uv\b",
        "poetry": r"\bpoetry\b",
        "pip": r"\bpip install\b",
        "pipenv": r"\bpipenv\b",
    },
    "JS formatter": {
        "prettier": r"\bprettier\b",
        "biome": r"\bbiome\b",
        "dprint": r"\bdprint\b",
    },
    "Python formatter/linter": {
        "black": r"\bblack\b",
        "ruff": r"\bruff\b",
        "flake8": r"\bflake8\b",
    },
    "Indentation": {
        "tabs": r"\buse tabs\b|\btab indent|\bindent(?:ation)? (?:with|using) tabs\b|\btabs for indent",
        "2 spaces": r"\b(?:2|two)[- ]space",
        "4 spaces": r"\b(?:4|four)[- ]space",
    },
    "Quote style": {
        "single quotes": r"\bsingle[- ]quotes?\b",
        "double quotes": r"\bdouble[- ]quotes?\b",
    },
}

POS = re.compile(r"\b(?:always|must|should|prefer|ensure)\s+(?!not\b)(.+)", re.I)
NEG = re.compile(r"\b(?:never|must not|should not|do not|don't|avoid)\s+(.+)", re.I)
STOP = set("a an the to of in on for with and or be is are it this that your you we use using when any all every".split())
IMPORT = re.compile(r"(?m)^\s*@([\w./~-]+\.\w+)\s*$|(?<=\s)@([\w./-]+\.md)\b")


@dataclass
class Source:
    path: str            # repo-relative
    text: str
    imported_by: list[str] = field(default_factory=list)


@dataclass
class Finding:
    kind: str            # clash | directive-clash | orphan | shadow
    severity: str        # error | warn
    message: str
    files: list[str]


def discover(root: Path) -> dict[str, Source]:
    found: dict[str, Source] = {}
    for pats in NATIVE.values():
        for pat in pats:
            for p in sorted(root.glob(pat)):
                if p.is_file():
                    rel = p.relative_to(root).as_posix()
                    found[rel] = Source(rel, p.read_text(errors="replace"))
    return found


def resolve_imports(root: Path, files: dict[str, Source]) -> dict[str, list[str]]:
    """Follow @path imports (Claude Code style) up to 5 hops. Returns file->imports."""
    graph: dict[str, list[str]] = {}
    for rel in list(files):
        seen, stack = [], [rel]
        depth = 0
        while stack and depth < 5:
            depth += 1
            cur = stack.pop()
            text = files[cur].text if cur in files else (root / cur).read_text(errors="replace")
            for m in IMPORT.finditer(_strip_code(text)):
                target = m.group(1) or m.group(2)
                tp = (root / Path(cur).parent / target).resolve()
                try:
                    trel = tp.relative_to(root.resolve()).as_posix()
                except ValueError:
                    continue
                if tp.is_file() and trel not in seen and trel != rel:
                    seen.append(trel)
                    if trel not in files:
                        files[trel] = Source(trel, tp.read_text(errors="replace"))
                    files[trel].imported_by.append(rel)
                    stack.append(trel)
        graph[rel] = seen
    return graph


def _strip_code(text: str) -> str:
    return re.sub(r"```.*?```", "", text, flags=re.S)


def effective_set(root: Path, files: dict[str, Source], graph: dict[str, list[str]]) -> dict[str, list[str]]:
    """Which files each agent actually receives."""
    eff: dict[str, list[str]] = {}
    for agent, pats in NATIVE.items():
        got: list[str] = []
        for rel in files:
            if any(Path(rel).match(p) or rel == p for p in pats) and rel in graph:
                got.append(rel)
                got += [i for i in graph[rel] if i not in got]
        if got:
            eff[agent] = got
    return eff


def detect_category_clashes(files: dict[str, Source]) -> list[Finding]:
    out = []
    for cat, options in CATEGORIES.items():
        per_file: dict[str, set[str]] = {}
        for rel, src in files.items():
            text = _strip_neg_context(src.text)
            hit = {name for name, rx in options.items() if re.search(rx, text, re.I)}
            if hit:
                per_file[rel] = hit
        if len(per_file) < 2:
            continue
        names = list(per_file)
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                if per_file[a].isdisjoint(per_file[b]):
                    out.append(Finding(
                        "clash", "error",
                        f"{cat}: {a} says {_fmt(per_file[a])} but {b} says {_fmt(per_file[b])}",
                        [a, b]))
    return out


def _fmt(s: set[str]) -> str:
    return "/".join(sorted(s))


def _strip_neg_context(text: str) -> str:
    """Drop lines like 'do not use yarn' so a prohibition is not read as a recommendation."""
    return "\n".join(l for l in text.splitlines() if not NEG.search(l))


def _norm(phrase: str) -> frozenset[str]:
    words = re.findall(r"[a-z0-9_.+-]+", phrase.lower())
    return frozenset(w for w in words if w not in STOP)


def _directives(text: str):
    pos, neg = [], []
    for line in _strip_code(text).splitlines():
        line = re.sub(r"^[\s>*\-\d.)#]+", "", line).strip()
        if not line:
            continue
        n = NEG.search(line)
        if n:
            neg.append((line, _norm(re.split(r"[.;]", n.group(1))[0])))
            continue
        p = POS.search(line)
        if p:
            pos.append((line, _norm(re.split(r"[.;]", p.group(1))[0])))
    return pos, neg


def detect_directive_clashes(files: dict[str, Source], threshold: float = 0.75) -> list[Finding]:
    out, seen = [], set()
    d = {rel: _directives(s.text) for rel, s in files.items()}
    for a in d:
        for b in d:
            for pl, pn in d[a][0]:
                for nl, nn in d[b][1]:
                    if len(pn) < 2 or len(nn) < 2:
                        continue
                    j = len(pn & nn) / len(pn | nn)
                    key = (a, pl, b, nl)
                    if j >= threshold and key not in seen:
                        seen.add(key)
                        out.append(Finding(
                            "directive-clash", "error",
                            f'"{pl}" ({a}) vs "{nl}" ({b})', sorted({a, b})))
    return out


def detect_loading_gaps(root: Path, files: dict[str, Source], eff: dict[str, list[str]]) -> list[Finding]:
    out = []
    has = lambda f: f in files
    if has("AGENTS.md") and "claude-code" in eff and "AGENTS.md" not in eff["claude-code"]:
        out.append(Finding(
            "orphan", "warn",
            "AGENTS.md exists but CLAUDE.md does not import it, so Claude Code will not "
            "receive those rules. Add a line `@AGENTS.md` to CLAUDE.md.",
            ["AGENTS.md", "CLAUDE.md"]))
    if has("AGENTS.md") and "claude-code" not in eff:
        out.append(Finding(
            "orphan", "warn",
            "AGENTS.md exists but there is no CLAUDE.md: Claude Code would not load it. "
            "Create CLAUDE.md containing `@AGENTS.md`.", ["AGENTS.md"]))
    if has(".github/copilot-instructions.md") and has("AGENTS.md"):
        out.append(Finding(
            "shadow", "warn",
            "Both .github/copilot-instructions.md and AGENTS.md exist; some Copilot clients "
            "apply only the former (reported in github/copilot-cli#489), so the files can "
            "diverge in practice.",
            [".github/copilot-instructions.md", "AGENTS.md"]))
    if has("CLAUDE.local.md") and has("AGENTS.md"):
        out.append(Finding(
            "shadow", "warn",
            "CLAUDE.local.md is present next to AGENTS.md; reported to disable AGENTS.md "
            "fallback in some Claude Code versions (verify on yours).",
            ["CLAUDE.local.md", "AGENTS.md"]))
    return out


def analyze(root: str | Path) -> dict:
    root = Path(root).resolve()
    files = discover(root)
    graph = resolve_imports(root, files)
    eff = effective_set(root, files, graph)
    findings = (detect_loading_gaps(root, files, eff)
                + detect_category_clashes(files)
                + detect_directive_clashes(files))
    return {"root": str(root), "files": sorted(files), "effective": eff,
            "findings": findings}
