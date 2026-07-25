"""Read-only projections over the ledger.

Step 0 serves these from the hand-written Dream fixture rather than the
database. That is deliberate: the point of the stub is to prove the *contract*
path — typed model out of the API, through JSON, into the browser — before any
ingestion exists to get it wrong. Step 4 swaps the source and the shape stays.

SPEC §3.1 · the public surface is read-only. Every route here is a GET, and
there is no write path to disable later.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from packages.contracts.fixtures.dream import DREAM_ROW, dream_packet
from packages.contracts.models import HoldingRow, Packet, PacketTotals

router = APIRouter()

#: Step 0 knows exactly one holding and one packet. A request for anything else
#: is a 404 rather than an empty result, because "no rows" and "not a thing we
#: have" are different answers and only one of them means the caller is wrong.
_ROWS: dict[str, HoldingRow] = {DREAM_ROW.holding_id: DREAM_ROW}


@router.get("/holdings/{holding_id}", response_model=HoldingRow)
def get_holding(holding_id: str) -> HoldingRow:
    row = _ROWS.get(holding_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"no holding {holding_id!r}")
    return row


@router.get("/funds/{fund_id}/periods/{period_id}/packet", response_model=Packet)
def get_packet(fund_id: str, period_id: str) -> Packet:
    packet = dream_packet()
    if fund_id != packet.fund_id or period_id != packet.period.id:
        raise HTTPException(status_code=404, detail=f"no packet {fund_id}/{period_id}")
    return packet


@router.get("/funds/{fund_id}/periods/{period_id}/totals", response_model=PacketTotals)
def get_totals(fund_id: str, period_id: str) -> PacketTotals:
    """The total, with its kind and its unsupported subtotal attached.

    Deliberately not a bare number. INV-19: a caller that wants "the fund's
    value" has to read past the qualification to get it, rather than receiving an
    unqualified figure and having to remember there was a caveat somewhere.
    """
    return get_packet(fund_id, period_id).totals()
