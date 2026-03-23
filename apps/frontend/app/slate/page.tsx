import Link from "next/link";
import { DatePickerForm } from "../../components/date-picker-form";
import {
  fetchDailyRecommendationsByDate,
  fetchGamesByDate,
  getAllowedDateBounds,
  getDefaultDate,
  isAllowedDate,
} from "../../lib/mock-api";

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

  const [gamesResponse, dailyRecommendations] = await Promise.all([
    fetchGamesByDate(selectedDate),
    fetchDailyRecommendationsByDate(selectedDate),
  ]);

  return (
    <main className="page stack-gap-lg">
      <header>
        <h1>Daily Slate</h1>
        <p className="subtitle">{selectedDate} · Scheduled games, projections, and value picks</p>
      </header>

      <section className="card stack-gap">
        <h2>Change date</h2>
        <DatePickerForm defaultDate={selectedDate} minDate={min} maxDate={max} submitLabel="Update slate" actionPath="/slate" />
      </section>

      {gamesResponse.notes.length > 0 && (
        <section className="card stack-gap">
          <h2>Data updates</h2>
          <ul className="candidate-list">
            {gamesResponse.notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        </section>
      )}

      <section className="card stack-gap">
        <h2>Top 3 overall value picks</h2>
        {dailyRecommendations.recommendations.length === 0 ? (
          <p className="empty-state">No value picks available for {selectedDate}. Odds and projection inputs may still be loading.</p>
        ) : (
          <ol className="pick-list">
            {dailyRecommendations.recommendations.slice(0, 3).map((pick) => (
              <li key={`${pick.game_id}-${pick.player_id}`}>
                <strong>{pick.player_name}</strong> · Model {(pick.model_probability * 100).toFixed(1)}% · Fair +{pick.fair_odds} · Market +{pick.market_odds} · Edge {(pick.edge * 100).toFixed(1)}% · EV {(pick.ev * 100).toFixed(1)}%
              </li>
            ))}
          </ol>
        )}
      </section>

      <section>
        <h2>Games</h2>
        {gamesResponse.games.length === 0 ? (
          <article className="card">
            <p className="empty-state">No games on the slate for this date yet.</p>
          </article>
        ) : (
          <div className="game-grid">
            {gamesResponse.games.map((game) => (
              <Link href={`/games/${game.game_id}?date=${selectedDate}`} key={game.game_id} className="card game-card-link stack-gap-sm">
                <p className="helper-text">{new Date(game.game_time).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", timeZone: "UTC" })} UTC</p>
                <h3>{game.away_team} @ {game.home_team}</h3>
                {game.away_top_projected_scorer && game.home_top_projected_scorer ? (
                  <p className="helper-text">
                    Top projected scorers: {game.away_top_projected_scorer.player_name} ({(game.away_top_projected_scorer.model_probability * 100).toFixed(1)}%) · {game.home_top_projected_scorer.player_name} ({(game.home_top_projected_scorer.model_probability * 100).toFixed(1)}%)
                  </p>
                ) : (
                  <p className="helper-text">Top projected scorer per team will appear once projections are available.</p>
                )}
              </Link>
            ))}
          </div>
        )}
      </section>
    </main>
  );
}
