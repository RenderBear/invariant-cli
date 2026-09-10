# Human ergonomics

Translate Invariant's protocol into the repository behavior a person actually needs to decide.
Lead with the finding, consequence, and recommendation; keep IDs and locator syntax as supporting
detail for the agent and CLI.

Do not ask a human to select paths, domains, reach, boundaries, architecture-reference locators,
governance references, checks, or assessment fields. Infer and validate those mechanically. If a
protocol value is missing or invalid, explain what evidence the agent will inspect or correct
rather than forwarding the validation error as a questionnaire.

When human authority is required, present one compact decision packet:

- what was observed and how strong the evidence is;
- why it matters to future repository behavior;
- the compatible options and their practical consequences;
- the recommended option and why;
- the single approval, rejection, or behavior-level clarification needed from the human.

After a governance audit, group findings as ready to adopt, needing a semantic decision, needing a
verifier, and evidence-only. State that the audit has already been saved. Offer clear next actions:
investigate named areas more deeply, adopt every ready finding, adopt selected findings, or defer
adoption while retaining the audit. Never imply that choosing one ready finding discards the rest.

Translate recurring internal terms consistently: authority means who may decide repository-wide
meaning; architecture reference means the accepted prose that defines a decision; governance
reference means the durable record being changed; boundary means whether durable meaning changes;
reach means which accepted records may be affected; discovery means unresolved evidence. Humans
should see these terms only when the distinction helps their decision.

If no human decision is required, say what will happen and continue. Do not request confirmation
for validation, local branch mechanics, audit persistence, or other actions already governed by
`execution` and repository policy.
