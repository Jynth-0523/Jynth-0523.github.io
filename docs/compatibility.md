# Naming, paths, and historical compatibility

Public modules, commands, headers, schema labels, messages, and example database
objects use descriptive names. Application paths are resolved from the repository
or the script itself, not from the author's home directory. External assets are
configured explicitly. Downloading the public repository does not download paid
research data, a private research engine, or a PostgreSQL archive.

## Public names and external metadata

Public specification labels, validation-profile IDs, fixtures, and workbook labels
use descriptive names. No project-release labels are hard-coded in published files.
These public names identify software profiles, not a newly executed historical run.

Optional archive checks use `ARCHIVE_RESEARCH_SPEC_ID`, `ARCHIVE_RUN_ID`, and
`ARCHIVE_DASHBOARD_NAME` supplied locally. They compare the exact source metadata;
hash and Formal/Shadow checks remain in force. A health report includes the source
metadata separately as `source_archive_identity`. Missing settings block the check.

The optional discovery adapter accepts `DISCOVERY_SOURCE_SPEC_ID`,
`DISCOVERY_MODIFICATION_FIELD`, `DISCOVERY_IMPLEMENTATION_DIRECTORY`, and
`DISCOVERY_RESULT_DIRECTORY` for an explicitly configured external source.
Paths must remain within the reviewed layout and implementation hashes still
must match. Conflicting modification flags fail closed. No source file is renamed
or rewritten by this adapter. The browser workspace needs none of these settings.

Dependency constraints, external API routes, and Tableau XML syntax remain intact;
they are required third-party compatibility information, not project names.

The public SQL importer creates objects in `research` in a separately authorized
database. It is never invoked by normal startup or tests. The historical checker
uses the configured `PGSCHEMA` and a read-only transaction. No existing database
was renamed, migrated, or written during this cleanup.

## Existing local state

Public profile, health-field, and review-schema labels changed in this cleanup. Keep an
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
