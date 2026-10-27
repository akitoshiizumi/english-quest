# Clone-and-run distribution validation

Date: 2026-10-27 (Asia/Tokyo)

- TypeScript checking and Vite production build: passed (`npm run build`).
- Python tests: 101 passed (`py -m unittest discover -v`), including five starter restore tests.
- Node tests: seven passed (shortcuts, statistics distribution, audio clipping).
- Playwright E2E: 40 passed (`npm run test:e2e`).
- Fresh distribution directory contained no `.env`, runtime database, `node_modules`, or installed `websockets` package. Starting the real server restored the bundled database and served the English Quest page successfully.
- Restored vocabulary count: 17,163. Saved material count: 14. Every audio reference resolved, and all 14 MP3s returned successfully from `/saved-audio` without an API key.
- Starter restoration verifies compressed parts, the complete database digest, and SQLite integrity before publishing the runtime database. Re-running restoration preserves existing learning data. Missing or damaged parts leave no partial runtime database.
- The initial precision-only compaction retained all 1,536 values per vector, shrinking the seed database to 248 MB and its bundled gzip files to 65 MB.
- The follow-up 768-dimension comparison used 1,000 sampled vectors and 100 queries. Top-five neighbor agreement with the original 1,536-dimension vectors was 89.2% at 768 dimensions and 84.2% at 512 dimensions. The 768-dimension release is 139 MB restored and about 38 MB compressed.
- The historical full test-suite run above predates the 768-dimension change. A clean seed restoration and integrity check were repeated for that release; the full automated suite was not rerun.
- The old E2E assertions for the material selector text and storage-location label also failed against the pre-change code. They now use the existing content lookup helper and current label. App title assertions were updated to English Quest.
- Runtime DB, `.env`, backups, logs, and installed dependencies are excluded from the published tree. The complete starter snapshot and `practice_data` are included as ordinary Git files; Git LFS is not needed.
- The published `main` begins with the current release snapshot. Earlier development history, including oversized database revisions, remains on the local `master` branch.

New paid AI generation was not exercised. It requires the user's API key; new speech generation additionally requires the optional Python dependency and FFmpeg documented in the README.
