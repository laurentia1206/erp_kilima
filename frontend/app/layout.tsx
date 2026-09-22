import type { Metadata } from 'next';
import '@tabler/icons-webfont/tabler-icons.min.css';
import './globals.css';

export const metadata: Metadata = {
  metadataBase: new URL(process.env.APP_URL || (process.env.NODE_ENV === 'production'
    ? 'https://kilimaholdings.com'
    : 'http://127.0.0.1:3000')),
  title: 'ERP KILIMA HOLDINGS',
  description: 'Espace de gestion des sociétés Kilima Holdings',
  robots: { index: false, follow: false },
};
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="fr"><body>{children}</body></html>;
}
