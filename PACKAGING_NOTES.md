# Packaging notes — runreckon (PyPI readiness)

Date: 2026-11-16. Local work only — nothing pushed to GitHub, nothing
uploaded to PyPI.

## PyPI name availability

- `GET https://pypi.org/pypi/runreckon/json` → **404 Not Found — name is free**
  (checked 2026-11-16). Variant `run-reckon` also 404.
- No PyPI token exists on this machine (no `~/.pypirc`, no TWINE_*/PyPI
  env vars), so no upload was attempted.

## pyproject.toml state

**Already good — no changes made.** Pre-existing file already had:
name `runreckon`, version `0.1.0`, description, `readme = "README.md"`,
`requires-python = ">=3.10"`, MIT license, author, keywords/classifiers,
zero dependencies, console entry point `runreckon = "runreckon.cli:main"`
(src layout, `src/runreckon/cli.py` has `main()`), project URL, package
find under `src/`, and package-data for the bundled examples.
Build emits a non-blocking setuptools warning that the table form of
`project.license` is deprecated in favour of an SPDX string — builds and
`twine check` pass today; migrate before the 2027-02-18 setuptools cutoff.

## Build artifacts (in `dist/`)

Built with a scratch venv outside the repo
(`~/workspace/.scratch-pkgbuild/pkgbuild-venv`, `build` 1.6.1):

```
python -m build   # exit 0
dist/runreckon-0.1.0.tar.gz            (sdist, ~36 KB)
dist/runreckon-0.1.0-py3-none-any.whl  (wheel, ~34 KB)
twine check dist/*  → PASSED for both artifacts, exit 0
```

`dist/` is already covered by the repo `.gitignore`.

## Clean-venv proof (packaged form, no repo on sys.path)

```
python3 -m venv ~/workspace/.scratch-pkgbuild/test-runreckon-venv
test-runreckon-venv/bin/pip install dist/runreckon-0.1.0-py3-none-any.whl   # exit 0
# from neutral cwd /tmp/neutral-rr:
runreckon --help     # exit 0 — argparse help, subcommands score/demo/selftest/version
runreckon version    # exit 0 — prints 0.1.0
runreckon selftest   # exit 0 — 18/18 planted defects caught, 3/3 controls pass
runreckon demo       # exit 1 BY DESIGN — returns worst example exit code;
                     # the policy-breach example is supposed to fail
python -c "import runreckon, runreckon.cli"   # exit 0, version 0.1.0
```

## Repo harness

```
cd ~/workspace/runreckon && python3 validate.py   # OVERALL PASS, exit 0
# 6/6 stages: import/compile, 63 unit tests, examples, self-test
# reproduction, reference-integrity scan, banned-name check
```

## Reference-integrity scan

The pyproject was scanned with the portfolio reference-integrity
scanner (its path is assembled at runtime in `validate.py`, so it is
not spelled out here): 0 candidate hits — clean. `validate.py`'s own
reference-integrity stage likewise reports 0 candidates, 0 judged
real, with this file present.

## Publish (one step, once Ranadhir creates a PyPI API token)

Create a token at https://pypi.org/manage/account/token/ (scope: this
project, once the project exists use a project-scoped token), then:

```bash
cd ~/workspace/runreckon
TWINE_USERNAME=__token__ TWINE_PASSWORD='pypi-<your-token>' \
  ~/workspace/.scratch-pkgbuild/pkgbuild-venv/bin/twine upload dist/*
```

Equivalent: `python3 -m twine upload dist/*` and answer username
`__token__` / password = the token. Upload the 0.1.0 artifacts above, or
rebuild first with `python -m build` if anything changes.
