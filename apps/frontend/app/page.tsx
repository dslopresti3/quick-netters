import { DatePickerForm } from "../components/date-picker-form";
import { AppShellHeader } from "../components/app-shell-header";
import { PageHeader } from "../components/page-header";
import { fetchDateAvailability, getCurrentUtcDate } from "../lib/api";
import Link from "next/link";

export default async function HomePage() {
  const availability = await fetchDateAvailability(getCurrentUtcDate());

  return (
    <main className="page stack-gap-lg">
      <AppShellHeader activeNav="home" />
      <PageHeader
        title="Quick Netters"
        description="Premium daily first-goal and anytime goal-scorer value intelligence."
        contextChips={["League · NHL", `Today · ${availability.selected_date}`]}
      />

      <section className="card stack-gap">
        <h2>Start here</h2>
        <p className="helper-text">You can choose any date in the current availability window.</p>
        <DatePickerForm
          defaultDate={availability.selected_date}
          minDate={availability.min_allowed_date}
          maxDate={availability.max_allowed_date}
          submitLabel="View slate"
          actionPath="/slate"
        />
        <Link href="/history" className="secondary-link">View historical picks</Link>
      </section>

      <section className="card stack-gap metrics-explainer">
        <details>
          <summary>How it works: betting metrics</summary>
          <div className="stack-gap-sm metrics-explainer-content">
            <p>
              <strong>Model Probability</strong>: The model's estimate of a player scoring first.
            </p>
            <p>
              <strong>Implied Probability</strong>: The probability implied by the sportsbook's market odds.
            </p>
            <p>
              <strong>Edge</strong>: How much the model probability differs from implied probability.
              <br />
              <code>Edge = Model Prob − Implied Prob</code>
            </p>
            <p>
              <strong>Expected Value (EV)</strong>: Estimated return per 1 unit staked.
              <br />
              <code>EV = (Model Prob × Payout) − (1 − Model Prob)</code>
            </p>
          </div>
        </details>
      </section>
    </main>
  );
}
