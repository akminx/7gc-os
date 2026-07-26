import type { GapObservation } from "./contracts";
import { GAP_KIND, GAP_KIND_ORDER } from "./labels";
import type { PacketResponse } from "./responses";
import { GapItem, Meta, Section, SourceBadge } from "./ui";

/**
 * SPEC §12 · the gap inventory.
 *
 * Grouped by `kind`, and the three groups always render — an empty one says
 * "none recorded" rather than disappearing. INV-12 is that the three kinds mean
 * different things to an auditor: a document held by counsel is a request to
 * counsel, a document referenced with no stated location is a custody question,
 * and a document searched for and not found is a request to the company.
 * Collapsing them to "missing" throws away the only part that says what to do
 * next.
 *
 * The grouping is a filter over rows the API supplied, in a fixed display
 * order. No count, subtotal or status is derived here; the position counts come
 * from `PacketTotals`.
 */

interface Entry {
  gap: GapObservation;
  company: string;
}

export function GapInventory({ packet }: { packet: PacketResponse }) {
  const entries: Entry[] = packet.rows.flatMap((row) =>
    row.gaps.map((gap) => ({ gap, company: row.company_name })),
  );
  return (
    <>
      <Section
        title="Gap inventory"
        note="Every gap observation in the packet. The packet states its own gaps; that is what makes it an honest deliverable rather than a clean-looking one."
      >
        <p className="note">
          <SourceBadge source={packet.source} />
        </p>
        <Meta
          items={[
            {
              label: "unsupported positions held at this date (API)",
              value: <strong>{packet.totals.unsupported_positions}</strong>,
            },
            {
              label: "packet gap positions, held or not (API)",
              value: <strong>{packet.totals.packet_gap_positions}</strong>,
            },
            {
              label: "unsupported but not held at this date (API)",
              value: <strong>{packet.totals.unheld_gap_positions}</strong>,
            },
          ]}
        />
        <p className="note">
          Those two counts are <em>positions</em>, supplied by the API. They are not a count of the
          observations below: a position can be unsupported with no gap observation recorded against
          it, and one position can carry several observations. The two units are not interchangeable
          and neither is derived from the other here.
        </p>
      </Section>

      {GAP_KIND_ORDER.map((kind) => {
        const group = entries.filter((entry) => entry.gap.kind === kind);
        return (
          <Section key={kind} title={GAP_KIND[kind].label} note={GAP_KIND[kind].meaning}>
            <p className="note">Next action: {GAP_KIND[kind].next}</p>
            {group.length === 0 ? (
              <p className="note">No observation of this kind is recorded in this packet.</p>
            ) : (
              <ul className="gap-list">
                {group.map((entry) => (
                  <GapItem
                    key={`${entry.gap.holding_id}:${entry.gap.id}`}
                    gap={entry.gap}
                    heading={<strong>{entry.company}</strong>}
                  />
                ))}
              </ul>
            )}
          </Section>
        );
      })}
    </>
  );
}
