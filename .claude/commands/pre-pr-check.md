---
description: Run comprehensive pre-PR quality checklist for Webwatch
---

<!-- Adapted from https://github.com/matsengrp/plugins (MIT License) -->

# Pre-PR Quality Checklist

You are helping the user prepare code for a pull request by guiding them through a comprehensive quality checklist.

## Your Role

Guide the user through each step systematically. For each step:

1. Explain what needs to be done
2. Execute the required checks/commands
3. Report the results clearly
4. Only proceed to the next step after the current step passes or the user acknowledges issues

## Checklist Steps

### 1. Issue Compliance Verification (CRITICAL - Do This First!)

- Ask the user for the GitHub issue number they're working on (if applicable)
- Use `gh issue view <number>` to fetch the issue details
- Review ALL requirements in the issue and verify 100% completion
- If any requirement cannot be met, STOP and discuss with the user before proceeding

### 2. Code Quality Foundation

- Run `make quality` (format + lint + typecheck)
- Report any files modified or errors found
- If errors, STOP and require fixes before proceeding

### 3. Documentation, Architecture, and Implementation Reviews

**Documentation Review:**

- Use the Task tool with subagent_type="documentation-reviewer" on all new/modified code
- Check pattern compliance against `docs/*.md`, documentation gaps, clarity issues, update recommendations
- Report findings and wait for the user to address before continuing

**Design Compliance:**

- Confirm the implementation matches the intended design; cross-reference the relevant `docs/plans/` doc and confirm it was `agy`-reviewed

**Antipattern Scan:**

- Use the Task tool with subagent_type="antipattern-scanner" on all new/modified code
- Look for SRP violations, silent defaults, error-handling antipatterns, naming issues
- Report findings and wait for the user to address before continuing

**Clean Code Review:**

- Use the Task tool with subagent_type="clean-code-reviewer" on all new/modified code
- Check single responsibility, meaningful names, small functions, DRY
- Report findings and wait for the user to address before continuing

**Code Smell Detection:**

- Use the Task tool with subagent_type="code-smell-detector" on all new/modified code
- Identify maintainability hints and readability improvements
- Report findings for the user's consideration

### 4. Extraction & Notification Safety Review (project-specific - CRITICAL)

This is where webwatch earns trust. For any change to extraction, checks, or notification:

- Confirm extractors distinguish "region found, value X" from "region missing" — a missing/ambiguous
  region yields `STRUCTURE_CHANGED`, a malformed value yields `PARSE_ERROR`, a block page yields
  `BLOCKED`. **A broken page must never produce a false `MISMATCH` or a guessed value.**
- Confirm structured data (JSON-LD) is used as corroboration, not a short-circuit, and that visible
  text is authoritative.
- Confirm comparisons go through `normalize.py` so cosmetic differences don't fake a `MISMATCH`.
- Confirm the change is covered by programmatic-mutation tests proving each negative status.
- For notification changes: confirm a dry-run path exists and was exercised, alerts fire on
  state transition (not every run), and no live recipient was emailed during testing.
- If any of these can't be confirmed, STOP and discuss before proceeding.

### 5. Test Quality Validation

- Scan test files for placeholder/`pass`-only tests, unjustified skips, or tests that fetch live sites outside `@pytest.mark.integration`
- Confirm HTTP is mocked at the transport boundary against committed fixtures per `docs/Testing.md`
- Confirm negative cases are derived by programmatic mutation, not committed mutated fixtures
- Run `make test` and report pass/fail. If failures exist, STOP and require fixes

### 6. Final Verification

- Run `make precommit` to verify all pre-commit hooks pass
- Report any violations and require fixes

## Success Criteria

All steps must pass before PR creation:

- All issue requirements completed (if applicable)
- `make quality` passes (format + lint + typecheck)
- Code follows documented patterns in `docs/`
- No critical antipatterns (or acknowledged/fixed)
- Extraction & notification safety confirmed
- All tests passing (`make test`)
- Pre-commit hooks pass (`make precommit`)

## Final Output

After completing all steps, provide:

1. Summary of checklist completion status
2. List of any remaining concerns or warnings
3. Confirmation that code is ready for PR, OR a list of items that need attention

## Important Notes

- **Fail Fast**: Stop at the first major issue
- **Follow the Docs**: All code should follow patterns in `docs/`
- **A false alarm costs trust**: Be especially rigorous on the extraction & notification safety step
