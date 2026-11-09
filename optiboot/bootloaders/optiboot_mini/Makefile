.DEFAULT_GOAL := both
include Makefile.dual
include Makefile.mini.inc
include Makefile.mini328.inc

.PHONY: test check
test check:
	$(PYTHON) run_tests.py
