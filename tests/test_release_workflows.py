"""Regression checks for the release handoff, publisher, and required lint gate."""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

import yaml

from git_fixtures import ReleaseRepository


ROOT = Path(__file__).resolve().parents[1]


def workflow(name):
    # BaseLoader preserves the Actions `on` key rather than treating it as YAML 1.1 true.
    return yaml.load((ROOT / ".github/workflows" / name).read_text(), Loader=yaml.BaseLoader)


def resolve_output(expression, context):
    """Resolve a direct output reference at the workflow's public boundary."""
    match = re.fullmatch(r"\$\{\{\s*([\w.-]+)\s*\}\}", expression)
    if not match:
        raise AssertionError(f"Expected a direct output reference: {expression}")
    value = context
    for part in match[1].split("."):
        value = value[part]
    return value


def release_tag(data, inputs, ref_name):
    """Resolve the publisher's input-or-event fallback for either entry point."""
    expression = data["jobs"]["publish-release"]["steps"][0]["env"]["RELEASE_TAG"]
    terms = expression.removeprefix("${{").removesuffix("}}").strip().split(" || ")
    context = {"inputs": inputs, "github": {"ref_name": ref_name}}
    for term in terms:
        value = resolve_output("${{ " + term + " }}", context)
        if value:
            return value
    return ""


def run_script(script, fixture, env=None):
    """Execute actual github-script code; replace only the remote GitHub API."""
    harness = r"""
const fs = require('node:fs');
const { script, fixture } = JSON.parse(fs.readFileSync(0, 'utf8'));
const AsyncFunction = Object.getPrototypeOf(async function() {}).constructor;
const outputs = {}, calls = [], errors = [];
const context = { repo: { owner: 'example', repo: 'caller' } };
let release = fixture.existing ? { id: 1, html_url: 'https://example.test/release' } : null;
const apiError = status => Object.assign(new Error(`API status ${status}`), { status });
const github = { rest: {
  git: { getRef: async args => {
    calls.push(['getRef', args]);
    if (fixture.tagStatus) throw apiError(fixture.tagStatus);
    return { data: { ref: 'refs/tags/v1.2.4' } };
  } },
  repos: {
    listPullRequestsAssociatedWithCommit: async () => ({ data: fixture.prs || [] }),
    getReleaseByTag: async args => {
      calls.push(['getReleaseByTag', args]);
      if (fixture.releaseStatus) throw apiError(fixture.releaseStatus);
      if (!release) throw apiError(404);
      return { data: release };
    },
    createRelease: async args => {
      calls.push(['createRelease', args]);
      if (fixture.createStatus) throw apiError(fixture.createStatus);
      release = { id: 1, html_url: 'https://example.test/release', tag_name: args.tag_name };
      return { data: release };
    },
  },
} };
const core = {
  notice: () => {}, info: () => {},
  setOutput: (key, value) => { outputs[key] = value; },
  setFailed: message => { errors.push(message); },
};
(async () => {
  for (let i = 0; i < (fixture.runs || 1); i++) {
    try { await new AsyncFunction('github', 'context', 'core', script)(github, context, core); }
    catch (error) { errors.push(error.message); }
  }
  process.stdout.write(JSON.stringify({ outputs, calls, errors, release }));
})();
"""
    result = subprocess.run(
        ["node", "-e", harness],
        input=json.dumps({"script": script, "fixture": fixture}),
        text=True, capture_output=True, check=True,
        env={**os.environ, **(env or {})},
    )
    return json.loads(result.stdout)


class ReleaseHandoffTests(unittest.TestCase):
    def test_release_and_retry_expose_the_same_tag_and_target(self):
        data = workflow("release-tag.yml")
        public = data["on"]["workflow_call"].get("outputs", {})
        self.assertTrue({"should_release", "tag", "sha", "created"} <= public.keys())
        job = data["jobs"]["release-tag"]
        version = next(step for step in job["steps"] if step.get("id") == "version")
        signal = next(step for step in job["steps"] if step.get("id") == "signal")
        result = run_script(signal["with"]["script"], {
            "prs": [{"number": 42, "title": "fix: example", "merged_at": "2026-11-11",
                     "base": {"ref": "main"}, "labels": [{"name": "release:patch"}]}],
        }, {"CALLER_EVENT_NAME": "push", "CALLER_SHA": "target", "BASE_BRANCH": "main"})
        self.assertEqual(result["errors"], [])
        with tempfile.TemporaryDirectory() as directory:
            repo = ReleaseRepository(directory)
            baseline = repo.commit("baseline")
            target = repo.commit("target", parent=baseline)
            repo.tag("v1.2.3", baseline)
            worker = repo.worker()
            for created in ("true", "false"):
                allocation, values = repo.allocate(version["run"], worker, target)
                self.assertEqual(allocation.returncode, 0, allocation.stderr)
                context = {"steps": {"signal": {"outputs": result["outputs"]},
                                     "version": {"outputs": values}}, "inputs": {"caller_sha": target}}
                job_values = {key: resolve_output(value, context) for key, value in job["outputs"].items()}
                exposed = {key: resolve_output(value["value"], {"jobs": {"release-tag": {"outputs": job_values}}})
                           for key, value in public.items()}
                self.assertEqual(exposed, {"should_release": "true", "tag": "v1.2.4",
                                          "sha": target, "created": created})

    def test_skip_signal_prevents_dependent_publication(self):
        tagger = workflow("release-tag.yml")["jobs"]["release-tag"]
        signal = next(step for step in tagger["steps"] if step.get("id") == "signal")
        result = run_script(signal["with"]["script"], {
            "prs": [{"number": 42, "merged_at": "2026-11-11", "base": {"ref": "main"},
                     "labels": [{"name": "release:skip"}]}],
        }, {"CALLER_EVENT_NAME": "push", "CALLER_SHA": "target", "BASE_BRANCH": "main"})
        self.assertEqual(result["outputs"]["should_release"], "false")
        caller = workflow("repo-release-tag.yml")["jobs"]
        self.assertIn("publish-release", caller)
        publish = caller["publish-release"]
        self.assertEqual(publish["needs"], "release-tag")
        self.assertEqual(publish["uses"], "./.github/workflows/repo-publish-release.yml")
        # Validate the job boundary: both new and reused tags must publish, skip must not.
        self.assertEqual(publish["if"], "needs.release-tag.outputs.should_release == 'true'")
        self.assertEqual(resolve_output(publish["with"]["release_tag"], {
            "needs": {"release-tag": {"outputs": {"tag": "v1.2.4"}}}}), "v1.2.4")


class PublisherTests(unittest.TestCase):
    def publish(self, *, direct_push=False, **fixture):
        data = workflow("repo-publish-release.yml")
        if direct_push:
            self.assertIn("v*", data["on"]["push"]["tags"])
            tag = release_tag(data, {"release_tag": ""}, "v1.2.4")
        else:
            self.assertEqual(data["on"]["workflow_call"]["inputs"]["release_tag"]["required"], "true")
            tag = release_tag(data, {"release_tag": "v1.2.4"}, "main")
        steps = data["jobs"]["publish-release"]["steps"]
        scripts = [step["with"]["script"] for step in steps if "github-script@" in step.get("uses", "")]
        self.assertEqual(len(scripts), 1, "Publisher must use an explicit API repository context")
        return run_script(scripts[0], fixture, {"RELEASE_TAG": tag})

    def test_direct_tag_push_publishes_the_event_tag(self):
        result = self.publish(direct_push=True)
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["release"]["tag_name"], "v1.2.4")

    def test_create_and_rerun_without_a_checkout(self):
        result = self.publish(runs=2)
        self.assertEqual(result["errors"], [])
        creates = [args for method, args in result["calls"] if method == "createRelease"]
        self.assertEqual(len(creates), 1)
        self.assertEqual(creates[0], {"owner": "example", "repo": "caller",
                                     "tag_name": "v1.2.4", "name": "v1.2.4",
                                     "generate_release_notes": True})
        refs = [args for method, args in result["calls"] if method == "getRef"]
        self.assertEqual(refs[0], {"owner": "example", "repo": "caller", "ref": "tags/v1.2.4"})

    def test_existing_release_is_a_successful_noop(self):
        result = self.publish(existing=True)
        self.assertEqual(result["errors"], [])
        self.assertNotIn("createRelease", [method for method, _ in result["calls"]])

    def test_api_failures_do_not_masquerade_as_missing_releases(self):
        for status in (401, 403, 429, 500):
            with self.subTest(status=status):
                result = self.publish(releaseStatus=status)
                self.assertEqual(result["errors"], [f"API status {status}"])
                self.assertNotIn("createRelease", [method for method, _ in result["calls"]])

    def test_missing_tag_or_failed_creation_fails_publication(self):
        result = self.publish(tagStatus=404)
        self.assertEqual(result["errors"], ["API status 404"])
        self.assertNotIn("createRelease", [method for method, _ in result["calls"]])
        result = self.publish(createStatus=403)
        self.assertEqual(result["errors"], ["API status 403"])


class LintGateTests(unittest.TestCase):
    def test_required_gate_rejects_workflow_and_shell_errors(self):
        step = next(step for step in workflow("repo-quality.yml")["jobs"]["quality"]["steps"]
                    if step["name"] == "Run actionlint")
        self.assertIn("run", step, "Run the linter directly so its exit status controls the gate")
        fixtures = {
            "valid": "on: push\njobs:\n  check:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo ok\n",
            "invalid-workflow": "on: push\njobs:\n  check:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v5\n        with:\n          unknown-input: true\n",
            "invalid-shell": "on: push\njobs:\n  check:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo $unused\n",
        }
        for name, settings in {
            "valid-queue": "queue: max\n  cancel-in-progress: false",
            "valid-single-queue": "queue: single\n  cancel-in-progress: true",
            "invalid-queue-value": "queue: typo",
            "invalid-queue-type": "queue: [max]",
            "invalid-cancelling-queue": "queue: max\n  cancel-in-progress: true",
            "invalid-concurrency-key": "queue: max\n  unexpected: true",
        }.items():
            fixtures[name] = "concurrency:\n  group: releases\n  " + settings + "\n" + fixtures["valid"]
        fixtures["invalid-job-queue"] = fixtures["valid"].replace(
            "    steps:", "    concurrency:\n      group: releases\n      queue: typo\n    steps:")
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run(["git", "init", "-q", directory], check=True)
            workflows = Path(directory) / ".github/workflows"
            workflows.mkdir(parents=True)
            if (ROOT / "scripts").exists():
                shutil.copytree(ROOT / "scripts", Path(directory) / "scripts")
            path = workflows / "fixture.yml"
            for name, contents in fixtures.items():
                with self.subTest(name=name):
                    path.write_text(contents)
                    result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", step["run"]],
                                            cwd=directory, capture_output=True, text=True)
                    self.assertEqual(result.returncode == 0, name.startswith("valid"), result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
