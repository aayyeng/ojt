---
name: design-system-from-real-process
description: Use when asked to design, plan or demo a software system or UI that replaces a real manual process (spreadsheets, paperwork, approvals), and to hand the plan to other AIs.
---

# Design a system from a real process

A method for turning "automate what we do by hand" into a plan other AIs can build from and a demo people can try. Work in this order.

## 1. Learn the real process before proposing anything
- Open the user's actual material (spreadsheet, forms, sample documents) and read it, do not guess from the filename.
- Write down: the inputs a person types, the values looked up automatically, the formulas, the outputs, who touches it and in what order.
- Extract the business rules as exact formulas (rates, rounding, which column an amount goes in). Put them in ONE shared module so the app, importer and tests agree.
- Measure the data quality: duplicates, inconsistent labels, lost leading zeros, typos in typed formulas. Report the counts. These findings are part of the value of the project.

## 2. Ask only what changes the design
- Ask a few short questions (users and roles, where it runs, which export matters). If the user does not know, pick a sensible default, state it, and keep going.
- Do not make the user decide things they have no information about yet. Record them as open questions in the plan.

## 3. Go beyond digitising the same steps
- If the new system only copies the old steps, it helps little. Look for the step that costs the most time and attack it (for example: scan once in batches and reuse the image for encoding, checking and approval, instead of retyping).
- Be honest about limits. Say what still needs a human (proofreading) and how the design makes that step faster rather than pretending it disappears.

## 4. Design for the exceptions, not the happy path
- Ask what goes wrong in the real world (faded or unreadable inputs, missing master data, duplicates, wrong totals) and give each case a defined path.
- Never-guess rule: if a value cannot be read or derived, leave it blank and flagged, with a confidence level. A confident wrong value is worse than an empty field.
- Use a second source to verify (for example a master list or arithmetic cross-check) and show confidence in the UI so people look hard only where needed.
- Validation: separate blocking errors from warnings and info.

## 5. Model the people and the control
- Map the approval chain to roles and statuses (for example Draft -> Submitted -> Checked -> Approved, plus Returned).
- Lock records after submission, require a remark when returning, and keep an audit trail of who did what and when.
- Show each role only the queue that needs their action.

## 6. Write the handoff plan for other AIs (PLAN.md)
Make it self-contained, with: background and current process, business rules as formulas, data dictionary, roles and workflow, features by phase, data model, API list, screen list, capture/automation approach, validation rules, acceptance tests with expected numbers, assumptions and open questions, and what NOT to build yet. Another AI that has never seen the conversation must be able to build from it.

## 7. Build the demo with real data
- Prefer a stack that runs locally with minimal setup (small backend, SQLite, no build step) and say how to start it.
- Import the user's real data so the demo looks like their world. Seed records in every workflow state so every screen has something to show.
- Make the fast path fast: keyboard-first entry, auto-fill from lookups, auto-save, sensible defaults.
- Where a feature depends on a real capability (such as OCR), use the real thing when available, label any simulated provider clearly, and never claim accuracy you did not measure.

## 8. Verify before delivering
- Test the rules and the whole workflow through the API with an automated script, including permission checks and the failure cases.
- Run the real tool on realistic samples and report what it got wrong, not only what it got right.
- Look at the UI in a browser or screenshot if possible.
- Deliver the files with a short note: what works, what is simulated, how to run it, and one natural next step.

## Style rules
- Short plain sentences. Lead with the answer.
- Keep fictional sample data clearly fictional and watermarked.
- State assumptions explicitly (for example export column mappings) so the user can confirm them.
