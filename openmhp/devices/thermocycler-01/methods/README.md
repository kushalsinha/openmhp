# Methods on thermocycler-01

One folder per project; `_shared` holds methods owned by no project. Each `<method>.yaml` is the
current version, `<method>.history.jsonl` every earlier one, `<method>.runs.jsonl` every run on this
instrument. Save methods through `methods/save` so the device validates and versions them; files
written by hand carry `validated: null` until they are saved once. Rules: SPEC.md §4.5.
