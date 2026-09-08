import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'Genjutsu — Unlimited',
  description: 'Unlimited free Higgsfield Genjutsu video generation',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen bg-ink bg-grad-dark text-zinc-100 antialiased">
        {children}
      </body>
    </html>
  );
}
