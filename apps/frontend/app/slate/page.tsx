import Link from "next/link";
import { DatePickerForm } from "../../components/date-picker-form";
import { MarketToggle } from "../../components/market-toggle";
import { RecommendationCard } from "../../components/recommendation-card";
import { fetchDailyRecommendationsByDate, fetchDateAvailability, fetchGamesByDate, getCurrentUtcDate, resolveDisplayTimezone } from "../../lib/api";
import { marketLabel, resolveMarket } from "../../lib/market";

type SlatePageProps = {
  searchParams?: {
    date?: string;
    timezone?: string;
    market?: string;
  };
};

export default async function SlatePage({ searchParams }: SlatePageProps) {
  const selectedDate = searchParams?.date ?? getCurrentUtcDate();
  const selectedMarket = resolveMarket(searchParams?.market);
  const displayTimezone = resolveDisplayTimezone(searchParams?.timezone);
  const marketTitle = marketLabel(selectedMarket);
  const availability = await fetchDateAvailability(selectedDate, selectedMarket);

  if (!availability.valid_by_product_rule) {
    return (
      <main className="page">
        <h1>Daily Slate</h1>
        <section className="card stack-gap">
          <h2>Invalid date</h2>
          <ul className="candidate-list">
            {availability.messages.map((message) => (
              <li key={message}>{message}</li>
            ))}
          </ul>
          <DatePickerForm
            defaultDate={availability.min_allowed_date}
            minDate={availability.min_allowed_date}
            maxDate={availability.max_allowed_date}
            submitLabel="Reload slate"
            actionPath="/slate"
            market={selectedMarket}
          />
          <Link href="/" className="secondary-link">Back home</Link>
        </section>
      </main>
    );
  }

  if (!availability.schedule_available) {
    return (
      <main className="page stack-gap-lg">
        <header>
          <h1>Daily Slate</h1>
          <p className="subtitle">{selectedDate} · Scheduled games and value picks</p>
        </header>

        <section className="card stack-gap">
          <h2>Change date</h2>
          <DatePickerForm
            defaultDate={selectedDate}
            minDate={availability.min_allowed_date}
            maxDate={availability.max_allowed_date}
            submitLabel="Update slate"
            actionPath="/slate"
            market={selectedMarket}
          />
        </section>

        <section className="card stack-gap">
          <h2>No scheduled games</h2>
          <ul className="candidate-list">
            {availability.messages.map((message) => (
              <li key={message}>{message}</li>
            ))}
          </ul>
        </section>
      </main>
    );
  }

  const gamesResponse = await fetchGamesByDate(selectedDate, displayTimezone, selectedMarket);
  const shouldLoadRecommendations = availability.projections_available && availability.odds_available;
  const dailyRecommendations = shouldLoadRecommendations ? await fetchDailyRecommendationsByDate(selectedDate, selectedMarket) : null;

  return (
    <main className="page stack-gap-lg">
      <header>
        <h1>Daily Slate</h1>
        <p className="subtitle">{selectedDate} · {marketTitle} market</p>
        <MarketToggle selectedDate={selectedDate} displayTimezone={displayTimezone} selectedMarket={selectedMarket} path="/slate" />
        <Link href={`/history?date=${selectedDate}&timezone=${encodeURIComponent(displayTimezone)}&market=${selectedMarket}`} className="secondary-link">View historical picks</Link>
      </header>

      <section className="card stack-gap">
        <h2>Change date</h2>
        <DatePickerForm
          defaultDate={selectedDate}
          minDate={availability.min_allowed_date}
          maxDate={availability.max_allowed_date}
          submitLabel="Update slate"
          actionPath="/slate"
          market={selectedMarket}
        />
      </section>

      {availability.messages.length > 0 && availability.status !== "ready" && (
        <section className="card stack-gap">
          <h2>Data updates</h2>
          <ul className="candidate-list">
            {availability.messages.map((message) => (
              <li key={message}>{message}</li>
            ))}
          </ul>
        </section>
      )}

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
        <h2>Top 3 overall value picks · {marketTitle}</h2>
        {!availability.projections_available ? (
          <p className="empty-state">Schedule is posted, but projections are still pending for this date.</p>
        ) : !availability.odds_available ? (
          <p className="empty-state">Projections are ready, but market odds are not posted yet.</p>
        ) : !dailyRecommendations || dailyRecommendations.recommendations.length === 0 ? (
          <p className="empty-state">No value picks available for {selectedDate}.</p>
        ) : (
          <div className="recommendation-grid">
            {dailyRecommendations.recommendations.slice(0, 3).map((pick, index) => (
              <RecommendationCard key={`${pick.game_id}-${pick.player_id}`} recommendation={pick} rank={index + 1} />
            ))}
          </div>
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
              <Link href={`/games/${game.game_id}?date=${selectedDate}&timezone=${encodeURIComponent(displayTimezone)}&market=${selectedMarket}`} key={game.game_id} className="card game-card-link stack-gap-sm">
                <p className="helper-text">{game.display_game_time ?? new Date(game.game_time).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", timeZone: displayTimezone })} {game.display_timezone ?? displayTimezone}</p>
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
