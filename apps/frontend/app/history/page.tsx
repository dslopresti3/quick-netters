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
  const availableDates = historyAvailability.available_dates;

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
        description="Archive and review locked picks, market outcomes, and historical recommendation quality."
        contextChips={[`Market · ${marketTitle}`, `Archive Date · ${selectedDate}`, "Mode · Locked Snapshots"]}
      >
        <div className="history-hero-meta-grid">
          <div className="history-meta-card">
            <p className="history-meta-kicker">Selected Archive Date</p>
            <strong>{selectedDate}</strong>
          </div>
          <div className="history-meta-card">
            <p className="history-meta-kicker">Market</p>
            <strong>{marketTitle}</strong>
          </div>
          <div className="history-meta-card">
            <p className="history-meta-kicker">Snapshot Status</p>
            <strong>{snapshot ? "Stored and reviewable" : historyResponse.is_locked ? "Locked, snapshot unavailable" : "Live, pending lock"}</strong>
          </div>
        </div>
      </PageHeader>

      <section className="card history-controls-card stack-gap">
        <div className="history-section-header">
          <div className="stack-gap-sm">
            <p className="history-section-kicker">Archive Controls</p>
            <h2>Browse by date and market</h2>
          </div>
          <div className="history-export-actions">
            <Link href={recommendationHistoryExportUrl("json", selectedDate, selectedMarket)} className="secondary-link">Export JSON</Link>
            <Link href={recommendationHistoryExportUrl("csv", selectedDate, selectedMarket)} className="secondary-link">Export CSV</Link>
            <Link href={recommendationHistoryExportUrl("xlsx", selectedDate, selectedMarket)} className="secondary-link">Export Excel</Link>
          </div>
        </div>

        <div className="history-control-panels">
          <div className="history-control-panel stack-gap-sm">
            <h3>Select date</h3>
            <DatePickerForm
              defaultDate={selectedDate}
              minDate={historyAvailability.min_available_date ?? selectedDate}
              maxDate={historyAvailability.max_available_date ?? selectedDate}
              submitLabel="Load historical picks"
              actionPath="/history"
              market={selectedMarket}
            />
            <p className="helper-text">Saved snapshots: {availableDates.length > 0 ? availableDates.length : 0} dates.</p>
            <p className="helper-text">
              {historyAvailability.min_available_date && historyAvailability.max_available_date
                ? `Available range: ${historyAvailability.min_available_date} to ${historyAvailability.max_available_date}.`
                : "No archived date range is available yet."}
            </p>
          </div>

          <div className="history-control-panel stack-gap-sm">
            <h3>Quick archive dates</h3>
            {availableDates.length > 0 ? (
              <div className="history-quick-date-grid">
                {availableDates.map((availableDate) => (
                  <Link
                    key={availableDate}
                    href={`/history?date=${encodeURIComponent(availableDate)}&timezone=${encodeURIComponent(displayTimezone)}&market=${selectedMarket}`}
                    className={`history-date-pill${availableDate === selectedDate ? " is-active" : ""}`}
                  >
                    {availableDate === selectedDate ? `Selected · ${availableDate}` : availableDate}
                  </Link>
                ))}
              </div>
            ) : (
              <p className="empty-state">No saved archive dates yet.</p>
            )}
          </div>
        </div>
      </section>
      <section className="card history-status-card stack-gap">
        <h2>Archive snapshot status</h2>
        {snapshot ? (
          <p className="helper-text"><strong>Locked snapshot.</strong> Created at {new Date(snapshot.snapshot_created_at).toLocaleString("en-US", { timeZone: "America/New_York" })} ET.</p>
        ) : historyResponse.is_locked ? (
          <p className="helper-text"><strong>Locked.</strong> No snapshot available yet (check backend job execution).</p>
        ) : (
          <p className="helper-text"><strong>Live (not locked yet).</strong> Historical snapshots are created 1 hour before the first game starts in ET.</p>
        )}
        <p className="helper-text">Lock cutoff (ET): {historyResponse.lock_cutoff_et ? new Date(historyResponse.lock_cutoff_et).toLocaleString("en-US", { timeZone: "America/New_York" }) : "Not available"}</p>
      </section>

      {!snapshot ? (
        <section className="card">
          <p className="empty-state">No locked historical picks are available for this date and market. Choose any saved date above.</p>
        </section>
      ) : (
        <>
          <section className="card stack-gap">
            <div className="history-section-header">
              <div className="stack-gap-sm">
                <p className="history-section-kicker">Top Overall</p>
                <h2>Best historical picks · {marketTitle}</h2>
              </div>
              <StatusSummary summary={topOverallSummary} label="Top Overall Summary" />
            </div>
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
            <div className="history-section-header">
              <div className="stack-gap-sm">
                <p className="history-section-kicker">Game Archive</p>
                <h2>Game-level saved picks</h2>
              </div>
            </div>
            {snapshot.games.map((gameSnapshot) => (
              <article key={gameSnapshot.game.game_id} className="card stack-gap history-game-card">
                <div className="history-game-header">
                  <h3>{gameSnapshot.game.away_team} @ {gameSnapshot.game.home_team}</h3>
                  <p className="helper-text">Start {gameSnapshot.game.display_game_time ?? new Date(gameSnapshot.game.game_time).toLocaleString("en-US", { timeZone: displayTimezone })} {gameSnapshot.game.display_timezone ?? displayTimezone}</p>
                </div>
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
                  {gameSnapshot.best_bet ? <HistoricalPickCard pick={gameSnapshot.best_bet} selectedMarket={selectedMarket} variant="best_bet" /> : <p className="empty-state">No best bet stored.</p>}
                  <h4>Underdog Value Play</h4>
                  {gameSnapshot.underdog_value_play ? <HistoricalPickCard pick={gameSnapshot.underdog_value_play} selectedMarket={selectedMarket} variant="underdog_value" /> : <p className="empty-state">No underdog value play stored.</p>}
                </div>
              </article>
            ))}
          </section>
        </>
      )}
    </main>
  );
}

function HistoricalPickCard({
  pick,
  selectedMarket,
  rank,
  variant = "top_play",
}: {
  pick: Recommendation;
  selectedMarket: "first_goal" | "anytime";
  rank?: number;
  variant?: "top_play" | "best_bet" | "underdog_value";
}) {
  return (
    <div className="stack-gap-sm">
      <div className={`history-result-badge history-result-${pick.result_status}`}>
        <strong>{pick.result_status.toUpperCase()}</strong>
        {pick.actual_result_detail ? ` · ${pick.actual_result_detail}` : ""}
      </div>
      <RecommendationCard recommendation={pick} rank={rank} market={selectedMarket} variant={variant} />
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
    <div className="history-status-summary" aria-label={label}>
      <span className="history-status-chip history-status-chip-hit">Hits {summary.hit}</span>
      <span className="history-status-chip history-status-chip-miss">Misses {summary.miss}</span>
      <span className="history-status-chip history-status-chip-pending">Pending {summary.pending}</span>
    </div>
  );
}
