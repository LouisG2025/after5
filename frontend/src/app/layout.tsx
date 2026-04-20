import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Albert Dashboard",
  description: "After5 WhatsApp agent observability",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="h-full bg-zinc-950 text-zinc-100">{children}</body>
    </html>
  );
}
