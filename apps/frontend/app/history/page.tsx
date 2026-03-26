import Link from "next/link";
import { DatePickerForm } from "../../components/date-picker-form";
import { MarketToggle } from "../../components/market-toggle";
import { RecommendationCard } from "../../components/recommendation-card";
import { fetchDateAvailability, fetchRecommendationHistory, getCurrentUtcDate, recommendationHistoryExportUrl, resolveDisplayTimezone } from "../../lib/api";
import { marketLabel, resolveMarket } from "../../lib/market";

type HistoryPageProps = {
  searchParams?: {
    date?: string;
    timezone?: string;
    market?: string;
  };
};

export default async function HistoryPage({ searchParams }: HistoryPageProps) {
  const selectedDate = searchParams?.date ?? getCurrentUtcDate();
  const selectedMarket = resolveMarket(searchParams?.market);
  const marketTitle = marketLabel(selectedMarket);
  const displayTimezone = resolveDisplayTimezone(searchParams?.timezone);

  const availability = await fetchDateAvailability(selectedDate, selectedMarket);
  const historyResponse = await fetchRecommendationHistory(selectedDate, selectedMarket);
  const snapshot = historyResponse.snapshots[0];

  return (
    <main className="page stack-gap-lg">
      <header>
        <h1>Historical Picks</h1>
        <p className="subtitle">Stored snapshots only · {selectedDate} · {marketTitle}</p>
        <MarketToggle selectedDate={selectedDate} displayTimezone={displayTimezone} selectedMarket={selectedMarket} path="/history" />
      </header>

      <section className="card stack-gap">
        <h2>Change date</h2>
        <DatePickerForm
          defaultDate={selectedDate}
          minDate={availability.min_allowed_date}
          maxDate={availability.max_allowed_date}
          submitLabel="Load historical picks"
          actionPath="/history"
          market={selectedMarket}
        />
        <p className="helper-text">Lock cutoff (ET): {historyResponse.lock_cutoff_et ? new Date(historyResponse.lock_cutoff_et).toLocaleString("en-US", { timeZone: "America/New_York" }) : "Not available"}</p>
      </section>

      <section className="card stack-gap">
        <h2>Status</h2>
        {snapshot ? (
          <p className="helper-text"><strong>Locked snapshot.</strong> Created at {new Date(snapshot.snapshot_created_at).toLocaleString("en-US", { timeZone: "America/New_York" })} ET.</p>
        ) : historyResponse.is_locked ? (
          <p className="helper-text"><strong>Locked.</strong> No snapshot available yet (check backend job execution).</p>
        ) : (
          <p className="helper-text"><strong>Live (not locked yet).</strong> Historical snapshots are created 1 hour before the first game starts in ET.</p>
        )}
        <div className="stack-gap-sm">
          <Link href={recommendationHistoryExportUrl("json", selectedDate, selectedMarket)} className="secondary-link">Export JSON (locked data)</Link>
          <Link href={recommendationHistoryExportUrl("csv", selectedDate, selectedMarket)} className="secondary-link">Export CSV (locked data)</Link>
        </div>
      </section>

      {!snapshot ? (
        <section className="card">
          <p className="empty-state">No locked historical picks are available for this date and market.</p>
        </section>
      ) : (
        <>
          <section className="card stack-gap">
            <h2>Top 3 overall · {marketTitle}</h2>
            {snapshot.top_overall.length === 0 ? (
              <p className="empty-state">No stored overall picks for this snapshot.</p>
            ) : (
              <div className="recommendation-grid">
                {snapshot.top_overall.map((pick, index) => (
                  <RecommendationCard key={`${pick.game_id}-${pick.player_id}`} recommendation={pick} rank={index + 1} />
                ))}
              </div>
            )}
          </section>

          <section className="stack-gap">
            <h2>Game-level picks</h2>
            {snapshot.games.map((gameSnapshot) => (
              <article key={gameSnapshot.game.game_id} className="card stack-gap">
                <h3>{gameSnapshot.game.away_team} @ {gameSnapshot.game.home_team}</h3>
                <p className="helper-text">Start {gameSnapshot.game.display_game_time ?? new Date(gameSnapshot.game.game_time).toLocaleString("en-US", { timeZone: displayTimezone })} {gameSnapshot.game.display_timezone ?? displayTimezone}</p>
                <div className="stack-gap">
                  <h4>Top 3 plays</h4>
                  {gameSnapshot.top_plays.length === 0 ? <p className="empty-state">No qualified top plays.</p> : (
                    <div className="recommendation-grid">
                      {gameSnapshot.top_plays.map((pick, index) => (
                        <RecommendationCard key={`top-${gameSnapshot.game.game_id}-${pick.player_id}`} recommendation={pick} rank={index + 1} />
                      ))}
                    </div>
                  )}
                  <h4>Best bet</h4>
                  {gameSnapshot.best_bet ? <RecommendationCard recommendation={gameSnapshot.best_bet} /> : <p className="empty-state">No best bet stored.</p>}
                  <h4>Underdog value play</h4>
                  {gameSnapshot.underdog_value_play ? <RecommendationCard recommendation={gameSnapshot.underdog_value_play} /> : <p className="empty-state">No underdog play stored.</p>}
                </div>
              </article>
            ))}
          </section>
        </>
      )}
    </main>
  );
}
