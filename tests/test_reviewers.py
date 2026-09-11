"""Offline CLI integration tests, including Bash 3.2 on macOS."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
VERDICT = "## Blocking\nNone.\n## Should fix\nNone.\n## Nitpicks\nNone.\n"
MOCK = '''#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
provider = pathlib.Path(sys.argv[0]).name
pathlib.Path(os.environ["MOCK_CAPTURE"]).write_text(json.dumps({
    "provider": provider, "args": args, "cwd": os.getcwd(),
    "prompt": sys.stdin.read() if provider == "codex" else args[-1],
    "session": {k: v for k, v in os.environ.items()
                if k.startswith(("CLAUDE", "CODEX_"))},
}))
mode = os.environ.get("MOCK_MODE", "success")
if mode == "fail":
    print("quota exceeded")
    print("authentication or quota failure", file=sys.stderr)
    sys.exit(7)
if mode == "empty":
    print("execution log without final message") if provider == "codex" else None
    sys.exit(0)
verdict = "## Blocking\\nNone.\\n## Should fix\\nNone.\\n## Nitpicks\\nNone.\\n"
if provider == "codex":
    pathlib.Path(args[args.index("--output-last-message") + 1]).write_text(verdict)
    print("execution log, not the verdict")
else:
    print(verdict, end="")
'''


class ReviewersTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="pr-review-test-")
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.repo = self.work / "repo"
        self.repo.mkdir()
        self.bin = self.work / "bin"
        self.bin.mkdir()
        for name in ("claude", "codex"):
            cli = self.bin / name
            cli.write_text(MOCK)
            cli.chmod(0o755)
        self.env = dict(os.environ)
        for key in list(self.env):
            if key.startswith(("PR_REVIEW_", "CLAUDE", "CODEX_", "GIT_")):
                del self.env[key]
        self.env.update(
            PATH=f"{self.bin}:{os.environ['PATH']}",
            PR_REVIEW_CONFIG=str(ROOT / "config"),
            PR_REVIEW_DIR=str(self.work / "packages"),
            XDG_CACHE_HOME=str(self.work / "cache"),
            MOCK_CAPTURE=str(self.work / "capture.json"),
            CLAUDE_CODE_SESSION_ID="caller",
            CODEX_THREAD_ID="caller",
            CODEX_HOME=str(self.work / "codex-auth"),
            GIT_CONFIG_GLOBAL=os.devnull,
            GIT_CONFIG_NOSYSTEM="1",
        )
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "Test")
        (self.repo / "code.txt").write_text("before\n")
        self.git("add", ".")
        self.git("commit", "-qm", "Base")
        self.git("branch", "base")
        (self.repo / "code.txt").write_text("after\n")
        self.git("add", ".")
        self.git("commit", "-qm", "Change")

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.repo, env=self.env,
                              check=True, capture_output=True, text=True)

    def run_review(self, *args, tests=False):
        command = ["/bin/bash", str(ROOT / "pr-review"), "--no-lint"]
        if not tests:
            command.append("--no-tests")
        return subprocess.run(command + list(args) + ["base"], cwd=self.repo,
                              env=self.env, capture_output=True, text=True)

    def package(self):
        return next((self.work / "packages").iterdir())

    def capture(self):
        return json.loads((self.work / "capture.json").read_text())

    def test_anthropic_default_and_session_isolation(self):
        self.env["PR_REVIEW_CLAUDE_ARGS"] = "--verbose"
        self.env["PR_REVIEW_CODEX_ARGS"] = "--wrong-provider-argument"
        result = self.run_review()
        self.assertEqual(result.returncode, 0, result.stderr)
        call = self.capture()
        self.assertEqual(call["provider"], "claude")
        self.assertEqual(call["args"][call["args"].index("--model") + 1], "fable")
        self.assertIn("--verbose", call["args"])
        self.assertNotIn("--wrong-provider-argument", call["args"])
        self.assertEqual(call["session"], {"CODEX_HOME": self.env["CODEX_HOME"]})
        self.assertEqual((self.package() / "REVIEW.md").read_text(), VERDICT)

    def test_openai_output_prompt_and_isolation(self):
        for name in ("AGENTS.md", "nested/AGENTS.override.md", ".codex/config.toml",
                     ".agents/skills/example/SKILL.md", "CLAUDE.md", ".claude/settings.json"):
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("author instructions")
        self.git("add", ".")
        self.git("commit", "-qm", "Assistant configuration")
        self.env["PR_REVIEW_CODEX_ARGS"] = "--json"
        self.env["PR_REVIEW_CLAUDE_ARGS"] = "--wrong-provider-argument"
        copy = self.work / "copied review.md"
        result = self.run_review("--provider", "openai", "--out", str(copy))
        self.assertEqual(result.returncode, 0, result.stderr)
        call = self.capture()
        args = call["args"]
        self.assertEqual(call["provider"], "codex")
        self.assertEqual(args[args.index("--model") + 1], "gpt-6-astra")
        self.assertEqual(args[args.index("--sandbox") + 1], "read-only")
        for flag in ("--ignore-user-config", "--ignore-rules", "--ephemeral", "--json"):
            self.assertIn(flag, args)
        self.assertNotIn("--wrong-provider-argument", args)
        self.assertIn('approval_policy="never"', args)
        self.assertEqual(call["prompt"], (self.package() / "BRIEF.md").read_text())
        self.assertEqual(Path(call["cwd"]).resolve(), self.package().resolve())
        self.assertEqual(call["session"], {"CODEX_HOME": self.env["CODEX_HOME"]})
        self.assertEqual(copy.read_text(), VERDICT)
        self.assertIn("execution log", (self.package() / "reviewer.stdout").read_text())
        self.assertFalse((self.package() / "src/AGENTS.md").exists())
        self.assertFalse((self.package() / "src/.codex").exists())
        self.assertFalse((self.package() / "src/nested/AGENTS.override.md").exists())

    def test_environment_provider_model_and_effort_override(self):
        self.env["PR_REVIEW_PROVIDER"] = "openai"
        result = self.run_review("--model", "custom-model", "--effort", "xhigh")
        self.assertEqual(result.returncode, 0, result.stderr)
        args = self.capture()["args"]
        self.assertIn("custom-model", args)
        self.assertIn("model_reasoning_effort=xhigh", args)
        result = self.run_review("--provider", "anthropic")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.capture()["provider"], "claude")

    def test_failures_and_empty_results_are_not_reviews(self):
        for provider in ("anthropic", "openai"):
            for mode in ("fail", "empty"):
                with self.subTest(provider=provider, mode=mode):
                    self.env["PR_REVIEW_DIR"] = str(self.work / f"{provider}-{mode}")
                    self.env["MOCK_MODE"] = mode
                    copy = self.work / "do-not-overwrite.md"
                    copy.write_text("previous review")
                    result = self.run_review("--provider", provider, "--out", str(copy))
                    self.assertEqual(result.returncode, 1, result.stderr)
                    package = next(Path(self.env["PR_REVIEW_DIR"]).iterdir())
                    self.assertFalse((package / "REVIEW.md").exists())
                    self.assertTrue((package / "REVIEW.failed.txt").exists())
                    self.assertEqual(copy.read_text(), "previous review")

    def test_parallel_test_failure_is_appended(self):
        hook = self.work / "hook.sh"
        hook.write_text('pr_review_test() { echo "test failure evidence"; return 3; }\n')
        result = self.run_review("--provider", "openai", "--parallel", "--hook", str(hook), tests=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        review = (self.package() / "REVIEW.md").read_text()
        self.assertTrue(review.startswith(VERDICT))
        self.assertIn("exit 3", review)
        self.assertIn("test failure evidence", review)
        self.assertIn("still running in parallel", self.capture()["prompt"])

    def test_package_only_does_not_invoke_reviewer(self):
        self.env["MOCK_MODE"] = "fail"
        result = self.run_review("--provider", "openai", "--no-review")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.work / "capture.json").exists())
        self.assertFalse((self.package() / "REVIEW.md").exists())

    def test_invalid_provider_fails_before_packaging(self):
        result = self.run_review("--provider", "unknown")
        self.assertEqual(result.returncode, 2)
        self.assertIn("unknown provider", result.stderr)
        self.assertFalse((self.work / "packages").exists())

    def test_missing_selected_cli_fails_before_packaging(self):
        self.env["PATH"] = str(self.work / "empty-bin")
        result = self.run_review("--provider", "openai")
        self.assertEqual(result.returncode, 2)
        self.assertIn("codex CLI not found", result.stderr)
        self.assertFalse((self.work / "packages").exists())

    def test_explicit_head_and_coderabbit(self):
        cli = self.bin / "coderabbit"
        cli.write_text('#!/bin/sh\nprintf "Review complete\\nNo findings\\n"\n')
        cli.chmod(0o755)
        self.git("branch", "review-target")
        self.git("checkout", "-q", "base")
        result = self.run_review("--provider", "openai", "--head", "review-target", "--coderabbit")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.package() / "src/code.txt").read_text(), "after\n")
        review = (self.package() / "REVIEW.md").read_text()
        self.assertTrue(review.startswith(VERDICT))
        self.assertIn("## CodeRabbit CLI", review)
        self.assertIn("No findings", review)


if __name__ == "__main__":
    unittest.main()
