# Setting up on the Chromeleon client PC (Windows only)

The Chromeleon SDK is a 32-bit .NET assembly that only runs inside a fully installed and licensed
Chromeleon client on the same machine, so this package is served from that PC. The twin runs anywhere.

## What you need

- Chromeleon 7.2 or 7.3 client with a client licence, connected to the data vault and the instrument.
- The **Chromeleon SDK**: `Thermo.Chromeleon.Sdk.dll` ships in the Chromeleon `bin` folder (also in the
  GAC). Thermo's "Chromeleon SDK specifications" sheet (PS74111) says an out-of-process executable, which
  is what a Python process is, needs no SDK runtime licence; a development licence (P/N 7100.0082) buys the
  API reference, which you will want for the members marked unverified in `references/chromeleon_sdk.md`.
- A **32-bit Python** (the SDK raises `SdkException` "WrongArchitecture" from a 64-bit process) with
  `pip install openmhp pythonnet keyring`.
- A Chromeleon user for the agent with rights on the data vault folder and instrument control.

## Install

1. Copy `config.example.json` to `config.json`: `sdk_dir`, the data vault folder URL the agent creates
   sequences in (chrom://...), the instrument URL, the user, and the sampler's injection volume range.
2. Store the password: `python -m keyring set Chromeleon <username>`. Leave `username` empty to let the
   SDK use its interactive logon (only workable on a logged-in desktop).
3. Put the instrument and processing methods the agent may use in that folder and, if you want to
   restrict it, list them in `allowed_methods`.
4. `mhp serve pkg:<this folder> --http <port>` and read `connected` and `instrument_status`.

## First hardware test

1. Read `connected`; if it is false, the reason names the SDK, the architecture or the logon.
2. Run `list_methods` and check the names match the folder in the Chromeleon console.
3. Invoke `run_samples` with one blank injection (the example with one sample, 1 uL); watch the sequence
   appear in the console's queue and start.
4. Read the job result when the injection ends; compare the peak table with the console's.
5. Start a second sequence, stop it from the console, and confirm the job ends (the SDK reports the
   injection ended) rather than hanging.

## Status

twin tested. Written from the SDK members visible in public code (see `references/chromeleon_sdk.md`);
several members are unverified and not yet run against a Chromeleon installation.
