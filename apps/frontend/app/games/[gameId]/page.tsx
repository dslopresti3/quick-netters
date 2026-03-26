import Link from "next/link";
import { MarketToggle } from "../../../components/market-toggle";
import { RecommendationCard } from "../../../components/recommendation-card";
import type { Recommendation, TeamProjectionLeader } from "../../../lib/interfaces";
import { fetchDateAvailability, fetchGameRecommendations, getCurrentUtcDate, resolveDisplayTimezone } from "../../../lib/api";
import { marketLabel, resolveMarket } from "../../../lib/market";

type GameDetailPageProps = {
  params: {
    gameId: string;
  };
  searchParams?: {
    date?: string;
    timezone?: string;
    market?: string;
  };
};

function formatProjectedGoalTotal(modelProbability: number): string {
  return modelProbability.toFixed(2);
}

function formatProbabilityPercent(probability: number): string {
  return `${(probability * 100).toFixed(1)}%`;
}

function normalizeTeamName(value?: string): string {
  return (value ?? "").trim().toLowerCase();
}

function resolveTeamLeader(
  recommendations: Recommendation[],
  fallbackLeader: TeamProjectionLeader | undefined,
  teamName: string,
): TeamProjectionLeader | undefined {
  const normalizedTeamName = normalizeTeamName(teamName);

  const topFromRecommendations = recommendations
    .filter((recommendation) => {
      const recommendationTeam = normalizeTeamName(recommendation.player_team ?? recommendation.team_name);
      return recommendationTeam === normalizedTeamName;
    })
    .sort((a, b) => b.model_probability - a.model_probability)[0];

  if (topFromRecommendations) {
    return {
      team: teamName,
      player_id: topFromRecommendations.player_id,
      player_name: topFromRecommendations.player_name,
      player_team: topFromRecommendations.player_team,
      team_name: topFromRecommendations.team_name,
      model_probability: topFromRecommendations.model_probability,
    };
  }

  return fallbackLeader;
}

function RecommendationSection({
  title,
  description,
  picks,
  emptyState,
  featuredClassName,
  ranked = false,
  selectedMarket,
}: {
  title: string;
  description: string;
  picks: Recommendation[];
  emptyState: string;
  featuredClassName?: string;
  ranked?: boolean;
  selectedMarket: "first_goal" | "anytime";
}) {
  return (
    <section className={`card stack-gap recommendation-panel${featuredClassName ? ` ${featuredClassName}` : ""}`}>
      <h2>{title}</h2>
      <p className="helper-text">{description}</p>
      {picks.length === 0 ? (
        <p className="empty-state">{emptyState}</p>
      ) : picks.length === 1 ? (
        <RecommendationCard recommendation={picks[0]} rank={ranked ? 1 : undefined} market={selectedMarket} />
      ) : (
        <div className="recommendation-grid">
          {picks.map((pick, index) => (
            <RecommendationCard key={pick.player_id} recommendation={pick} rank={ranked ? index + 1 : undefined} market={selectedMarket} />
          ))}
        </div>
      )}
    </section>
  );
}

export default async function GameDetailPage({ params, searchParams }: GameDetailPageProps) {
  const selectedDate = searchParams?.date ?? getCurrentUtcDate();
  const selectedMarket = resolveMarket(searchParams?.market);
  const selectedMarketLabel = marketLabel(selectedMarket);
  const displayTimezone = resolveDisplayTimezone(searchParams?.timezone);
  const availability = await fetchDateAvailability(selectedDate, selectedMarket);

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
          <Link href={`/slate?date=${availability.min_allowed_date}&timezone=${encodeURIComponent(displayTimezone)}&market=${selectedMarket}`} className="secondary-link">Back to Daily Slate</Link>
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
        <Link href={`/slate?date=${selectedDate}&timezone=${encodeURIComponent(displayTimezone)}&market=${selectedMarket}`} className="secondary-link">Back to Daily Slate</Link>
      </main>
    );
  }

  const gameResponse = await fetchGameRecommendations(params.gameId, selectedDate, displayTimezone, selectedMarket);

  if (!gameResponse) {
    return (
      <main className="page stack-gap">
        <h1>Game detail</h1>
        <section className="card">
          <p className="empty-state">No game detail exists for this matchup and date yet.</p>
        </section>
        <Link href={`/slate?date=${selectedDate}&timezone=${encodeURIComponent(displayTimezone)}&market=${selectedMarket}`} className="secondary-link">Back to Daily Slate</Link>
      </main>
    );
  }

  const topPlays = gameResponse.top_plays ?? gameResponse.recommendations.slice(0, 3);
  const bestBet = gameResponse.best_bet;
  const underdogPlay = gameResponse.underdog_value_play;
  const awayTeamLeader = resolveTeamLeader(
    gameResponse.recommendations,
    gameResponse.game.away_top_projected_scorer,
    gameResponse.game.away_team,
  );
  const homeTeamLeader = resolveTeamLeader(
    gameResponse.recommendations,
    gameResponse.game.home_top_projected_scorer,
    gameResponse.game.home_team,
  );
  const featuredProjectionRows = [
    { team: gameResponse.game.away_team, leader: awayTeamLeader },
    { team: gameResponse.game.home_team, leader: homeTeamLeader },
  ];
  const featuredScorerLabel = selectedMarket === "anytime" ? "Top projected anytime scorer" : "Top projected first-goal scorer";
  const projectionMetricLabel = selectedMarket === "anytime" ? "Anytime scoring probability" : "First-goal probability";

  return (
    <main className="page stack-gap-lg game-detail-page">
      <header className="stack-gap-sm">
        <p className="subtitle">Date: {gameResponse.date} · Market: {selectedMarketLabel}</p>
        <h1>{gameResponse.game.away_team} @ {gameResponse.game.home_team}</h1>
        <p className="helper-text">Start {gameResponse.game.display_game_time ?? new Date(gameResponse.game.game_time).toLocaleString("en-US", { timeZone: displayTimezone })} {gameResponse.game.display_timezone ?? displayTimezone}</p>
        <MarketToggle selectedDate={selectedDate} displayTimezone={displayTimezone} selectedMarket={selectedMarket} path={`/games/${params.gameId}`} />
        <Link href={`/slate?date=${selectedDate}&timezone=${encodeURIComponent(displayTimezone)}&market=${selectedMarket}`} className="secondary-link">← Back to Daily Slate</Link>
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

      <section className="card stack-gap featured-scorer-summary">
        <div className="featured-summary-header">
          <h2>{featuredScorerLabel}s by team</h2>
          <p className="helper-text">Quick matchup view of each team&apos;s top projected scorer for the selected market.</p>
        </div>
        <ul className="featured-scorer-list">
          {featuredProjectionRows.map(({ team, leader }) => (
            <li key={team} className="featured-scorer-row">
              {leader ? (
                <div>
                  <p className="featured-scorer-rank">{featuredScorerLabel}</p>
                  <p className="featured-scorer-name">{leader.player_name}</p>
                  <p className="helper-text">{leader.team_name ?? leader.player_team ?? team}</p>
                </div>
              ) : (
                <div>
                  <p className="featured-scorer-rank">{featuredScorerLabel}</p>
                  <p className="featured-scorer-name">{team}</p>
                  <p className="helper-text">Top projected scorer unavailable.</p>
                </div>
              )}
              <div className="featured-scorer-metric">
                <span className="metric-label">{projectionMetricLabel}</span>
                {leader ? (
                  <>
                    <strong>{formatProbabilityPercent(leader.model_probability)}</strong>
                    <span className="helper-text">Model output: {formatProjectedGoalTotal(leader.model_probability)}</span>
                  </>
                ) : (
                  <strong>-</strong>
                )}
              </div>
            </li>
          ))}
        </ul>
      </section>

      {!availability.projections_available ? (
        <section className="card stack-gap">
          <h2>Recommendations · {selectedMarketLabel}</h2>
          <p className="empty-state">This game is scheduled, but projections are not available yet.</p>
        </section>
      ) : !availability.odds_available ? (
        <section className="card stack-gap">
          <h2>Recommendations · {selectedMarketLabel}</h2>
          <p className="empty-state">Projections are available, but market odds are not posted yet.</p>
        </section>
      ) : (
        <section className="recommendation-hub stack-gap">
          <RecommendationSection
            title="Top 3 Plays"
            selectedMarket={selectedMarket}
            description="Best balanced plays using a blended probability + betting value ranking."
            picks={topPlays}
            emptyState="No balanced Top 3 plays are qualified yet for this game."
            ranked
          />
          <div className="featured-recommendations-grid">
            <RecommendationSection
              title="Best Bet"
              selectedMarket={selectedMarket}
              description="The single strongest overall play from the blended probability + value model."
              picks={bestBet ? [bestBet] : []}
              emptyState="No best bet is qualified for this game yet."
              featuredClassName="featured-best-bet"
            />
            <RecommendationSection
              title="Underdog Value Play"
              selectedMarket={selectedMarket}
              description="A higher-risk, higher-payout option with positive EV and edge."
              picks={underdogPlay ? [underdogPlay] : []}
              emptyState="No underdog value play is qualified for this game yet."
              featuredClassName="featured-underdog"
            />
          </div>
        </section>
      )}
    </main>
  );
}
