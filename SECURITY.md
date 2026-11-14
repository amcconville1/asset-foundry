# Security

## Reporting

Please report vulnerabilities privately through GitHub's "Report a vulnerability" (Security
tab → Advisories), not in a public issue. You'll get a reply within a week.

## What to know when using the foundry

- **Profiles can run code.** A builder module a profile lists in `parts` is Python that
  runs with your permissions, and `[hooks]` are shell commands. Treat profiles and builder
  modules from others like code: read them before building. Recipes themselves are data.
- **Blender runs headless** with `--factory-startup` (no user add-ons or startup files), one
  process per variant, and is stopped if it outlives its timeout.
- **The review server is local.** `foundry review` binds to 127.0.0.1 only, has no
  authentication, serves only catalog files of known types (`.png`, `.glb`, `.json`, ...)
  and refuses paths that leave the catalog. Don't expose it to a network.
