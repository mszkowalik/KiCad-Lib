"""Production flasher backend.

The browser does the esptool work (erase/flash/verify — latency-sensitive SLIP
round trips) and acts as a dumb byte pipe for the monitor phase; THIS package
owns the scenario: the step interpreter, the Tasmota dialog, credential
derivation and every database write. See docs/flasher/design.md §3.
"""
