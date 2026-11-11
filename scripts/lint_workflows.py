"""Keep actionlint strict while validating its unsupported concurrency.queue field."""

from pathlib import Path
import subprocess
import sys

import yaml


# actionlint 1.7.12 does not yet implement GitHub's concurrency.queue syntax.
# https://github.com/rhysd/actionlint/issues/657
# Validate that field below before excluding only its unknown-key diagnostic.
QUEUE_DIAGNOSTIC = r'^unexpected key "queue" for "concurrency" section\.'


def main():
    paths = sorted(Path(".github/workflows").glob("*.yml"))
    paths += sorted(Path(".github/workflows").glob("*.yaml"))
    for path in paths:
        data = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
        if not isinstance(data, dict):
            continue  # actionlint diagnoses malformed workflow structures.
        scopes = [data]
        jobs = data.get("jobs", {})
        if isinstance(jobs, dict):
            scopes += [job for job in jobs.values() if isinstance(job, dict)]
        for scope in scopes:
            concurrency = scope.get("concurrency")
            if not isinstance(concurrency, dict) or "queue" not in concurrency:
                continue
            queue = concurrency["queue"]
            if queue not in ("single", "max"):
                sys.exit(f"{path}: concurrency.queue must be single or max")
            if queue == "max" and concurrency.get("cancel-in-progress", "false") != "false":
                sys.exit(f"{path}: queue: max requires cancel-in-progress to be omitted or literal false")
    return subprocess.call(["actionlint", "-ignore", QUEUE_DIAGNOSTIC])


if __name__ == "__main__":
    sys.exit(main())
