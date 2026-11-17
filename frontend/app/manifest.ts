import type { MetadataRoute } from 'next';

// Manifeste PWA : rend l'ERP installable sur téléphone (« Ajouter à
// l'écran d'accueil »). Nécessite le HTTPS en production.
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: 'ERP KILIMA HOLDINGS',
    short_name: 'Kilima ERP',
    description: 'Espace de gestion des sociétés Kilima Holdings',
    start_url: '/',
    display: 'standalone',
    orientation: 'portrait',
    background_color: '#f4f7f6',
    theme_color: '#176b61',
    lang: 'fr',
    icons: [
      { src: '/icons/icone-192.png', sizes: '192x192', type: 'image/png' },
      { src: '/icons/icone-512.png', sizes: '512x512', type: 'image/png' },
      { src: '/icons/icone-maskable-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
    ],
  };
}
