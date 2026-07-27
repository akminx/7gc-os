"""The auditor packet, written to disk.

Everything upstream of this assembles a `Packet` in memory and then drops it.
Harwell & Kent asked for the support "organized by portfolio company"; a
`Packet` object is not that until something serialises it, and nothing did.

What leaves here is deliberately shaped so the packet cannot flatter itself:

* Every total names what it is a total OF (INV-19), so a caller cannot print the
  fund figure without the qualification that travels with it.
* The gap report is a first-class artefact rather than an omission. A packet in
  which nothing is approved says exactly that, on the cover, in the approval log
  and once per position.
* Each cited figure is exported beside the document version it resolves into,
  and the manifest records the hash of both — so "trace this number" is a file
  path and two offsets, not a request to the fund.
"""

from __future__ import annotations

from packet.export import PacketExportError, Written, export_packet

__all__ = ["PacketExportError", "Written", "export_packet"]
