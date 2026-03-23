import type {
  DailyRecommendationsResponse,
  DateAvailabilityResponse,
  GameRecommendationsResponse,
  GamesResponse,
} from "./interfaces";

const API_BASE_URL = process.env.API_BASE_URL ?? "http://127.0.0.1:8000";

export const formatDate = (date: Date): string => date.toISOString().slice(0, 10);

export function getCurrentUtcDate(): string {
  return formatDate(new Date());
}

async function fetchJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: { Accept: "application/json" },
    next: { revalidate: 0 },
  });

  if (!response.ok) {
    let detail = `Request failed with status ${response.status}`;

    try {
      const body = await response.json();
      if (typeof body?.detail === "string") {
        detail = body.detail;
      }
    } catch {
      // no-op: keep generic detail
    }

    throw new Error(detail);
  }

  return response.json() as Promise<T>;
}

export async function fetchDateAvailability(date: string): Promise<DateAvailabilityResponse> {
  return fetchJson<DateAvailabilityResponse>(`/availability/date?date=${encodeURIComponent(date)}`);
}

export async function fetchGamesByDate(date: string): Promise<GamesResponse> {
  return fetchJson<GamesResponse>(`/games?date=${encodeURIComponent(date)}`);
}

export async function fetchDailyRecommendationsByDate(date: string): Promise<DailyRecommendationsResponse> {
  return fetchJson<DailyRecommendationsResponse>(`/recommendations/daily?date=${encodeURIComponent(date)}`);
}

export async function fetchGameRecommendations(gameId: string, date: string): Promise<GameRecommendationsResponse | null> {
  try {
    return await fetchJson<GameRecommendationsResponse>(`/recommendations/game?game_id=${encodeURIComponent(gameId)}&date=${encodeURIComponent(date)}`);
  } catch (error) {
    if (error instanceof Error && error.message.toLowerCase().includes("not found")) {
      return null;
    }
    throw error;
  }
}
