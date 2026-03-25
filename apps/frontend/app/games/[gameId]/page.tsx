import Link from "next/link";
import { RecommendationCard } from "../../../components/recommendation-card";
import { fetchDateAvailability, fetchGameRecommendations, getCurrentUtcDate, resolveDisplayTimezone } from "../../../lib/api";

type GameDetailPageProps = {
  params: {
    gameId: string;
  };
  searchParams?: {
    date?: string;
    timezone?: string;
  };
};

export default async function GameDetailPage({ params, searchParams }: GameDetailPageProps) {
  const selectedDate = searchParams?.date ?? getCurrentUtcDate();
  const displayTimezone = resolveDisplayTimezone(searchParams?.timezone);
  const availability = await fetchDateAvailability(selectedDate);

  if (!availability.valid_by_product_rule) {
    return (
      <main className="page">
        <h1>Game detail</h1>
        <section className="card stack-gap">
          <h2>Invalid date</h2>
          <ul className="candidate-list">
            {availability.messages.map((message) => (
              <li key={message}>{message}</li>
            ))}
          </ul>
          <Link href={`/slate?date=${availability.min_allowed_date}&timezone=${encodeURIComponent(displayTimezone)}`} className="secondary-link">Back to slate</Link>
        </section>
      </main>
    );
  }

  if (!availability.schedule_available) {
    return (
      <main className="page stack-gap">
        <h1>Game detail</h1>
        <section className="card stack-gap">
          <h2>No scheduled games</h2>
          <ul className="candidate-list">
            {availability.messages.map((message) => (
              <li key={message}>{message}</li>
            ))}
          </ul>
        </section>
        <Link href={`/slate?date=${selectedDate}&timezone=${encodeURIComponent(displayTimezone)}`} className="secondary-link">Back to slate</Link>
      </main>
    );
  }

  const gameResponse = await fetchGameRecommendations(params.gameId, selectedDate, displayTimezone);

  if (!gameResponse) {
    return (
      <main className="page stack-gap">
        <h1>Game detail</h1>
        <section className="card">
          <p className="empty-state">No game detail exists for this matchup and date yet.</p>
        </section>
        <Link href={`/slate?date=${selectedDate}&timezone=${encodeURIComponent(displayTimezone)}`} className="secondary-link">Back to slate</Link>
      </main>
    );
  }

  const topPlays = gameResponse.top_plays ?? gameResponse.recommendations.slice(0, 3);
  const bestBet = gameResponse.best_bet;
  const underdogPlay = gameResponse.underdog_value_play;

  return (
    <main className="page stack-gap-lg">
      <header className="stack-gap-sm">
        <p className="subtitle">{gameResponse.date}</p>
        <h1>{gameResponse.game.away_team} @ {gameResponse.game.home_team}</h1>
        <p className="helper-text">Start {gameResponse.game.display_game_time ?? new Date(gameResponse.game.game_time).toLocaleString("en-US", { timeZone: displayTimezone })} {gameResponse.game.display_timezone ?? displayTimezone}</p>
        <Link href={`/slate?date=${selectedDate}&timezone=${encodeURIComponent(displayTimezone)}`} className="secondary-link">← Back to slate</Link>
      </header>

      {gameResponse.notes.length > 0 && (
        <section className="card stack-gap">
          <h2>Data updates</h2>
          <ul className="candidate-list">
            {gameResponse.notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        </section>
      )}

      {availability.messages.length > 0 && availability.status !== "ready" && (
        <section className="card stack-gap">
          <h2>Availability</h2>
          <ul className="candidate-list">
            {availability.messages.map((message) => (
              <li key={message}>{message}</li>
            ))}
          </ul>
        </section>
      )}

      <section className="card stack-gap">
        <h2>Top projected first-goal scorers by team</h2>
        <ul className="candidate-list">
          <li>
            <strong>{gameResponse.game.away_team}:</strong>{" "}
            {gameResponse.game.away_top_projected_scorer
              ? `${gameResponse.game.away_top_projected_scorer.player_name} (${(gameResponse.game.away_top_projected_scorer.model_probability * 100).toFixed(1)}%)`
              : "Projection unavailable"}
          </li>
          <li>
            <strong>{gameResponse.game.home_team}:</strong>{" "}
            {gameResponse.game.home_top_projected_scorer
              ? `${gameResponse.game.home_top_projected_scorer.player_name} (${(gameResponse.game.home_top_projected_scorer.model_probability * 100).toFixed(1)}%)`
              : "Projection unavailable"}
          </li>
        </ul>
      </section>

      <section className="card stack-gap">
        <h2>Top 3 plays for this game</h2>
        <p className="helper-text">Best balanced plays using a blended probability + betting value ranking.</p>
        {!availability.projections_available ? (
          <p className="empty-state">This game is scheduled, but projections are not available yet.</p>
        ) : !availability.odds_available ? (
          <p className="empty-state">Projections are available, but market odds are not posted yet.</p>
        ) : topPlays.length === 0 ? (
          <p className="empty-state">No balanced Top 3 plays are qualified yet for this game.</p>
        ) : (
          <div className="recommendation-grid">
            {topPlays.map((pick, index) => (
              <RecommendationCard key={pick.player_id} recommendation={pick} rank={index + 1} />
            ))}
          </div>
        )}
      </section>

      <section className="card stack-gap featured-best-bet">
        <h2>Best bet</h2>
        <p className="helper-text">The single strongest overall play from the blended probability + value model.</p>
        {!availability.projections_available ? (
          <p className="empty-state">This game is scheduled, but projections are not available yet.</p>
        ) : !availability.odds_available ? (
          <p className="empty-state">Projections are available, but market odds are not posted yet.</p>
        ) : !bestBet ? (
          <p className="empty-state">No best bet is qualified for this game yet.</p>
        ) : (
          <RecommendationCard recommendation={bestBet} />
        )}
      </section>

      {underdogPlay && (
        <section className="card stack-gap featured-underdog">
          <h2>Underdog value play</h2>
          <p className="helper-text">A higher-risk, higher-payout option with positive EV and edge.</p>
          <RecommendationCard recommendation={underdogPlay} />
        </section>
      )}
    </main>
  );
}
