# pr-review

Blind, isolated review of a branch before it becomes a pull request.

`pr-review` packages the diff against the base branch, the full source
tree at the reviewed commit, the output of the repository's lint layer
and the output of its test suite, then runs Claude Code (Anthropic) or
Codex (OpenAI) inside that package as an external reviewer with read-only
permissions and no context
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
- for Anthropic: the [Claude Code CLI](https://docs.claude.com/en/docs/claude-code)
  (`claude`) with its own login: run `claude login` once in a terminal.
  The desktop app's session does not carry over.
- for OpenAI: the [Codex CLI](https://developers.openai.com/codex/cli/)
  (`codex`), authenticated with `codex login`. Use a current version that
  supports `--ignore-user-config`, `--ignore-rules`, `--ephemeral`, and
  the `skip_host_skill_discovery` feature. Only the selected CLI is needed;
  `--no-review` requires neither.
- whatever the repository's hook needs. For `borg-ui`: Python 3 with
  `venv`, Node with `npm` (the hook fetches Node 22 through `npm exec`
  for CI parity), and a `frontend/node_modules` in the checkout or the
  patience for `npm ci`.
- optional: `ruff` and `shellcheck` for the hook-less fallback lint

A run uses the account authenticated with the selected CLI. On
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
pr-review --provider anthropic     # Claude Fable (default provider)
pr-review --provider openai        # GPT-6 Astra via Codex
pr-review --provider openai --effort xhigh
pr-review --parallel               # tests run while the reviewer works
pr-review --quick                  # tests narrowed to touched test files
pr-review --no-review              # build the package only, no reviewer call
pr-review --head fix/some-branch   # review a branch without checking it out
pr-review --coderabbit             # CodeRabbit CLI as a second opinion, in parallel
pr-review --out ./REVIEW.md upstream/main
```

### Reviewer selection

`--provider anthropic` uses `claude -p --model fable`; `--provider openai`
uses `codex exec --model gpt-6-astra`. The default is Anthropic. Set
`PR_REVIEW_PROVIDER=openai` in your shell to change the default; an explicit
`--provider` wins. `--model MODEL` overrides the selected provider's model,
and `--effort LEVEL` is passed to that provider (default `high`). Use a
level supported by the chosen model. Model access depends on your account.
The model names follow the [Claude model catalog](https://platform.claude.com/docs/en/models/overview)
and [GPT-6 Astra documentation](https://developers.openai.com/api/docs/models/gpt-6-astra).

Both providers receive the same brief and package. The provider, model,
and effort are recorded in `summary.txt`. Existing `--parallel`, `--quick`,
`--head`, `--out`, and `--coderabbit` options work with either provider.

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

For Anthropic, `claude -p` starts inside the package with:

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

For OpenAI, `codex exec` runs in the package using a read-only sandbox,
`approval_policy="never"`, and `--ephemeral`. User configuration and execution
rules are ignored while the existing `CODEX_HOME` remains available for
login. Project instructions, host skill discovery, plugins, apps, hooks,
memory, subagents, browser/computer tools, web search, and shell snapshots
are disabled. Shell commands inherit a minimal environment without secret
variables or shell-profile loading. These options follow the
[Codex CLI reference](https://developers.openai.com/codex/cli/reference/).

Both providers strip `AGENTS.md`, `AGENTS.override.md`, `.codex/`, and
`.agents/` in addition to the Claude configuration listed above. Calling
`CODEX_*` session variables are also unset, except `CODEX_HOME` for login.
The brief restricts the review to package inputs; read-only permissions
are not a filesystem read jail. Administrator-managed CLI policies still
apply. Custom extra CLI arguments can override these defaults.

Codex's final message becomes `REVIEW.md`; its execution output is retained
in `reviewer.stdout` and diagnostics in `reviewer.stderr`.

On a reviewer failure (auth, quota), any verdict output is kept as
`REVIEW.failed.txt`; Codex logs remain in `reviewer.stdout` and
`reviewer.stderr`. An error page is never mistaken for a review.

## CodeRabbit

`--coderabbit` runs the [CodeRabbit CLI](https://docs.coderabbit.ai/cli)
on the same commit range while the blind reviewer works, and appends its
output to `REVIEW.md` under its own heading. The reviewer never sees it,
so the two verdicts stay independent. On a fork whose pull requests are
reviewed by CodeRabbit anyway, this front-loads that round before the
push.

Facts that shape the integration:

- The CLI is a cloud service: the diff leaves the machine. The flag is
  therefore opt-in per run, and a hook may set
  `PR_REVIEW_NO_CODERABBIT=1` to refuse it for a repository.
- It needs a git worktree and computes the diff itself, so it cannot
  run inside the package's `src/`. It runs in the real checkout for
  `HEAD` (`--committed`, so uncommitted edits are ignored) and, for
  `--head REF`, in a local clone under the package with a branch at the
  reviewed commit. The clone carries the checkout's remotes because
  CodeRabbit resolves organisation, plan and open-source status from
  them.
- `--base-commit` takes the merge base, so the range matches
  `changes.patch` exactly. The "Compare" line in the CLI output names
  the remote default branch, not the base commit; the file list below
  it is the authoritative scope.
- Output: `coderabbit.txt` (colours, terminal hyperlinks and the
  changelog banner stripped), `coderabbit.raw.txt`, `coderabbit.stderr`.
- Rate limits are per plan and per hour (free open-source repositories:
  a separate, lower limit). The run is cut off after
  `PR_REVIEW_CODERABBIT_TIMEOUT` seconds (default 900).

Setup: `brew install --cask coderabbit`, then `coderabbit auth login`
once (browser) and `coderabbit doctor`. The token lives in
`~/.coderabbit/auth.json`, so the call needs no terminal.

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
- `PR_REVIEW_PROVIDER`: default provider (`anthropic` or `openai`)
- `PR_REVIEW_CLAUDE_ARGS`: extra arguments for Anthropic calls only
- `PR_REVIEW_CODEX_ARGS`: extra arguments for OpenAI calls only
  (both argument variables are whitespace-separated, not shell-evaluated;
  embedded quoting is not supported)
- `PR_REVIEW_CODERABBIT_TIMEOUT`: seconds to wait for the CodeRabbit CLI
  (default 900)
- `PR_REVIEW_NO_CODERABBIT`: set to `1` by a hook to refuse `--coderabbit`

## Development

Run the offline integration tests with `python3 -m unittest discover -s tests -v`.
They use temporary Git repositories and mock CLIs; no model calls are made.
Check shell syntax and lint with `bash -n pr-review install.sh` and
`shellcheck pr-review install.sh`.

## License

MIT, see `LICENSE`.
