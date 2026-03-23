import Link from "next/link";
import { fetchGameDetail, getAllowedDateBounds, getDefaultDate, isAllowedDate } from "../../../lib/mock-api";

type GameDetailPageProps = {
  params: {
    gameId: string;
  };
  searchParams?: {
    date?: string;
  };
};

export default async function GameDetailPage({ params, searchParams }: GameDetailPageProps) {
  const selectedDate = searchParams?.date ?? getDefaultDate();
  const { min, max } = getAllowedDateBounds();

  if (!isAllowedDate(selectedDate)) {
    return (
      <main className="page">
        <h1>Game detail</h1>
        <section className="card stack-gap">
          <h2>Invalid date</h2>
          <p className="helper-text">Use {min} (today) or {max} (tomorrow), then reopen a game.</p>
          <Link href={`/slate?date=${getDefaultDate()}`} className="secondary-link">Back to slate</Link>
        </section>
      </main>
    );
  }

  const game = await fetchGameDetail(params.gameId, selectedDate);

  if (!game) {
    return (
      <main className="page stack-gap">
        <h1>Game detail</h1>
        <section className="card">
          <p className="empty-state">No mock game detail exists for this matchup and date yet.</p>
        </section>
        <Link href={`/slate?date=${selectedDate}`} className="secondary-link">Back to slate</Link>
      </main>
    );
  }

  return (
    <main className="page stack-gap-lg">
      <header className="stack-gap-sm">
        <p className="subtitle">{game.date}</p>
        <h1>{game.matchup}</h1>
        <p className="helper-text">Start {new Date(game.startTimeUtc).toLocaleString("en-US", { timeZone: "UTC" })} UTC</p>
        <Link href={`/slate?date=${selectedDate}`} className="secondary-link">← Back to slate</Link>
      </header>

      <section className="card stack-gap">
        <h2>Top 3 best bets</h2>
        {game.topBets.length === 0 ? (
          <p className="empty-state">No top bets available for this game.</p>
        ) : (
          <table className="bets-table">
            <thead>
              <tr>
                <th>Player</th>
                <th>Team</th>
                <th>Model probability</th>
                <th>Fair odds</th>
                <th>Market odds</th>
                <th>Edge</th>
              </tr>
            </thead>
            <tbody>
              {game.topBets.map((bet) => (
                <tr key={bet.player}>
                  <td>{bet.player}</td>
                  <td>{bet.team}</td>
                  <td>{(bet.modelProbability * 100).toFixed(1)}%</td>
                  <td>{bet.fairOdds}</td>
                  <td>{bet.marketOdds}</td>
                  <td>{bet.edge}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="card stack-gap">
        <h2>Additional candidate players</h2>
        {game.candidatePlayers.length === 0 ? (
          <p className="empty-state">No additional players for this game yet.</p>
        ) : (
          <ul className="candidate-list">
            {game.candidatePlayers.map((bet) => (
              <li key={bet.player}>
                <strong>{bet.player}</strong> ({bet.team}) · Model {(bet.modelProbability * 100).toFixed(1)}% · Fair {bet.fairOdds} · {bet.marketOdds} · {bet.edge}
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}
