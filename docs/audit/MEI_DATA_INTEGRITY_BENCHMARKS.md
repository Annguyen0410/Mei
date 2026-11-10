# Data-integrity performance measurements

Environment: local Windows development machine, Python virtual environment,
`tools/benchmark_data_integrity.py`. The fixture uses synthetic task records in a
temporary profile and a temporary backup destination. These are one-run
measurements, not a statistical benchmark or a before/after claim.

| Tasks | Health scan | Verified ZIP backup | Encrypted create | Encrypted verify |
|---:|---:|---:|---:|---:|
| 100 | 0.0229 s | 0.0194 s | 0.2760 s | 0.1253 s |
| 2,000 | 0.0174 s | 0.0368 s | 0.3498 s | 0.1386 s |
| 10,000 | 0.0458 s | 0.1189 s | 0.4202 s | 0.1641 s |

Plain ZIP sizes were approximately 3.4 KB, 52 KB and 258 KB respectively.

Observations:

- Health scanning remains effectively constant for these task counts because it
  checks bounded store metadata/validation rather than building a full index.
- The encrypted create cost is dominated by scrypt plus the verification
  decryption; it grows modestly with archive size.
- Encrypted verification deliberately performs a full authenticated decrypt and
  inner-manifest verification, so it is not a cheap header-only check.
- These numbers do not cover large note vaults, BrowserData, network storage,
  or slower removable media.

Reproduce with:

```powershell
.\.venv\Scripts\python.exe tools\benchmark_data_integrity.py
```
