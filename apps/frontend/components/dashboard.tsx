import { mockOdds, mockProjections, mockRecommendations, mockSchedule } from "../lib/mock-data";

export function Dashboard() {
  return (
    <section className="grid">
      <article className="card">
        <h3>Schedule Data</h3>
        <ul>
          {mockSchedule.map((match) => (
            <li key={match.id}>{match.playerA} vs {match.playerB} ({match.tournament})</li>
          ))}
        </ul>
        <span className="tag">Mock only</span>
      </article>

      <article className="card">
        <h3>Player Projections</h3>
        <ul>
          {mockProjections.slice(0, 3).map((projection) => (
            <li key={projection.player}>{projection.player}: hold {projection.holdPct}% / break {projection.breakPct}%</li>
          ))}
        </ul>
        <span className="tag">Interface first</span>
      </article>

      <article className="card">
        <h3>Odds</h3>
        <ul>
          {mockOdds.map((odds) => (
            <li key={odds.matchId}>{odds.sportsbook}: {odds.playerA} / {odds.playerB}</li>
          ))}
        </ul>
        <span className="tag">No external feeds</span>
      </article>

      <article className="card">
        <h3>Recommendations</h3>
        <ul>
          {mockRecommendations.map((rec) => (
            <li key={rec.matchId}>Match {rec.matchId}: {(rec.confidence * 100).toFixed(0)}% confidence</li>
          ))}
        </ul>
        <span className="tag">Reasoning placeholder</span>
      </article>
    </section>
  );
}
