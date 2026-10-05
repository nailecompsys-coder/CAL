# Stage 1 isolated replay report — 2026-10-05

No production code or operational schedule/card table was changed or queried.
Immutable source PDFs were read, and all generated state was written to the
local `fax_stage1` PostgreSQL schema and local temporary work directories.

| Fax | Pages | Candidate rows | Native OCR/SQL resolved | Flagged before cross-fax audit |
|---:|---:|---:|---:|---:|
| 139 | 24 | 217 | 153 | 64 |
| 162 | 33 | 342 | 256 | 86 |
| 168 | 32 | 311 | 229 | 82 |
| 240 | 31 | 331 | 266 | 65 |
| 242 | 28 | 276 | 211 | 65 |
| 245 | 28 | 303 | 230 | 73 |
| 900001 (three-page schedule fixture) | 3 | 10 | 10 | 0 |

Totals: 179 pages, 1,790 candidate rows, 1,349 native resolutions, and
441 flagged rows. A second copy of fax 168 was checksum-identical and was not
misrepresented as an independent test.

Across these PDFs, SQL found 486 patient/date cases repeated on more than one
fax (1,140 repeated rows). The immutable-fax comparison exposed:

- 29 patient-name conflicts after case, spacing, and punctuation normalization
- 6 DOB conflicts
- 14 start-time conflicts
- 19 normalized-procedure conflicts
- 13 normalized-room conflicts

These conflicts are now added to the flagged-only vision queue by
`cross-fax-audit.psql`.

Only faxes 240, 242, and 245 remain in production file storage. Eight older
database records point to source PDFs that were previously pruned. Additional
independent replay coverage requires restoring those immutable PDFs from the
authorized archive or supplying other old source PDFs.

A clean replay through a `/tmp` work directory exposed a macOS path defect:
the renderer could create files through the `/tmp` symlink while the native
OCR executable could not reopen that spelling. The executable now canonicalizes
the work directory before rendering, loading, cropping, or recording paths.
After that fix, the three-page fixture completed with 10 of 10 rows resolved
and status `stage1_complete_pre_card_match`.

## SQL database-reference correction replay

The correction queue is now reconciled, before vision, against prior resolved
fax rows and existing operational case/activity/appointment rows. On a clean
Fax 245 rebuild, native OCR plus the cross-fax audit queued 94 rows. Unique
high-confidence SQL references resolved 67 of them, leaving 27 for vision.
Every considered match and selected source row is recorded in
`fax_stage1.reference_matches`; ambiguous best matches are not selected.

The OpenAI correction leg was not transmitted because no customer API key is
available to the executable. PHI transmission requires the organization's
approved API/healthcare agreement and retention configuration. Until that is
configured, rows remain unresolved and the document cannot receive the
`stage1_complete_pre_card_match` status.
