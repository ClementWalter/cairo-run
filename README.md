# Welcome to cairo-run

`cairo-run` is a simple Scarb + Python project to show how to run `scarb`
compiled cairo files on the python Cairo VM.

:warning: it's experimental and cairo traces haven't been checked thoroughly!

## How to use

1. `scarb build` to build the scarb artifacts
1. `python main.py` to run the compiled cairo program with the python cairo-vm
