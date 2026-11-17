// Service worker minimal : rend l'application installable sans jamais
// mettre en cache les données de gestion (tout passe par le réseau).
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));
self.addEventListener('fetch', () => { /* réseau direct, aucun cache applicatif */ });
