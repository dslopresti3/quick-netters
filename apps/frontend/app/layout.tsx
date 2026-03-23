import type { Metadata } from "next";
import "./styles.css";

export const metadata: Metadata = {
  title: "Quick Netters",
  description: "Daily tennis decision support with backend-driven slate availability.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
