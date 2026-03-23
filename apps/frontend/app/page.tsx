import { DatePickerForm } from "../components/date-picker-form";
import { getAllowedDateBounds, getDefaultDate } from "../lib/mock-api";

export default function HomePage() {
  const defaultDate = getDefaultDate();
  const { min, max } = getAllowedDateBounds();

  return (
    <main className="page">
      <h1>Quick Netters</h1>
      <p className="subtitle">Pick a date to view the first-goal slate and value picks.</p>

      <section className="card stack-gap">
        <h2>Start here</h2>
        <p className="helper-text">Only today and tomorrow are available right now while we are in mock-data mode.</p>
        <DatePickerForm defaultDate={defaultDate} minDate={min} maxDate={max} submitLabel="View slate" actionPath="/slate" />
      </section>
    </main>
  );
}
