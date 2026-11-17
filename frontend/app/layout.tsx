import type { Metadata, Viewport } from 'next';
import '@tabler/icons-webfont/tabler-icons.min.css';
import './globals.css';

export const metadata: Metadata = {
  metadataBase: new URL(process.env.APP_URL || (process.env.NODE_ENV === 'production'
    ? 'https://kilimaholdings.com'
    : 'http://127.0.0.1:3000')),
  title: 'ERP KILIMA HOLDINGS',
  description: 'Espace de gestion des sociétés Kilima Holdings',
  robots: { index: false, follow: false },
  appleWebApp: { capable: true, title: 'Kilima ERP', statusBarStyle: 'default' },
  icons: { apple: '/icons/apple-touch-icon.png' },
};
export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  viewportFit: 'cover',
  themeColor: '#176b61',
};
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="fr"><body>{children}</body></html>;
}
