"""Exercise the allocator against real local Git remotes and conflicting pushes."""

import tempfile
import unittest

from git_fixtures import ReleaseRepository
from test_release_workflows import workflow


class AllocationTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.repo = ReleaseRepository(directory)
        self.baseline = self.repo.commit("baseline")
        self.target = self.repo.commit("target", parent=self.baseline)
        self.script = next(step["run"] for step in workflow("release-tag.yml")["jobs"]["release-tag"]["steps"]
                           if step.get("id") == "version")

    def allocate(self, bump="patch", worker=None, target=None):
        result, values = self.repo.allocate(self.script, worker or self.repo.worker(), target or self.target, bump)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        refs = self.repo.git("for-each-ref", "--format=%(refname)", "refs/tags/", cwd=self.repo.remote)
        self.assertIn(f"refs/tags/{values['tag']}", refs.splitlines())
        self.assertEqual(self.repo.git("rev-parse", f"refs/tags/{values['tag']}^{{commit}}",
                                       cwd=self.repo.remote), target or self.target)
        return values

    def test_initial_patch_version(self):
        self.assertEqual(self.allocate(), {"tag": "v0.0.1", "created": "true"})

    def test_initial_minor_version(self):
        self.assertEqual(self.allocate("minor"), {"tag": "v0.1.0", "created": "true"})

    def test_initial_major_version(self):
        self.assertEqual(self.allocate("major"), {"tag": "v1.0.0", "created": "true"})

    def test_non_versions_prereleases_and_metadata_do_not_change_the_stable_baseline(self):
        for name in ("vnext", "v2", "v01.2.3", "v9.0.0-rc.1", "v8.0.0+build.1", "v1.2.3"):
            self.repo.tag(name, self.baseline)
        self.assertEqual(self.allocate(), {"tag": "v1.2.4", "created": "true"})

    def test_aliases_and_prereleases_on_target_do_not_count_as_a_completed_release(self):
        self.repo.tag("v1.2.3", self.baseline)
        for name in ("vnext", "v1", "v1.3.0-rc.1", "v1.3.0+build.1"):
            self.repo.tag(name, self.target)
        self.assertEqual(self.allocate(), {"tag": "v1.2.4", "created": "true"})

    def test_annotated_stable_tag_is_reused_without_a_second_version(self):
        self.repo.tag("v1.2.3", self.target, annotated=True)
        self.assertEqual(self.allocate(), {"tag": "v1.2.3", "created": "false"})

    def test_versions_sort_numerically_and_use_the_repository_wide_namespace(self):
        self.repo.tag("v1.9.9", self.baseline)
        unrelated = self.repo.commit("unrelated history", branch="maintenance")
        self.repo.tag("v1.10.0", unrelated)
        self.assertEqual(self.allocate(), {"tag": "v1.10.1", "created": "true"})

    def test_two_merges_manual_release_and_reruns_preserve_all_versions(self):
        self.repo.tag("v1.2.3", self.baseline)
        second = self.repo.commit("second merge", parent=self.target)
        manual = self.repo.commit("manual target", parent=second)
        # Both waiting jobs have a stale checkout before the first tag is pushed.
        first_worker, second_worker = self.repo.worker("first"), self.repo.worker("second")
        self.assertEqual(self.allocate(worker=first_worker)["tag"], "v1.2.4")
        self.assertEqual(self.allocate("minor", second_worker, second)["tag"], "v1.3.0")
        self.assertEqual(self.allocate("major", self.repo.worker("manual"), manual)["tag"], "v2.0.0")
        self.assertEqual(self.allocate(worker=first_worker), {"tag": "v1.2.4", "created": "false"})
        self.assertEqual(self.allocate("minor", second_worker, second), {"tag": "v1.3.0", "created": "false"})

    def test_conflicting_push_refreshes_tags_and_recomputes(self):
        self.repo.tag("v1.2.3", self.baseline)
        worker = self.repo.worker()
        self.repo.inject_competing_tag(worker, self.baseline)
        self.assertEqual(self.allocate(worker=worker), {"tag": "v1.2.5", "created": "true"})
        self.assertEqual(self.repo.git("rev-parse", "refs/tags/v1.2.4", cwd=self.repo.remote), self.baseline)

    def test_same_sha_winning_a_race_is_reused(self):
        self.repo.tag("v1.2.3", self.baseline)
        worker = self.repo.worker()
        self.repo.inject_competing_tag(worker, self.target)
        self.assertEqual(self.allocate(worker=worker), {"tag": "v1.2.4", "created": "false"})

    def test_repeated_conflicts_stop_without_success_outputs(self):
        self.repo.tag("v1.2.3", self.baseline)
        worker = self.repo.worker()
        self.repo.inject_competing_tag(worker, self.baseline, repeat=True)
        result, values = self.repo.allocate(self.script, worker, self.target)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(values, {})
        self.assertEqual((worker / ".git/hooks/attempts").read_text().splitlines(), ["push"] * 5)

    def test_non_conflict_push_failure_is_reported_without_retry(self):
        worker = self.repo.worker()
        hook = worker / ".git/hooks/pre-push"
        hook.write_text("#!/bin/sh\necho rejected >&2\nexit 1\n")
        hook.chmod(0o755)
        result, values = self.repo.allocate(self.script, worker, self.target)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("rejected", result.stderr)
        self.assertEqual(values, {})


class QueueContractTests(unittest.TestCase):
    def test_all_automatic_and_manual_taggers_share_a_non_cancelling_queue(self):
        job = workflow("release-tag.yml")["jobs"]["release-tag"]
        self.assertIn("concurrency", job)
        self.assertEqual(job["concurrency"], {
            "group": "reusable-release-tags", "cancel-in-progress": "false", "queue": "max",
        })
        # No outer queue with the same group: nesting would deadlock this job.
        self.assertNotIn("concurrency", workflow("repo-release-tag.yml"))


if __name__ == "__main__":
    unittest.main()
