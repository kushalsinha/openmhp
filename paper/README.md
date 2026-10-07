# Paper

`openmhp.tex` is the arXiv/journal source for the OpenMHP paper. `openmhp.pdf` is the built copy.

## Build

```bash
brew install tectonic          # one self-contained binary; fetches only what the doc needs
tectonic -X compile openmhp.tex
```

Any TeX distribution works too (`pdflatex openmhp.tex` twice, for the references).

## Before submitting

The source defines a `\TODO{...}` macro that renders in red. Every unfinished claim is wrapped
in one, so nothing unverified can be submitted by accident. Search for `\TODO` and clear them
all; the most important is §9.3, the deployment-on-physical-instruments subsection, which must
be written from real runs. To make leftovers invisible instead of red, redefine the macro as
`\newcommand{\TODO}[1]{}`.
