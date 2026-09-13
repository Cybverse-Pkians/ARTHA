/** Special Mention Account stage, as a badge.
 *
 * The stage is a classification with a regulatory meaning, so it is rendered as
 * its own control rather than folded into the Sentinel's verdict badge: one is
 * a prediction about a customer who is still paying, the other is a fact about
 * one who has stopped. A banker who cannot tell those apart at a glance cannot
 * tell a warning from an arrears case.
 */
export function SmaBadge({
  stage,
  label,
  daysPastDue,
}: {
  stage: string;
  label: string;
  daysPastDue?: number;
}) {
  if (!stage || stage === "STANDARD") {
    return <span className="sma-badge sma-standard">Standard</span>;
  }
  return (
    <span
      className={`sma-badge sma-${stage.toLowerCase()}`}
      title={
        daysPastDue !== undefined
          ? `${daysPastDue} days past due. Band to be verified against the current RBI circular.`
          : undefined
      }
    >
      {label}
      {daysPastDue !== undefined ? ` · ${daysPastDue}d` : ""}
    </span>
  );
}
