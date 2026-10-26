# 05 ??Status view and operational polish

**What to build:** Trust and observability for day-to-day operation: a `status` command listing which archives are indexed versus pending; an ingest summary after every run reporting new, skipped, and errored items; sensible exit codes distinguishing success, partial failure, and unreadable input; and a usage README covering install, ingest, and the query commands.

**Blocked by:** 02 ??Structured envelope parsing.

**Status:** resolved

- [x] Status correctly reports pending archives when new files are dropped into the folder and none remain pending after ingest
- [x] Every ingest run ends with a summary whose counts reconcile with the database state
- [x] Exit codes distinguish clean success, partial success with recorded errors, and total failure
- [x] README gets a new user from install to first successful search without outside help
- [x] All behaviour verified through the CLI boundary only
