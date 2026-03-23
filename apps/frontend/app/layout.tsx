import type { Metadata } from "next";
import "./styles.css";

export const metadata: Metadata = {
  title: "Quick Netters",
  description: "Daily tennis decision support with mock-first scaffolding.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
