<!--
Sync Impact Report
- Version change: template (unversioned) → 1.0.0
- Rationale: first ratification; all placeholder principles replaced with the
  10 subtracker statement-import principles supplied verbatim by the team.
- Modified principles: [PRINCIPLE_1..5_NAME] → I..X (see below); template had 5 slots,
  the project defines 10.
- Added sections: none beyond template structure (Core Principles, Additional
  Constraints, Development Workflow, Governance).
- Removed sections: none.
- Deferred TODOs: none.
- This comment is scratch material for amendment review and should be deleted
  before committing the amended file.
-->
# subtracker Constitution

## Core Principles

### I. Specification Describes Behavior, Not Implementation
A specification MUST NOT name classes, files, modules or libraries. Frameworks and code
structure are decided in the plan phase. Rationale: the same spec must survive a change of
stack, and two teams must be able to agree on behavior without agreeing on code.

### II. Every Requirement Is Verifiable
A statement that cannot be turned into a test MUST NOT enter the spec. The words "fast",
"convenient" and "clear" are forbidden; numbers and conditions replace them. Rationale: an
unverifiable requirement cannot be accepted or rejected, so it silently becomes optional.

### III. Boundaries And Errors Are Requirements
For every scenario the spec MUST state the behavior on empty input, oversized input,
partially invalid input and fully invalid input. These cases are not footnotes. Rationale:
failure paths are where imports actually break.

### IV. Money Is Decimal With Two Digits, Never Floating Point
Monetary values are decimal, rounded to 2 digits, and are written as strings in the spec and
in API examples. Rationale: binary floating point cannot represent amounts exactly, and
rounding drift in a money tracker is a correctness bug.

### V. A User Sees Only Their Own Data
Every scenario that involves data MUST state whose data it is. Reads and writes are scoped to
the owner; another owner's object MUST be indistinguishable from a nonexistent one.

### VI. Two Languages, ru And en
Every text a user can see MUST exist in both ru and en. A server response therefore carries a
stable machine code rather than prose intended for display.

### VII. Nothing Is Stored Without Explicit User Confirmation
Import MUST NOT create subscriptions by itself. Analysis of a statement is a proposal;
persistence of subscriptions happens only on an explicit confirming action by the owner.

### VIII. Assumptions About Another Team's Scope Are Labeled Assumptions
What is taken for granted without confirmation MUST appear in a dedicated Assumptions
section, never as a requirement. Rationale: a disguised assumption is discovered at
integration time instead of at the agreement meeting.

### IX. The Existing Subscription Model And API Do Not Change
The existing subscription fields and the existing endpoints MUST remain as they are unless the
spec contains a separate written justification for the change.

### X. Declared Out Of Scope
Bank APIs, OCR, PDF, mail import, background queues, notifications and Pro-plan features are
out of scope. A requirement that depends on any of them MUST be rejected or restated.

## Additional Constraints

- Money: decimal only, 2 digits, never floating point (Principle IV).
- User isolation: owner-scoped access everywhere (Principle V).
- All user-visible text is served through the ru/en translation dictionary (Principle VI).
- Database schema changes happen through migrations only.
- Every new endpoint ships with a test.

## Development Workflow

1. Constitution is agreed first and is identical for all teams working on the feature.
2. Each team writes its half of the specification independently; cross-team gaps are recorded
   as explicit requirements on the other side plus labeled assumptions.
3. Teams reconcile the two specifications at an agreement meeting; assumptions are the agenda.
4. Planning and implementation start only after the reconciled spec passes its quality
   checklist.

## Governance

This constitution supersedes conflicting practice for the statement-import feature. Amendments
require a written proposal naming the principle changed, the reason, and the migration impact,
and take effect once recorded here with a version bump.

Versioning policy: MAJOR for a removed or redefined principle, MINOR for a new or materially
expanded principle, PATCH for clarification and wording.

Compliance: every specification, plan and review MUST be checkable against these principles;
a spec that violates one is rejected or carries an explicit justification in its own text.

**Version**: 1.0.0 | **Ratified**: 2026-10-29 | **Last Amended**: 2026-10-29
