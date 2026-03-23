import Link from "next/link";
import { DatePickerForm } from "../../components/date-picker-form";
import { fetchSlateByDate, fetchTopPicksByDate, getAllowedDateBounds, getDefaultDate, isAllowedDate } from "../../lib/mock-api";

type SlatePageProps = {
  searchParams?: {
    date?: string;
  };
};

export default async function SlatePage({ searchParams }: SlatePageProps) {
  const selectedDate = searchParams?.date ?? getDefaultDate();
  const { min, max } = getAllowedDateBounds();

  if (!isAllowedDate(selectedDate)) {
    return (
      <main className="page">
        <h1>Daily Slate</h1>
        <section className="card stack-gap">
          <h2>Invalid date</h2>
          <p className="helper-text">Please choose either {min} (today) or {max} (tomorrow).</p>
          <DatePickerForm defaultDate={getDefaultDate()} minDate={min} maxDate={max} submitLabel="Reload slate" actionPath="/slate" />
          <Link href="/" className="secondary-link">Back home</Link>
        </section>
      </main>
    );
  }

  const [games, valuePicks] = await Promise.all([fetchSlateByDate(selectedDate), fetchTopPicksByDate(selectedDate)]);

  return (
    <main className="page stack-gap-lg">
      <header>
        <h1>Daily Slate</h1>
        <p className="subtitle">{selectedDate} · Mock data only</p>
      </header>

      <section className="card stack-gap">
        <h2>Change date</h2>
        <DatePickerForm defaultDate={selectedDate} minDate={min} maxDate={max} submitLabel="Update slate" actionPath="/slate" />
      </section>

      <section className="card stack-gap">
        <h2>Top 3 overall value picks</h2>
        {valuePicks.length === 0 ? (
          <p className="empty-state">No value picks available for {selectedDate}. Check back later.</p>
        ) : (
          <ol className="pick-list">
            {valuePicks.slice(0, 3).map((pick) => (
              <li key={`${pick.gameId}-${pick.player}`}>
                <strong>{pick.player}</strong> ({pick.team}) · Model {(pick.modelProbability * 100).toFixed(1)}% · Fair {pick.fairOdds} · {pick.marketOdds} · {pick.edge}
              </li>
            ))}
          </ol>
        )}
      </section>

      <section>
        <h2>Games</h2>
        {games.length === 0 ? (
          <article className="card">
            <p className="empty-state">No games on the slate for this date yet.</p>
          </article>
        ) : (
          <div className="game-grid">
            {games.map((game) => (
              <Link href={`/games/${game.id}?date=${selectedDate}`} key={game.id} className="card game-card-link">
                <p className="helper-text">{game.league} · {new Date(game.startTimeUtc).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", timeZone: "UTC" })} UTC</p>
                <h3>{game.awayTeam.team} @ {game.homeTeam.team}</h3>

                <dl className="team-grid">
                  <div>
                    <dt>Away top scorer</dt>
                    <dd>{game.awayTeam.topScorer}</dd>
                    <dd>Fair probability {(game.awayTeam.fairProbability * 100).toFixed(1)}%</dd>
                  </div>
                  <div>
                    <dt>Home top scorer</dt>
                    <dd>{game.homeTeam.topScorer}</dd>
                    <dd>Fair probability {(game.homeTeam.fairProbability * 100).toFixed(1)}%</dd>
                  </div>
                </dl>

                <p className="metric-line">Market odds: {game.marketOdds}</p>
                <p className="metric-line">Edge: {game.edge}</p>
              </Link>
            ))}
          </div>
        )}
      </section>
    </main>
  );
}
