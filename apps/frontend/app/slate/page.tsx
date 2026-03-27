import Link from "next/link";
import { DatePickerForm } from "../../components/date-picker-form";
import { AppShellHeader } from "../../components/app-shell-header";
import { PageHeader } from "../../components/page-header";
import { RecommendationCard } from "../../components/recommendation-card";
import { fetchDailyRecommendationsByDate, fetchDateAvailability, fetchGamesByDate, getCurrentUtcDate, resolveDisplayTimezone } from "../../lib/api";
import { Recommendation } from "../../lib/interfaces";
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
      <main className={`page stack-gap-lg market-theme-${selectedMarket}`}>
        <AppShellHeader
          activeNav="slate"
          selectedDate={selectedDate}
          displayTimezone={displayTimezone}
          selectedMarket={selectedMarket}
          marketPath="/slate"
        />
        <PageHeader
          title="Daily Slate"
          description="Track today’s board and quickly pivot by market or date."
          contextChips={[`Market · ${marketTitle}`, `Date · ${selectedDate}`]}
          market={selectedMarket}
        />
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
      <main className={`page stack-gap-lg market-theme-${selectedMarket}`}>
        <AppShellHeader
          activeNav="slate"
          selectedDate={selectedDate}
          displayTimezone={displayTimezone}
          selectedMarket={selectedMarket}
          marketPath="/slate"
        />
        <PageHeader
          title="Daily Slate"
          description="Scheduled games and value picks for the selected board."
          contextChips={[`Market · ${marketTitle}`, `Date · ${selectedDate}`]}
          market={selectedMarket}
        />

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
  const recommendationsByGame = (dailyRecommendations?.recommendations ?? []).reduce<Record<string, Recommendation[]>>((acc, pick) => {
    if (!acc[pick.game_id]) {
      acc[pick.game_id] = [];
    }
    acc[pick.game_id].push(pick);
    return acc;
  }, {});

  return (
    <main className={`page stack-gap-lg slate-page market-theme-${selectedMarket}`}>
      <AppShellHeader
        activeNav="slate"
        selectedDate={selectedDate}
        displayTimezone={displayTimezone}
        selectedMarket={selectedMarket}
        marketPath="/slate"
        utilityLinks={[
          {
            href: `/history?date=${selectedDate}&timezone=${encodeURIComponent(displayTimezone)}&market=${selectedMarket}`,
            label: "History",
          },
        ]}
      />
      <PageHeader
        title="Daily Slate"
        description="Live slate intelligence with top model-driven value opportunities."
        contextChips={[`Market · ${marketTitle}`, `Date · ${selectedDate}`, `Timezone · ${displayTimezone}`]}
        market={selectedMarket}
      />

      <section className="card slate-overview-card stack-gap">
        <div className="slate-overview-header">
          <div className="stack-gap-sm">
            <p className="slate-overview-kicker">Slate overview</p>
            <h2>{marketTitle} board for {selectedDate}</h2>
            <p className="helper-text">Quickly scan board depth, featured model value, and per-matchup opportunities.</p>
          </div>
          <div className="hero-chip-row">
            <span className="hero-chip">Selected Market · {marketTitle}</span>
            <span className="hero-chip">Selected Date · {selectedDate}</span>
            <span className="hero-chip">Display TZ · {displayTimezone}</span>
          </div>
        </div>
        <div className="slate-overview-metrics">
          <article className="slate-overview-metric">
            <p className="helper-text">Games on slate</p>
            <strong>{gamesResponse.games.length}</strong>
          </article>
          <article className="slate-overview-metric">
            <p className="helper-text">Overall featured picks</p>
            <strong>{Math.min(dailyRecommendations?.recommendations.length ?? 0, 3)}</strong>
          </article>
          <article className="slate-overview-metric">
            <p className="helper-text">Data status</p>
            <strong>{availability.status === "ready" ? "Ready" : "Updating"}</strong>
          </article>
        </div>
        <div className="slate-overview-controls">
          <h3>Change date</h3>
          <DatePickerForm
            defaultDate={selectedDate}
            minDate={availability.min_allowed_date}
            maxDate={availability.max_allowed_date}
            submitLabel="Update slate"
            actionPath="/slate"
            market={selectedMarket}
          />
        </div>
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

      <section className="card stack-gap slate-featured-top">
        <div className="stack-gap-sm">
          <p className="slate-overview-kicker">Featured</p>
          <h2>Top 3 Overall · {marketTitle}</h2>
          <p className="helper-text">Highest-priority opportunities across the full board.</p>
        </div>
        {!availability.projections_available ? (
          <p className="empty-state">Schedule is posted, but projections are still pending for this date.</p>
        ) : !availability.odds_available ? (
          <p className="empty-state">Projections are ready, but market odds are not posted yet.</p>
        ) : !dailyRecommendations || dailyRecommendations.recommendations.length === 0 ? (
          <p className="empty-state">No value picks available for {selectedDate}.</p>
        ) : (
          <div className="recommendation-grid slate-featured-grid">
            {dailyRecommendations.recommendations.slice(0, 3).map((pick, index) => (
              <RecommendationCard
                key={`${pick.game_id}-${pick.player_id}`}
                recommendation={pick}
                rank={index + 1}
                market={selectedMarket}
                variant="top_play"
              />
            ))}
          </div>
        )}
      </section>

      <section className="slate-games-section stack-gap">
        <h2>Game Boards</h2>
        {gamesResponse.games.length === 0 ? (
          <article className="card">
            <p className="empty-state">No games on the slate for this date yet.</p>
          </article>
        ) : (
          <div className="slate-matchup-list">
            {gamesResponse.games.map((game) => (
              <article key={game.game_id} className="card slate-matchup-card stack-gap">
                <header className="slate-matchup-header">
                  <div className="stack-gap-sm">
                    <p className="context-chip">{game.display_game_time ?? new Date(game.game_time).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", timeZone: displayTimezone })} {game.display_timezone ?? displayTimezone}</p>
                    <h3>{game.away_team} @ {game.home_team}</h3>
                  </div>
                  <Link href={`/games/${game.game_id}?date=${selectedDate}&timezone=${encodeURIComponent(displayTimezone)}&market=${selectedMarket}`} className="secondary-link">
                    Open matchup
                  </Link>
                </header>
                {game.away_top_projected_scorer && game.home_top_projected_scorer ? (
                  <p className="helper-text">
                    Top projected scorers: {game.away_top_projected_scorer.player_name} ({(game.away_top_projected_scorer.model_probability * 100).toFixed(1)}%) · {game.home_top_projected_scorer.player_name} ({(game.home_top_projected_scorer.model_probability * 100).toFixed(1)}%)
                  </p>
                ) : (
                  <p className="helper-text">Top projected scorer per team will appear once projections are available.</p>
                )}
                {!availability.projections_available ? (
                  <p className="empty-state">Per-game picks will populate when projections are posted.</p>
                ) : !availability.odds_available ? (
                  <p className="empty-state">Per-game picks will populate when market odds are posted.</p>
                ) : (recommendationsByGame[game.game_id]?.length ?? 0) === 0 ? (
                  <p className="empty-state">No model value picks for this matchup currently.</p>
                ) : (
                  <div className="recommendation-grid slate-matchup-grid">
                    {recommendationsByGame[game.game_id].slice(0, 3).map((pick, index) => (
                      <RecommendationCard
                        key={`${game.game_id}-${pick.player_id}`}
                        recommendation={pick}
                        rank={index + 1}
                        market={selectedMarket}
                        variant="top_play"
                      />
                    ))}
                  </div>
                )}
              </article>
            ))}
          </div>
        )}
      </section>
    </main>
  );
}
