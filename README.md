# pr-review

Blind, isolated review of a branch before it becomes a pull request.

`pr-review` packages the diff against the base branch, the full source
tree at the reviewed commit, the output of the repository's lint layer
and the output of its test suite, then runs `claude -p` inside that
package as an external reviewer with read-only tools and no context
beyond the package. The reviewer is told to assume the diff is broken
and must give `file:line` plus a failure scenario for every finding.
The verdict lands in `REVIEW.md` inside the package, never in the
repository.

It is stricter than a hosted review bot because the reviewer gets the
whole tree, the lint output and the test output, and because it sees
neither the branch name, the commit messages, nor the author's assistant
configuration.

## Requirements

- bash 3.2 or newer, git, a POSIX `sed`, `mktemp`, `shasum` (macOS and
  Linux both qualify out of the box)
- the [Claude Code CLI](https://docs.claude.com/en/docs/claude-code)
  (`claude`) with its own login: run `claude login` once in a terminal.
  The desktop app's session does not carry over.
- whatever the repository's hook needs. For `borg-ui`: Python 3 with
  `venv`, Node with `npm` (the hook fetches Node 22 through `npm exec`
  for CI parity), and a `frontend/node_modules` in the checkout or the
  patience for `npm ci`.
- optional: `ruff` and `shellcheck` for the hook-less fallback lint

A run costs real tokens on the account behind `claude login`. On
`borg-ui` a full run takes roughly 15 minutes with `--parallel`
(unit suite about 9 minutes, reviewer about 14 minutes at effort
`high`).

## Install

```bash
git clone https://github.com/<owner>/pr-review.git
cd pr-review
./install.sh
```

This symlinks `~/bin/pr-review` and `~/.config/pr-review` into the
clone, so `git pull` updates the script, the brief and the hooks
together. Existing non-symlink files are moved to `*.bak`. Pass
`--bin DIR` or `--config DIR` to choose other locations.

## Run

Inside the repository, on the branch to review, with the work
committed (only `HEAD` is reviewed, the working tree is ignored):

```bash
pr-review                          # base = upstream/main, upstream/master, origin/main, ...
pr-review --parallel               # tests run while the reviewer works
pr-review --quick                  # tests narrowed to touched test files
pr-review --no-review              # build the package only, no reviewer call
pr-review --head fix/some-branch   # review a branch without checking it out
pr-review --out ./REVIEW.md upstream/main
```

`--parallel` roughly halves wall time. The trade-off: the reviewer is
told that tests are still running and does not see `tests.txt`; the
script appends the test result (and the tail of `tests.txt` on failure)
to `REVIEW.md` afterwards.

The package lands under `$TMPDIR/pr-review/<repo>-<timestamp>-XXXX/`
and stays there:

```
changes.patch              diff merge-base(BASE, HEAD)..HEAD
changed-files.txt          touched paths (changed-files-status.txt adds A/M/D)
src/                       full tree at HEAD, no .git, no assistant config
lint.txt                   output of the lint layer
tests.txt                  output of the test layer
summary.txt                shas, counts, exit codes handed to the reviewer
BRIEF.md                   the reviewer instructions actually used
REVIEW.md                  the verdict: Blocking / Should fix / Nitpicks
```

Submodules appear as empty directories in `src/`; to review a submodule
branch, run `pr-review` inside the submodule. The script never modifies
the checkout.

### Suggested workflow

1. Commit, run `pr-review --parallel --out /tmp/review-1.md`.
2. Verify every finding against the code. The reviewer lacks project
   history and refutes itself on roughly one finding in five; do not
   apply blindly.
3. Fix what holds, amend, run a second round.
4. Open the pull request once the second round has no blocking findings.

## Isolation

The reviewer is `claude -p` started inside the package with:

- `--tools Read,Grep,Glob` and the same allow-list: read-only
- `--strict-mcp-config` without any config: no MCP servers
- `--setting-sources ""`: no user, project or local settings, no hooks,
  no plugins
- `--no-session-persistence`: nothing written to `~/.claude/projects`
- cwd = package: no repository `CLAUDE.md`, no auto-memory for that path
- `CLAUDE.md`, `CLAUDE.local.md`, `.claude/`, `.mcp.json` stripped from
  `src/` so nothing is auto-loaded while the reviewer reads code (listed
  in `stripped-from-src.txt`)
- every `CLAUDE*` variable of a calling Claude Code session is unset, so
  a session that runs `pr-review` cannot leak its identity into the
  reviewer

On a reviewer failure (auth, quota) the output is kept as
`REVIEW.failed.txt` so an error page is never mistaken for a review.

## Hooks

A hook is a bash file that may define one or both of:

```bash
pr_review_lint() { ...; }   # cwd=$SRC, output -> lint.txt
pr_review_test() { ...; }   # cwd=$SRC, output -> tests.txt
```

Lookup order:

1. `--hook FILE`
2. `.pr-review/hook.sh` inside the reviewed tree, so a repository can
   ship its own hook next to the CI definition it mirrors
3. `config/hooks/<repo>.sh`, where `<repo>` is the basename of the git
   toplevel (a clone named differently needs `--hook`)

Available variables: `SRC` (clean export of HEAD), `REPO` (real checkout:
read it, do not write), `OUT` (package dir), `CACHE`
(`~/.cache/pr-review`, for venvs and the like), `CHANGED_FILES` (file
with the touched paths), `QUICK` (0/1), `BASE_SHA`, `HEAD_SHA`.

A non-zero exit is recorded in `summary.txt` and shown to the reviewer
as evidence. It does not abort the run. Without a hook, `ruff` and
`shellcheck` run when applicable and tests are skipped.

Shipped hooks:

- `config/hooks/borg-ui.sh`: mirrors `.github/workflows/tests.yml` of
  [borg-ui](https://github.com/karanhudia/borg-ui): ruff check and
  format, `pytest tests/unit`, prettier, tsc, oxlint, locale parity and
  vitest under Node 22. Each side runs only when the diff touches it.
  Keeps one cached venv per `requirements.txt` hash under
  `~/.cache/pr-review/venv/` and links the checkout's
  `frontend/node_modules` when the lockfile is unchanged.
- `config/hooks/k8s-borg.sh`: `helm lint` on the chart, `shellcheck`
  on touched shell scripts, no test layer.

## Environment

- `PR_REVIEW_DIR`: package root (default `$TMPDIR/pr-review`)
- `PR_REVIEW_CONFIG`: config directory (default `~/.config/pr-review`)
- `PR_REVIEW_CLAUDE_ARGS`: extra arguments for the reviewer call

## License

MIT, see `LICENSE`.
