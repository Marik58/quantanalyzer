# How we build (as of 2026-10-07)

QuantAnalyzer is built by Marik with an AI coding assistant. Trust in the numbers matters
more than speed, and anything shown to others must be independently checkable.

## The loop

1. **One Roadmap item at a time.** Commit each one separately with a message that says what
   changed and why, then push to `main` (the repo is public).
2. **Tests are the gate.** `python scripts/run_all_tests.py` must be all green before any
   commit, and each feature adds its own checks. A good test is a known-answer test: a planted
   edge must be found, no edge must not be invented, and a deliberately broken version of the
   code must make the test fail.
3. **Verify, don't repeat.** Run the code; check formulas against textbook versions or
   synthetic data with known answers; render the UI before calling it done. A September 2026
   audit found docs claiming a model (GARCH) that was never implemented.
4. **Audit your own output.** After any rule change, look at a sample of the results by
   hand. The ticker-to-company map's first run looked fine in aggregate, but 22 of its
   "likely" rows were mostly wrong.

## Sign-off before editing

These files need Marik's OK first: `backend/main.py`, `backend/analysis/data.py`,
`backend/analysis/signals.py`. For any other file, show what changed, then apply.

## Planning versus building

While Marik is still shaping a plan or adding ideas, proposals stay in the chat and no files
change. An explicit "go ahead" or "start building" switches to building.

## Explaining things

Use plain language and analogies, with the big picture before the details. Explain every
term the first time it appears. When asking Marik to do something, say exactly what to click
or type.

## Known machine quirk

On the development laptop (Windows, Git Bash), shell heredocs eat one level of backslashes
and backticks trigger command substitution. Write patch scripts to a file first.
