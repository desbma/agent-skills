---
name: implem-brake
description: Withhold or restore permission to modify code, on the user's explicit signal.
argument-hint: "[on|off]"
disable-model-invocation: true
---

# Implementation brake

`on`, the default without argument: do not create, modify or delete any project file. Reading, searching, building and testing stay open. Discuss with the user; when a change is needed, say which one and why. Only an explicit `off` from the user lifts this — not their approval of your proposal.

`off`: you may change code again. Implementation is likely what the user wants next, but raise any open point before starting.
