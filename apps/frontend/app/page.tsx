import { DatePickerForm } from "../components/date-picker-form";
import { fetchDateAvailability, getCurrentUtcDate } from "../lib/api";

export default async function HomePage() {
  const availability = await fetchDateAvailability(getCurrentUtcDate());

  return (
    <main className="page">
      <h1>Quick Netters</h1>
      <p className="subtitle">Pick a date to view the first-goal slate and value picks.</p>

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
      </section>
    </main>
  );
}
