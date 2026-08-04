# Security policy

## Supported versions

The current `main` branch is supported for security fixes while this project is
an incubation repository.

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability or credential leak.
Use GitHub's private security advisory flow for this repository, or contact the
repository maintainers privately with a minimal reproduction and the affected
commit.

Do not include live credentials, customer data, raw licensed source material,
or executable trading instructions in a report. Revoke and rotate any exposed
credential through its owning provider before reporting it.

## Repository guardrails

Automated secret scanning runs on pushes and pull requests. It supplements,
rather than replaces, the portable boundary: credentials, cookies, provider
tokens, signed URLs, raw provider payloads, and broker authority are forbidden
from portable inputs, results, events, artifacts, logs, and browser payloads.
