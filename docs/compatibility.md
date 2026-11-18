# Naming, paths, and historical compatibility

Public modules, commands, headers, schema labels, messages, and example database
objects use descriptive names. Application paths are resolved from the repository
or the script itself, not from the author's home directory. External assets are
configured explicitly. Downloading the public repository does not download paid
research data, a private research engine, or a PostgreSQL archive.

## Deliberate exceptions

- Frozen research-specification and run identifiers are exact historical facts.
  They remain unchanged in validators, configuration, and synthetic fixtures.
  Renaming them would falsely label an existing result as a different research run.
- The historical workbook's expected dashboard title remains in the read-only
  audit configuration because it belongs to the hash-locked original. The public
  workbook template uses descriptive names instead.
- `backend/src/research_platform/historical_contract.py` recognizes the original
  modification flag and artifact-directory labels. Conflicting old/new flags fail
  closed. It never modifies the source artifacts.
- Dependency versions, API-standard versions, and Tableau XML attribute names
  remain intact because they define compatibility, not project branding.

The public SQL importer creates objects in `research` in a separately authorized
database. It is never invoked by normal startup or tests. The historical checker
uses the configured `PGSCHEMA` and a read-only transaction. No existing database
was renamed, migrated, or written during this cleanup.

## Existing local state

Public health-field and review-schema labels changed in this cleanup. Keep an
existing runtime directory as an archive and use a fresh runtime directory with
the new public package. Do not rewrite old hash-linked run envelopes or frozen
review records to match the new labels. Old research outputs remain unchanged;
this is a software naming update, not new empirical evidence.

## What running the download means

After installing Node.js and the locked web dependencies, the browser workspace
can start locally without private services. Optional historical checks require
the user's own authorized assets and exact configuration. Their absence is
reported as blocked, not as successful research validation. Software tests use
synthetic fixtures; they do not rerun locked research or establish paper-replication
accuracy.
