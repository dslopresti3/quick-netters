"use client";

import { useRouter } from "next/navigation";
import { FormEvent, useState, useTransition } from "react";

type DatePickerFormProps = {
  defaultDate: string;
  minDate: string;
  maxDate: string;
  submitLabel: string;
  actionPath: string;
  market?: "first_goal" | "anytime";
};

export function DatePickerForm({ defaultDate, minDate, maxDate, submitLabel, actionPath, market = "first_goal" }: DatePickerFormProps) {
  const router = useRouter();
  const [selectedDate, setSelectedDate] = useState(defaultDate);
  const [isPending, startTransition] = useTransition();

  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const userTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "America/New_York";
    startTransition(() => {
      router.push(`${actionPath}?date=${selectedDate}&timezone=${encodeURIComponent(userTimezone)}&market=${market}`);
    });
  };

  return (
    <form className="date-picker-form" onSubmit={onSubmit}>
      <label htmlFor="date">Game date</label>
      <input
        id="date"
        name="date"
        type="date"
        value={selectedDate}
        min={minDate}
        max={maxDate}
        onChange={(event) => setSelectedDate(event.target.value)}
      />
      <button type="submit" disabled={isPending}>
        {isPending ? "Loading..." : submitLabel}
      </button>
    </form>
  );
}
