---
name: process-ticket
description: Implement a ticket from this English-learning application, following its requirements, design decisions, OpenAI API policy, and per-ticket integration/E2E test process.
metadata:
  short-description: Process an application ticket end to end
---

# Process an application ticket

Use this skill when the user asks to implement, continue, or review a development ticket in this repository. Work within the ticket's scope and leave an auditable result in the ticket file.

Every software development request in this repository must have a ticket before implementation, regardless of size. Create and index a new ticket first, or continue the existing ticket when the request belongs to its scope. Do not make development edits before the ticket and open-ticket index are marked In Progress, unless the user explicitly asks to bypass ticketing.

## Create a ticket

- When asked to create a ticket, copy `docs/tickets/TEMPLATE.md` to the next available `docs/tickets/T-XXX.md`; never start from a blank file.
- Replace every placeholder. Describe observable outcomes, explicit scope, requirement IDs/dependencies, and relevant edge or regression cases.
- Select unit, integration, E2E, and other validation layers individually. For each N/A layer, state why it does not apply. Define isolated synthetic fixtures and expected coverage; never point tests at production data or paid APIs.
- Add the ticket to `docs/tickets/README.md` with priority, dependencies, and initial status. Do not mark it complete until implementation and evidence exist.

## Before changing code

1. Find the repository root and read `docs/README.md`, `docs/tickets/README.md`, the requested ticket, and `docs/testing.md`.
2. Read `docs/requirements.md` sections matching the ticket's requirement IDs. Read the related design documents linked from the docs index. For data work, read `docs/data-model.md`; for keyboard/UI work, read `docs/interaction.md`; for API-backed work, read `docs/openai-api-policy.md` and use the available OpenAI Docs skill to verify current official API guidance before implementation.
3. Read prerequisite tickets' decisions and the relevant code/data before editing. Treat existing user changes as theirs: inspect `git status`, avoid overwriting unrelated changes, and do not reset or clean the worktree.
4. Confirm the ticket is unblocked. If the user named no ticket, choose the first unblocked ticket in roadmap order, state that choice in a progress update, and proceed.
5. Set the ticket and index to `作業中` before implementation. Open ticket files live in `docs/tickets/`; completed ticket files live in `docs/tickets/done/`. Keep scope to this ticket unless the user asks to continue through dependencies. If actual requirements conflict or a material decision is unresolved, do independent work first and ask only about the blocking decision.

## Implement and verify

- Implement all acceptance criteria, not only a demonstration path. Update requirements or design docs when the implementation reveals a necessary decision.
- Follow `docs/testing.md`. Use isolated synthetic fixtures and temporary databases/files. Never let automated tests read or mutate `dataset/vocab.db` or `practice_data`, and do not call paid OpenAI APIs from tests. Replace the API boundary with deterministic fixtures.
- For every feature ticket, run relevant unit tests and integration tests. For changes users perform through the interface, run E2E tests that cover the ticket's acceptance path and check important regression paths. If a layer genuinely does not apply, record why. A test that cannot be run is not a passing result.
- If test infrastructure does not yet exist, implement the prerequisite testing ticket or add the smallest reusable fixture/runner needed; do not silently replace an expected integration/E2E test with manual inspection.
- Run the repo's documented test command(s), plus targeted checks for changed code. Record exact commands, pass/fail, fixture names, and any unverified criteria. Keep network-dependent manual API checks separate and report any cost.
- For UI work, check both mouse and keyboard usage where relevant. Preserve the configured multiple-key behavior and avoid shortcut capture in editable controls.
- Treat the acceptance checklist as the completion gate: each item needs implementation evidence and the planned validation result. If a check is blocked or not applicable, record the reason and leave the ticket open when an acceptance criterion remains unverified.
- When a preventable process failure recurs, capture the smallest durable prevention: amend the relevant existing instruction, add a reusable procedure, or add an automated check. Avoid duplicating rules in multiple documents; link to the canonical owner.
- Keep repository instructions and skills concise. Put durable repository-wide constraints in `AGENTS.md`, the repeatable ticket workflow here, test policy in `docs/testing.md`, and task-specific outcomes in tickets. Review the existing source before adding another rule.

## Finish the ticket

1. Review the diff for unrelated changes, secrets, accidental edits to datasets, and mismatches with acceptance criteria.
2. Update the ticket's implementation, test results, remaining limitations, and each acceptance checkbox.
3. Only when every criterion is met and required tests pass, mark the ticket `完了`, move its file from `docs/tickets/T-XXX.md` to `docs/tickets/done/T-XXX.md`, remove it from the open-ticket table in `docs/tickets/README.md`, and add/update its link and completion date in `docs/tickets/done/README.md`. Adjust relative links after moving it. Otherwise leave it `作業中` or `確認待ち` with a concrete next step.
4. Commit each ticket implementation, tests, ticket-file move, index updates, and a changelog summary together as one ticket-scoped commit. After the commit, record its resulting hash in the changelog in a documentation follow-up, since a commit cannot contain its own final hash. Summarize what changed, checks run, and remaining work to the user. Do not claim unrun tests passed.

## Project references

- Ticket status and dependencies: `docs/tickets/README.md`
- Requirements and acceptance criteria: `docs/requirements.md`
- Test layers and fixtures: `docs/testing.md`
- Data compatibility and schema: `docs/data-model.md`
- Current OpenAI API selection: `docs/openai-api-policy.md`
- Mouse and keyboard interaction: `docs/interaction.md`
- New-ticket template: `docs/tickets/TEMPLATE.md`
