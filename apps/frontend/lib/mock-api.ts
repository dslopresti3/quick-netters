import { ALLOWED_DATES, mockDetailsByGameAndDate, mockSlateByDate, mockTopPicksByDate } from "./mock-data";
import type { GameDetail, GameSlateCard, ValuePick } from "./interfaces";

const SIMULATED_LATENCY_MS = 400;

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

export function isAllowedDate(date: string): boolean {
  return date === ALLOWED_DATES.today || date === ALLOWED_DATES.tomorrow;
}

export function getDefaultDate(): string {
  return ALLOWED_DATES.today;
}

export function getAllowedDateBounds() {
  return { min: ALLOWED_DATES.today, max: ALLOWED_DATES.tomorrow };
}

export async function fetchSlateByDate(date: string): Promise<GameSlateCard[]> {
  await sleep(SIMULATED_LATENCY_MS);

  if (!isAllowedDate(date)) {
    throw new Error("Invalid date. Please select today or tomorrow.");
  }

  return mockSlateByDate[date] ?? [];
}

export async function fetchTopPicksByDate(date: string): Promise<ValuePick[]> {
  await sleep(SIMULATED_LATENCY_MS);

  if (!isAllowedDate(date)) {
    throw new Error("Invalid date. Please select today or tomorrow.");
  }

  return mockTopPicksByDate[date] ?? [];
}

export async function fetchGameDetail(gameId: string, date: string): Promise<GameDetail | null> {
  await sleep(SIMULATED_LATENCY_MS);

  if (!isAllowedDate(date)) {
    throw new Error("Invalid date. Please select today or tomorrow.");
  }

  return mockDetailsByGameAndDate[date]?.[gameId] ?? null;
}

// NOTE: Keep this API surface stable so we can replace mock data with backend calls later.
