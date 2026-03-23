import { Dashboard } from "../components/dashboard";

export default function HomePage() {
  return (
    <main className="page">
      <h1>Quick Netters</h1>
      <p className="subtitle">Mock-only frontend scaffold for schedule, projections, odds, and recommendations.</p>
      <Dashboard />
    </main>
  );
}
