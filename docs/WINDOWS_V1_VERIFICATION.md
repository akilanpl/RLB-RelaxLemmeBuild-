# Windows V1 implementation and verification

Date: 2026-10-06. Host: macOS arm64. Windows release acceptance has not passed; this host has no available Windows environment.

## Implementation status

Existing architecture and agents retained. The Windows release build now includes the frozen local FastAPI/worker sidecar, standalone frontend dependencies/static/public assets, local Monaco editors, a complete private Python runtime with venv/ensurepip, and checksum-verified Node/npm. The installer is per-user and preserves application data and selected project folders. User setup uses the installed application: pair with a signed-in web account's token, configure providers/loadouts, choose a local folder and create/approve tasks. No developer command is required by this flow.

The desktop verifies authenticated launch-specific runtime readiness and a live worker before enabling privileged IPC. Real Electron main-frame authorization was fixed after native validation exposed the previous invalid WebFrameMain property. Close preserves background work; clean quit authenticates shutdown; unexpected children have bounded restart attempts and orphan cleanup. Upgrade requests clean shutdown and aborts rather than forcing an approved write. Credentials are encrypted with OS safeStorage and persisted using synced temporary-file replacement. Release child environments exclude development credentials and environment-file loading.

Local authority, SQLite recovery, immutable promotion journals, workflow gates, repair loops, durable command receipts/outbox, ownership checks and explicit task artifacts remain the existing implementation. Local approval requests now use the backend's actual plan contract; desktop auth/workspace loading does not wait on cloud connectivity. Windows-invalid output paths are rejected. Sandbox subprocess cancellation includes process trees and disposable snapshot/venv cleanup. Local subprocesses retain the user's OS permissions; this driver is not an OS container.

## Results actually obtained

| Check | Result |
| --- | --- |
| Full backend suites (tests, integration, hosted_integration) | 242 passed, 2 skipped; expected duplicate-ZIP fixture warning |
| Frontend contract regression tests | 2 passed |
| Frontend lint and typecheck | Passed |
| Production Next build | Passed |
| Python compile checks | Passed |
| Electron syntax/lifecycle/security regression tests | 9 passed |
| Diff whitespace check | Passed |
| Frontend and desktop production dependency audits | Zero reported vulnerabilities |
| Frozen Python sidecar and standalone frontend build | Passed on macOS |
| Actual Electron package construction | Passed for macOS arm64, development unsigned package |
| Actual packaged native GUI | Pairing page displayed Ready; native menu quit completed runtime shutdown and closed both listeners |
| Packaged-process smoke | Passed authentication, worker/instance readiness, unauthorized shutdown rejection, real local registration, encrypted provider/workspace restart persistence, parent-loss cleanup, frontend nonce/static files and locally served Monaco assets |
| Windows build guard | Correctly rejects attempting a Windows installer on this Mac |
| Windows installer, bundled Windows toolchains and installed runtime | Not executed; requires Windows x64 |
| Live hosted pairing/provider task/browser controls | Not executed against a real account; automated authenticated fixtures and actual local subprocess workflow tests passed |

The two skipped tests need disposable PostgreSQL/pgmq. This Mac cannot start the required PostgreSQL shared-memory service and has no pgmq/container runtime. Existing CI jobs cover these services. No production database or real account was changed.

## Remaining external acceptance gates and exact next action

Run the committed Windows CI job on Windows x64. It builds `RLB-Setup-0.1.0.exe`, installs it into a disposable profile and runs packaged sidecar/frontend/toolchain smoke checks, native first launch, background close, live upgrade and uninstall/data preservation. The CI job and Windows PowerShell/NSIS hooks have not been executed on this Mac; their successful Windows execution remains a gate.

Then install that artifact on a clean Windows user account against the intended hosted deployment (migrations through 008, private artifact bucket, verified JWT auth, control-only mode). Pair with actual account credentials, register a real project, run a real provider-backed task through both approvals, failure/repair/review/completion, and exercise authenticated remote prompt/pause/resume/stop, revoked-device rejection, artifacts, network-loss catch-up and reboot/crash recovery. Run the PostgreSQL/pgmq CI suites as well. No Windows or live-account acceptance result is implied by the macOS and fixture results above.
