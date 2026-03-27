import Link from "next/link";
import { DatePickerForm } from "../../components/date-picker-form";
import { AppShellHeader } from "../../components/app-shell-header";
import { PageHeader } from "../../components/page-header";
import { RecommendationCard } from "../../components/recommendation-card";
import { fetchRecommendationHistory, fetchRecommendationHistoryAvailability, getCurrentUtcDate, recommendationHistoryExportUrl, resolveDisplayTimezone } from "../../lib/api";
import { Recommendation } from "../../lib/interfaces";
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

  const historyAvailability = await fetchRecommendationHistoryAvailability(selectedDate, selectedMarket);
  const historyResponse = await fetchRecommendationHistory(selectedDate, selectedMarket);
  const snapshot = historyResponse.snapshots[0];
  const topOverallSummary = summarizeStatuses(snapshot?.top_overall ?? []);

  return (
    <main className="page stack-gap-lg">
      <AppShellHeader
        activeNav="history"
        selectedDate={selectedDate}
        displayTimezone={displayTimezone}
        selectedMarket={selectedMarket}
        marketPath="/history"
        utilityLinks={[
          {
            href: `/slate?date=${encodeURIComponent(selectedDate)}&timezone=${encodeURIComponent(displayTimezone)}&market=${selectedMarket}`,
            label: "Back to Slate",
          },
        ]}
      />
      <PageHeader
        title="Historical Picks"
        description="Evaluate locked snapshots, outcomes, and export-ready performance data."
        contextChips={[`Market · ${marketTitle}`, `Date · ${selectedDate}`, "Mode · Stored Snapshots"]}
      />

      <section className="card stack-gap">
        <h2>Change date</h2>
        <DatePickerForm
          defaultDate={selectedDate}
          minDate={historyAvailability.min_available_date ?? selectedDate}
          maxDate={historyAvailability.max_available_date ?? selectedDate}
          submitLabel="Load historical picks"
          actionPath="/history"
          market={selectedMarket}
        />
        <p className="helper-text">
          Saved snapshot dates: {historyAvailability.available_dates.length > 0 ? historyAvailability.available_dates.join(", ") : "none yet"}.
        </p>
        <p className="helper-text">Lock cutoff (ET): {historyResponse.lock_cutoff_et ? new Date(historyResponse.lock_cutoff_et).toLocaleString("en-US", { timeZone: "America/New_York" }) : "Not available"}</p>
        {historyAvailability.available_dates.length > 0 && (
          <div className="stack-gap-sm">
            <h3>Browse saved dates</h3>
            <div className="stack-gap-sm">
              {historyAvailability.available_dates.map((availableDate) => (
                <Link
                  key={availableDate}
                  href={`/history?date=${encodeURIComponent(availableDate)}&timezone=${encodeURIComponent(displayTimezone)}&market=${selectedMarket}`}
                  className="secondary-link"
                >
                  {availableDate === selectedDate ? `✓ ${availableDate}` : availableDate}
                </Link>
              ))}
            </div>
          </div>
        )}
      </section>

      <section className="card stack-gap">
        <h2>Status · {marketTitle} · {selectedDate}</h2>
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
          <Link href={recommendationHistoryExportUrl("xlsx", selectedDate, selectedMarket)} className="secondary-link">Export Excel (locked data)</Link>
        </div>
      </section>

      {!snapshot ? (
        <section className="card">
          <p className="empty-state">No locked historical picks are available for this date and market. Choose any saved date above.</p>
        </section>
      ) : (
        <>
          <section className="card stack-gap">
            <h2>Top 3 overall · {marketTitle}</h2>
            <StatusSummary summary={topOverallSummary} label="Top Overall Summary" />
            {snapshot.top_overall.length === 0 ? (
              <p className="empty-state">No stored overall picks for this snapshot.</p>
            ) : (
              <div className="recommendation-grid">
                {snapshot.top_overall.map((pick, index) => (
                  <HistoricalPickCard key={`${pick.game_id}-${pick.player_id}`} pick={pick} selectedMarket={selectedMarket} rank={index + 1} />
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
                  <h4>Top 3 Plays</h4>
                  <StatusSummary summary={summarizeStatuses(gameSnapshot.top_plays)} label="Top Plays Summary" />
                  {gameSnapshot.top_plays.length === 0 ? <p className="empty-state">No qualified top plays.</p> : (
                    <div className="recommendation-grid">
                      {gameSnapshot.top_plays.map((pick, index) => (
                        <HistoricalPickCard key={`top-${gameSnapshot.game.game_id}-${pick.player_id}`} pick={pick} selectedMarket={selectedMarket} rank={index + 1} />
                      ))}
                    </div>
                  )}
                  <h4>Best Bet</h4>
                  {gameSnapshot.best_bet ? <HistoricalPickCard pick={gameSnapshot.best_bet} selectedMarket={selectedMarket} /> : <p className="empty-state">No best bet stored.</p>}
                  <h4>Underdog Value Play</h4>
                  {gameSnapshot.underdog_value_play ? <HistoricalPickCard pick={gameSnapshot.underdog_value_play} selectedMarket={selectedMarket} /> : <p className="empty-state">No underdog value play stored.</p>}
                </div>
              </article>
            ))}
          </section>
        </>
      )}
    </main>
  );
}

function HistoricalPickCard({ pick, selectedMarket, rank }: { pick: Recommendation; selectedMarket: "first_goal" | "anytime"; rank?: number }) {
  return (
    <div className="stack-gap-sm">
      <div className={`history-result-badge history-result-${pick.result_status}`}>
        <strong>{pick.result_status.toUpperCase()}</strong>
        {pick.actual_result_detail ? ` · ${pick.actual_result_detail}` : ""}
      </div>
      <RecommendationCard recommendation={pick} rank={rank} market={selectedMarket} />
    </div>
  );
}

function summarizeStatuses(picks: Recommendation[]): { hit: number; miss: number; pending: number } {
  return picks.reduce(
    (acc, pick) => {
      if (pick.result_status === "hit") acc.hit += 1;
      else if (pick.result_status === "miss") acc.miss += 1;
      else acc.pending += 1;
      return acc;
    },
    { hit: 0, miss: 0, pending: 0 },
  );
}

function StatusSummary({ summary, label }: { summary: { hit: number; miss: number; pending: number }; label: string }) {
  return (
    <p className="helper-text">
      {label}: Hits {summary.hit} · Misses {summary.miss} · Pending {summary.pending}
    </p>
  );
}
