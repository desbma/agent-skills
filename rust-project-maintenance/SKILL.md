---
name: rust-project-maintenance
description: Execute Rust project maintenance around dependencies, clippy lints lists, etc.
disable-model-invocation: true
---

# Rust project maintenance

This file describes how to run a set of maintenance operations common to several Rust projects.

## Scope

Maintenance can be done according to 3 different scopes:

- _light_: doing only a quick, minimal set of tasks
- _standard_: doing a common set of tasks
- _complete_: doing a full, thorough set of tasks, typically before a release

Decide the scope according to the user's request formulation. If unsure, default to the _standard_ scope.

## Workflow

Execute each task in order.
If a task is skipped, or requires no change to the code after being analyzed, simply continue to the next one.
If a task has required some code changes, pause before executing the next task, show a _progress report_ as shown below, followed by a short description of your last changes, and wait for the user to review your work and signal you can continue.
Once all tasks are done, show a final _progress report_.

### Progress report

Show a status output for the user, with number of tasks already executed or skipped, the total number of tasks, and the status for each task ("done", "skipped", "review", "pending"). Tasks that required no action are considered "done", tasks waiting for user approval to continue are in "review" state.

Follow the output format of the content of this code block:

```text
Maintenance tasks (3/4):
1. ☑ AGENTS.md update [DONE]
2. ☑ Dependencies compatible update [SKIPPED]
3. ☑ Cargo audit [REVIEW]
4. ☐ Clippy lint list update
```

Note that `[PENDING]` is omitted for pending tasks.

## Task list

Before starting your work, check that the current repository is a Rust project, and if not says so to the user, it is likely an error.
The list of tasks to execute for each scope follows. Refer to the task definition part for detailed instructions for each task.

### _Light_ scope

- Pre commit hook removal
- AGENTS.md update
- Cargo audit
- Clippy lint list update

### _Standard_ scope

- Pre commit hook removal
- AGENTS.md update
- Dependencies compatible update
- Cargo audit
- Clippy lint list update
- MSRV check

### _Complete_ scope

- Pre commit hook removal
- AGENTS.md update
- Dependencies breaking update
- Cargo audit
- Clippy lint list update
- MSRV check
- GitHub actions update
- Changelog template update
- Release script update

## Task definition

### Pre commit hook removal

Pre-commit files:

- `.git/hooks/pre-commit`
- `.pre-commit-config.yaml`

Skip this task if none of these files exist, remove them if they do.

### AGENTS.md update

Skip this task if the current project has no `AGENTS.md` file in the root directory.

Compare the current repository `AGENTS.md` file with the reference template at `https://github.com/desbma/cargo-template/blob/master/AGENTS.md`. The goal is to copy relevant points from the reference to the local file. Do not blindly copy the content, follow these rules:

- if a bullet point from the "Code Style" part is present in the reference, but not in the local file, add it locally
- if a bullet point from the "Code Style" part is present in the reference, and overlaps with the meaning of a rule in the local file, keep the most restrictive one
- ignore difference that can be explained by local project specifics (ie. MSRV, workspace with multiple packages...)
- if a command from the "Build & Test" part, seems more thorough in the reference than in the local file (ie. runs Clippy or tests with more features, passes more flags to `cargo fmt`...), **and** it makes sense to use such command locally (for example it is not needed to run `cargo test --all-features` if local project has no features), then replace it locally
- once done updating `AGENTS.md`, run build, check and formatting commands, and fix any surfacing issues

### Dependencies compatible update

Run:

```bash
cargo upgrade
cargo update
cargo check
```

Fix any compilation errors reported by `cargo check`. If the project supports different feature combination or platforms (check this by looking for example at the CI jobs), run `cargo check` for all configurations you can, for example `cargo check --target x86_64-pc-windows-gnu --features foo`. Then run the project's other test/lint/format commands, if any, and fix errors that surface.

### Dependencies breaking update

Run the _Dependencies compatible update_ task, by using `cargo upgrade -i`, and follow the same checks.
You will likely need to so some adjustments to the code to accommodate for the breaking changes.

### Cargo audit

Run `cargo audit` and fix all reported warnings:

- replace abandoned dependencies by mature and maintained ones, similar in scope
- consider the recommended actions for security issues (version bump, feature to disable...)

### Clippy lint list update

Compare the current Clippy configuration from `lint.*` or `workspace.lint.*` sections in `Cargo.toml` file with the reference template at `https://github.com/desbma/cargo-template/blob/master/Cargo.toml`.
Copy the reference lint configuration locally, including comments, but respect lints that were intentionally disabled:

- by being already present in the list commented out
- by being set to `allow` (leave such lines)

Also copy the `https://github.com/desbma/cargo-template/blob/master/clippy.toml` reference file locally if it is missing or less complete than the reference.

Then run Clippy on the local project, covering all code (including tests and features not enabled by default), and fix any warning that surface, either by running `cargo fix`, by updating the code to fix the root cause, or by ignoring it locally.

### MSRV check

Skip this task if the current project has no `package.rust-version` attribute set in `Cargo.toml`.

Run `cargo msrv verify`. Update reported MSRV if it is incorrect, using `cargo msrv` to find the correct value.

### GitHub actions update

Skip this task if the local repository does not have GitHub actions files.

Steps :

- for each workflow in `https://github.com/desbma/cargo-template/tree/master/.github/workflows`, if it exists locally, compare them and consider updating the local version:
  - if a job exists in the reference action, but does not make sense locally (MSRV check when we don't declare one locally) => ignore it
  - for the `release` workflow, only update jobs existing locally, do not add new ones
  - do not make changes that affect the output (ie. compilation toolchains, library packages installed), as it is highly project specific
  - ignore the `untemplate` line noise, it is an artifact of the `cargo-generate` use
  - if a check is in the reference action, and not in the local one, or is more thorough in the reference (ie. runs Clippy on test code and we have tests) **and** it makes sense to use such command locally (for example it is not needed to run `cargo test --all-features` if local project has no features) => add it
- run `pinact run -u -min-age 10` to update GitHub actions versions, and pin it with hashes

### Changelog template update

Skip this task if the current project has no `CHANGELOG.md` file in the root directory.

Compare the current Git Cliff configuration from the `cliff.toml` file with the reference template at `https://github.com/desbma/cargo-template/blob/master/cliff.toml`. Update the local version, ignoring obviously local-specific elements like project URL, or changelog header.

### Release script update

Skip this task if the current project has no `release` script in the root directory.

Compare the current `release` script file with the reference template at `https://github.com/desbma/cargo-template/blob/master/release`. Update the local version, ignoring obviously local-specific elements like:

- changelog update if we have no changelog locally
- different base version for the changelog
- different version convention (ie. CalVer vs SemVer)
- beta version naming replacements if we have no beta version locally
