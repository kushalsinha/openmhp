# Versioning and support

OpenMHP is two things that version separately: the **protocol** (`SPEC.md`, reported by every
device as `mhp` at `initialize` and in `device/describe`) and the **reference implementation**
(the `openmhp` Python package, `openmhp-cli` and `openmhp-node`).

## How versions are numbered

**Protocol.** Dated revisions, `YYYY-MM-DD`. A device reports the revision it implements; a
client reports the revision it expects at `initialize`. Revisions are ordered by date and
nothing else.

**Implementation.** Semantic versioning, `MAJOR.MINOR.PATCH`. Before 1.0 a minor bump may
break; after 1.0 only a major bump may.

## What counts as a breaking change

To the protocol: removing or renaming a method, field or error code; narrowing what a field
may contain; changing the order of the six safety gates; changing when a gate refuses;
changing what a state name means.

Not breaking: adding an optional field; adding an error code; adding a method; adding a
conformance level; relaxing a restriction; anything that only changes wording.

Devices and clients MUST ignore fields they do not recognise, which is what makes additive
change safe.

## Support window

**Pre-1.0 (now).** One protocol revision at a time. Breaking changes are possible on any minor
release and are listed at the top of the release notes. Do not build a validated or regulated
deployment on a pre-1.0 revision.

**From 1.0.** A protocol revision is supported for **24 months** from the date its successor
ships. The reference implementation accepts the current revision and the previous one for that
whole window, so a device and a client never have to be upgraded on the same day.

## Deprecation

Nothing is removed without passing through deprecation first:

1. The replacement ships, and the old form keeps working.
2. The old form is marked deprecated in `SPEC.md` and in release notes, naming the replacement
   and the earliest revision that may remove it. The runtime warns when it is used.
3. Removal, no sooner than **12 months** after step 2, and only in a revision whose notes say
   so at the top.

## Staying on a version you have qualified

Pin the implementation (`openmhp==X.Y.Z`) and the protocol revision your device reports. A
conformance report (`mhp conformance <target>`) is evidence about **one device at one protocol
revision**, so re-run it after changing either. Nothing in the runtime auto-updates a
deployment; `npx openmhp-node` resolves the latest published launcher at install time, so pin
it too if your deployment is qualified.

## Where changes are announced

`SPEC.md` carries the current revision and a section for what is not yet specified. Release
notes accompany every published version. Breaking changes appear first in both.
