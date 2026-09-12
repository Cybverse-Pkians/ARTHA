/** Every figure in this console is illustrative (report §11.2).
 *
 * Shown on every page that renders a number. A dashboard is the easiest place
 * for "generated from synthetic data" to quietly become "measured", and the
 * claims register only means something if the labelling survives into the UI.
 */
export function Provenance({ note }: { note?: string }) {
  return (
    <div className="provenance">
      <span aria-hidden="true">◆</span>
      <span>
        <strong>Illustrative figures.</strong>{" "}
        {note ??
          "Generated from the synthetic transaction generator (report §11.1). Not measured portfolio results."}
      </span>
    </div>
  );
}
