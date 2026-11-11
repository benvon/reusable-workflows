"""Disposable, local-only Git remotes for release allocator tests."""

import os
from pathlib import Path
import subprocess


class ReleaseRepository:
    def __init__(self, root):
        self.root = Path(root)
        self.remote = self.root / "origin.git"
        self.seed = self.root / "seed"
        self.env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
        self.git("init", "--bare", "-q", str(self.remote), cwd=self.root)
        self.git("init", "-q", "--initial-branch=main", str(self.seed), cwd=self.root)
        self.git("remote", "add", "origin", str(self.remote))
        self.tree = self.git("mktree", input="")
        self.tip = None

    def git(self, *args, cwd=None, input=None):
        return subprocess.check_output(
            ["git", *args], cwd=cwd or self.seed, env=self.env,
            input=input, text=True, stderr=subprocess.PIPE,
        ).strip()

    def commit(self, name, parent=None, branch="main"):
        # Construct fixture objects without invoking user signing tools or hooks.
        contents = f"tree {self.tree}\n"
        if parent:
            contents += f"parent {parent}\n"
        contents += ("author Fixture <fixture@example.invalid> 1 +0000\n"
                     "committer Fixture <fixture@example.invalid> 1 +0000\n\n" + name + "\n")
        sha = self.git("hash-object", "-w", "-t", "commit", "--stdin", input=contents)
        self.git("update-ref", f"refs/heads/{branch}", sha)
        self.git("push", "--quiet", "origin", f"{sha}:refs/heads/{branch}")
        self.tip = sha
        return sha

    def tag(self, name, sha, annotated=False):
        if annotated:
            sha = self.git("mktag", input=(
                f"object {sha}\ntype commit\ntag {name}\n"
                "tagger Fixture <fixture@example.invalid> 1 +0000\n\nFixture tag\n"))
        self.git("push", "--quiet", "origin", f"{sha}:refs/tags/{name}")

    def worker(self, name="worker"):
        directory = self.root / name
        self.git("clone", "--quiet", "--no-checkout", "--branch", "main",
                 str(self.remote), str(directory), cwd=self.root)
        return directory

    def allocate(self, script, worker, target, bump="patch"):
        output = worker / "step-output"
        output.write_text("")
        result = subprocess.run(
            ["bash", "-e", "-o", "pipefail", "-c", script],
            cwd=worker, text=True, capture_output=True,
            env={**self.env, "RELEASE_SHA": target, "RELEASE_BUMP": bump,
                 "RELEASE_SOURCE": "fixture", "GITHUB_OUTPUT": str(output),
                 "GITHUB_STEP_SUMMARY": str(worker / "step-summary")},
        )
        values = dict(line.split("=", 1) for line in output.read_text().splitlines())
        return result, values

    def inject_competing_tag(self, worker, target, *, repeat=False):
        hook = worker / ".git/hooks/pre-push"
        hook.write_text(
            "#!/usr/bin/env python3\n"
            "import pathlib, subprocess, sys\n"
            "for line in sys.stdin:\n"
            "    _, _, ref, _ = line.split()\n"
            f"    subprocess.run(['git', '--git-dir', {str(self.remote)!r}, "
            f"'update-ref', ref, {target!r}], check=True)\n"
            "count = pathlib.Path(__file__).with_name('attempts')\n"
            "count.write_text(count.read_text() + 'push\\n' if count.exists() else 'push\\n')\n"
            + ("" if repeat else "pathlib.Path(__file__).unlink()\n")
        )
        hook.chmod(0o755)
