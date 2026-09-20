"use strict";
const API = "/api";
let token = localStorage.getItem("kh_token") || null;
let me = null, societes = [], currentSocieteId = null;
let activeView = "accueil", navigationVersion = 0, toastTimer;
const pendingWrites = new Set();
function savedJSON(key, fallback) {
  try { return JSON.parse(localStorage.getItem(key)) || fallback; } catch { return fallback; }
}

// ── Helpers ──────────────────────────────────────────────────────────
const $ = (s) => document.querySelector(s);
const esc = (s) => (s == null ? "" : String(s).replace(/[&<>"]/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])));
const fmtUSD = (v) => new Intl.NumberFormat("fr-FR", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(v || 0) + " USD";

// Traduit les erreurs de validation FastAPI (detail = liste d'objets) en message lisible
const CHAMPS_FR = {
  code: "Code", nom: "Nom", prenom: "Prénom", type: "Type", email: "Email",
  password: "Mot de passe", designation: "Désignation", qte: "Quantité",
  prix_unitaire: "Prix unitaire", montant: "Montant", libelle: "Libellé",
  origine: "Origine", destination: "Destination", marchandise: "Marchandise",
  tonnage_prevu: "Tonnage prévu", tonnage_livre: "Tonnage livré",
  immatriculation: "Immatriculation", trajet: "Trajet", prix: "Prix",
  tiers_id: "Tiers", client_tiers_id: "Client", camion_id: "Camion", lignes: "Lignes",
};
function messageErreur(data, statusText) {
  if (!data) return statusText || "Erreur réseau.";
  const d = data.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) {
    return d.slice(0, 3).map((e) => {
      const brut = (e.loc || []).filter((x) => !["body", "query", "path"].includes(x)).pop();
      const champ = CHAMPS_FR[brut] || brut || "champ";
      let m = String(e.msg || "valeur invalide")
        .replace(/^Value error, /, "")
        .replace(/^Field required$/, "obligatoire")
        .replace(/^Input should be a valid \w+.*$/, "valeur invalide")
        .replace(/^String should have at least (\d+) characters?$/, "au moins $1 caractère(s)")
        .replace(/^String should have at most (\d+) characters?$/, "au plus $1 caractère(s)")
        .replace(/^String should match pattern.*$/, "valeur non autorisée")
        .replace(/^Input should be greater than (\d+)$/, "doit être supérieur à $1")
        .replace(/^Input should be greater than or equal to (\d+)$/, "doit être ≥ $1")
        .replace(/^List should have at least (\d+) item.*$/, "au moins $1 ligne(s)");
      return `${champ} : ${m}`;
    }).join(" · ");
  }
  try { return JSON.stringify(data); } catch { return statusText || "Erreur."; }
}

async function api(path, { method = "GET", body = null, form = false } = {}) {
  const headers = {};
  if (token) headers["Authorization"] = "Bearer " + token;
  let payload = null;
  if (form) payload = new URLSearchParams(body);
  else if (body) { headers["Content-Type"] = "application/json"; payload = JSON.stringify(body); }
  const writing = !["GET", "HEAD"].includes(method.toUpperCase());
  const key = method + path + payload;
  if (writing && pendingWrites.has(key)) throw new Error("Cette opération est déjà en cours. Patientez.");
  if (writing) pendingWrites.add(key);
  const requestedSociete = currentSocieteId;
  try {
    let res;
    try { res = await fetch(API + path, { method, headers, body: payload }); }
    catch { throw new Error(writing
      ? "Connexion interrompue. Vérifiez si l’opération a été enregistrée avant de réessayer."
      : "Le serveur est inaccessible. Vérifiez votre connexion puis réessayez."); }
    if (res.status === 401 && path !== "/auth/login") { logout(); throw new Error("Session expirée. Veuillez vous reconnecter."); }
    if (!writing && path.includes("societe_id=") && requestedSociete !== currentSocieteId)
      throw new Error("La société active a changé. Rechargez cet écran.");
    const ct = res.headers.get("content-type") || "";
    const data = ct.includes("json") ? await res.json() : null;
    if (!res.ok) {
      const error = new Error(res.status >= 500
        ? "Le serveur n’a pas pu terminer l’opération. Vérifiez son état avant de réessayer."
        : messageErreur(data, res.statusText));
      error.data=data; error.status=res.status; throw error;
    }
    return data;
  } finally { if (writing) pendingWrites.delete(key); }
}
function toast(msg, kind = "") {
  const t = $("#toast"); t.textContent = msg; t.className = "toast show " + kind;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.className = "toast"), kind === "ko" ? 6500 : 3500);
}
const myRoles = () => (societes.find((s) => s.id === currentSocieteId)?.roles) || [];
const has = (...rs) => rs.some((r) => myRoles().includes(r));
const statusLabels = { transformee:"Transformée en ordre", soumise:"Soumise", approuvee:"Approuvée", rejetee:"Rejetée", annulee:"Annulée", validee:"Validée", payee:"Payée", execute:"Exécuté", en_attente_info:"Précisions demandées", demande_validee:"Demande validée", en_attente:"En attente", terminee:"Terminée", cloturee:"Clôturée", brouillon:"Brouillon", partiellement_payee:"Partiellement payée", soldee:"Soldée", partiellement_recue:"Partiellement reçue", recue:"Reçue", envoyee:"Envoyée", justifiee:"Justifiée" };
const pill = (st) => `<span class="pill st-${esc(st || "")}">${esc(statusLabels[st] || (st || "").replace(/_/g, " "))}</span>`;

// ── Auth ─────────────────────────────────────────────────────────────
async function login() {
  if ($("#btn-login").disabled) return;
  $("#login-err").textContent = "";
  const email = $("#email").value.trim(), password = $("#password").value;
  if (!email || !password) { $("#login-err").textContent = "Email et mot de passe requis."; return; }
  $("#btn-login").disabled = true; $("#btn-login").textContent = "Connexion…";
  try {
    const d = await api("/auth/login", { method: "POST", form: true, body: { username: email, password } });
    token = d.access_token; localStorage.setItem("kh_token", token);
    await boot();
  } catch (e) { $("#login-err").textContent = e.message; }
  finally { $("#btn-login").disabled = false; $("#btn-login").textContent = "Se connecter"; }
}
function logout() {
  Pilotage.reset();
  token = null; localStorage.removeItem("kh_token");
  navigationVersion++;
  me = null; societes = []; currentSocieteId = null;
  $("#modal-root").replaceChildren();
  document.querySelectorAll(".view").forEach((v) => v.replaceChildren());
  $("#password").value = "";
  setMobileMenu(false);
  $("#app").classList.add("hidden"); $("#login").classList.remove("hidden");
}
async function boot() {
  me = await api("/auth/me");
  societes = await api("/societes");
  if (!societes.length) { logout(); throw new Error("Aucune société affectée à ce compte. Contactez votre administrateur."); }
  const savedSociete = localStorage.getItem("kh_societe_" + me.id);
  currentSocieteId = societes.some((s) => s.id === savedSociete) ? savedSociete : societes[0].id;
  $("#who-nm").textContent = me.nom + (me.prenom ? " " + me.prenom : "");
  $("#who-em").textContent = me.email;
  $("#avatar").textContent = (me.nom || "?").slice(0, 1).toUpperCase();
  const sel = $("#societe-select");
  sel.innerHTML = societes.map((s) => `<option value="${s.id}">${esc(s.nom)}</option>`).join("");
  sel.value = currentSocieteId;
  renderSidebar();
  $("#login").classList.add("hidden"); $("#app").classList.remove("hidden");
  await refreshBadge();
  Pilotage.badge();
  if (hasGlobal("COMPTABLE", "DFI")) refreshComptaBadge();
  // Un réceptionniste atterrit directement sur son tableau de bord hôtel
  const rolesTous = societes.flatMap((s) => s.roles);
  if (rolesTous.length && rolesTous.every((r) => r === "RECEPTIONNISTE")) go("hotel-reception");
  else go("accueil");
}

// ── Menu latéral dépliable (généré selon les rôles) ──────────────────
const hasGlobal = (...rs) => societes.some((s) => s.roles.some((r) => rs.includes(r)));
let collapsed = savedJSON("kh_collapsed", {});
const NAV = [
  { g: "Pilotage", items: [
    { v: "accueil", l: "Accueil", i: "ti-home" },
    { v: "dashboard", l: "Tableau de bord", i: "ti-layout-dashboard" }] },
  { g: "Approbations", items: [
    { v: "approbation", l: "Centre d'approbation", i: "ti-checks", badge: "appro" },
    { v: "nouvelle-req", l: "Nouvelle réquisition", i: "ti-file-plus" },
    { v: "requisitions", l: "Réquisitions", i: "ti-files" }] },
  { g: "Décaissement", items: [
    { v: "ordres", l: "Ordres de dépense", i: "ti-receipt" },
    { v: "avances", l: "Avances à justifier", i: "ti-cash" }] },
  { g: "Caisses (trésorerie)", items: [
    { v: "caisse", l: "Journal & soldes", i: "ti-book-2" },
    { v: "caisse-exec", l: "Décaissements à exécuter", i: "ti-arrow-bar-to-down", roles: ["CAISSIER_CENTRAL", "CAISSIER_VENDEUR", "DFI", "COMPTABLE"] },
    { v: "transferts", l: "Transferts", i: "ti-arrows-exchange", roles: ["CAISSIER_CENTRAL", "CAISSIER_VENDEUR", "COMPTABLE", "DFI"] }] },
  { g: "Point de vente", roles: ["CAISSIER_CENTRAL", "CAISSIER_VENDEUR", "COMPTABLE", "DFI"], items: [
    { v: "pos", l: "Écran de vente", i: "ti-cash-register" },
    { v: "tarifs-pos", l: "Tarifs & points de vente", i: "ti-tags", roles: ["COMPTABLE", "DFI"] }] },
  { g: "Achats", roles: ["COMPTABLE", "DFI"], items: [
    { v: "commandes", l: "Commandes fournisseurs", i: "ti-clipboard-list" },
    { v: "receptions", l: "Réceptions", i: "ti-truck-delivery", badge: "recv" },
    { v: "achats", l: "Factures d'achat", i: "ti-shopping-cart" }] },
  { g: "Ventes", roles: ["COMPTABLE", "DFI"], items: [
    { v: "devis", l: "Devis & commandes", i: "ti-file-description", badge: "devispo" },
    { v: "ventes", l: "Factures de vente", i: "ti-tag" },
    { v: "rapports-commercial", l: "Rapports", i: "ti-report-analytics" }] },
  { g: "Stock", roles: ["COMPTABLE", "DFI", "DG", "CAISSIER_CENTRAL"], items: [
    { v: "stock", l: "État du stock", i: "ti-packages" },
    { v: "depots", l: "Dépôts & transferts", i: "ti-building-warehouse" },
    { v: "articles", l: "Articles", i: "ti-box" }] },
  { g: "Transport", roles: ["COMPTABLE", "DFI", "DG"], items: [
    { v: "courses", l: "Fiches de course", i: "ti-steering-wheel", badge: "crs" },
    { v: "flotte", l: "Flotte & maintenance", i: "ti-truck" },
    { v: "contrats-transport", l: "Contrats de transport", i: "ti-writing-sign" },
    { v: "flotte-documents", l: "Documents & échéances", i: "ti-license" },
    { v: "carburant", l: "Suivi carburant", i: "ti-gas-station" },
    { v: "config-transport", l: "Configuration", i: "ti-settings" }] },
  { g: "Location d'engins", roles: ["COMPTABLE", "DFI", "DG", "ASSISTANT_TECH", "ASSISTANT_TECHNIQUE", "DT", "DISPATCHER"], items: [
    { v: "engins-parc", l: "Parc d'engins", i: "ti-backhoe" },
    { v: "engins-heures", l: "Heures prestées", i: "ti-clock-hour-4" },
    { v: "engins-rpe", l: "RPE & facturation", i: "ti-file-invoice" },
    { v: "carburant", l: "Suivi carburant", i: "ti-gas-station" },
    { v: "config-engins", l: "Configuration", i: "ti-settings" }] },
  { g: "Hôtel", roles: ["RECEPTIONNISTE", "CAISSIER_CENTRAL", "COMPTABLE", "DFI", "DG"], items: [
    { v: "hotel-reception", l: "Réception & séjours", i: "ti-bed" },
    { v: "hotel-chambres", l: "Chambres & ménage", i: "ti-door" },
    { v: "cuisine", l: "Cuisine & food cost", i: "ti-chef-hat" },
    { v: "config-hotel", l: "Configuration", i: "ti-settings" }] },
  { g: "Maintenance", roles: ["MAINTENANCIER", "DT", "ASSISTANT_TECHNIQUE", "COMPTABLE", "DFI", "DG"], items: [
    { v: "maintenance-parc", l: "Parc & échéances", i: "ti-gauge" },
    { v: "maintenance-interventions", l: "Interventions", i: "ti-tool" },
    { v: "flotte-documents", l: "Documents & échéances", i: "ti-license" },
    { v: "config-maintenance", l: "Configuration", i: "ti-settings" }] },
  { g: "Groupe", roles: ["DFI", "PRESIDENT", "COMPTABLE"], items: [
    { v: "intersociete", l: "Opérations intersociétés", i: "ti-affiliate" }] },
  { g: "Comptabilité", roles: ["COMPTABLE", "DFI"], items: [
    { v: "cockpit", l: "Cockpit financier", i: "ti-gauge" },
    { v: "compta", l: "Pièces en attente", i: "ti-file-invoice", badge: "compta" },
    { v: "saisie-od", l: "Saisir une écriture", i: "ti-pencil-plus" },
    { v: "grand-livre", l: "Grand livre", i: "ti-list-details" },
    { v: "lettrage", l: "Lettrage des tiers", i: "ti-link" },
    { v: "rapprochement", l: "Rapprochement bancaire", i: "ti-building-bank" },
    { v: "analytique", l: "Analytique", i: "ti-chart-pie" },
    { v: "balance", l: "Balance", i: "ti-scale" },
    { v: "etats", l: "États financiers", i: "ti-report-money" },
    { v: "plan-comptable", l: "Plan comptable & journaux", i: "ti-book-2" }] },
  { g: "Paramètres", items: [
    { v: "taux", l: "Taux du jour", i: "ti-currency-dollar" },
    { v: "config", l: "Paramétrage", i: "ti-adjustments", roles: ["DFI", "PRESIDENT", "ADMIN_SYS"] },
    { v: "administration", l: "Administration", i: "ti-shield-cog", roles: ["DFI", "PRESIDENT", "ADMIN_SYS"] }] },
];
function renderSidebar() {
  let h = "";
  for (const grp of NAV) {
    if (grp.roles && !hasGlobal(...grp.roles)) continue;
    const items = grp.items.filter((it) => !it.roles || hasGlobal(...it.roles));
    if (!items.length) continue;
    h += `<div class="nav-group ${collapsed[grp.g] ? "collapsed" : ""}">
      <button type="button" class="nav-group-hdr" aria-expanded="${!collapsed[grp.g]}" data-toggle="${grp.g}">${grp.g}<i class="ti ti-chevron-down chev"></i></button>
      <div class="nav-children">${items.map((it) => `
        <button type="button" class="nav-item" data-view="${it.v}"><i class="ti ${it.i}"></i> ${it.l}
        ${it.badge ? `<span class="nav-badge hidden" data-badge="${it.badge}">0</span>` : ""}</button>`).join("")}</div></div>`;
  }
  const nav = $("#sidebar-nav");
  nav.innerHTML = h;
  nav.querySelectorAll("[data-toggle]").forEach(h=>h.onclick=()=>Navigation.ouvrir(h.dataset.toggle));
  nav.querySelectorAll(".nav-item").forEach(n=>n.onclick=()=>go(n.dataset.view,n.closest('.nav-group').querySelector('[data-toggle]').dataset.toggle));
  Navigation.selectionner(activeView);
}

// ── Navigation ───────────────────────────────────────────────────────
const TITLES = {
  accueil: ["Accueil", "Vos priorités et vos opérations"],
  dashboard: ["Tableau de bord", "Vue d'ensemble de la société"],
  approbation: ["Centre d'approbation", "Ce qui attend votre validation"],
  "nouvelle-req": ["Nouvelle réquisition", "Soumettre une demande de sortie de fonds"],
  requisitions: ["Réquisitions", "Suivi des demandes"],
  ordres: ["Ordres de dépense", "Autorisations de décaissement"],
  avances: ["Avances à justifier", "Suivi et justification des avances"],
  taux: ["Taux du jour", "Taux de change USD / CDF"],
  caisse: ["Caisses — Journal & soldes", "Vue d'ensemble des caisses, mouvements et sessions"],
  "caisse-exec": ["Décaissements à exécuter", "Ordres validés à payer (caisse)"],
  transferts: ["Transferts de fonds", "Entre caisses et comptes bancaires — double validation"],
  pos: ["Point de vente", "Écran de vente — session, encaissements, tickets et rapport"],
  compta: ["Pièces comptables", "Pièces en attente de validation / reclassement"],
  "saisie-od": ["Saisie d'écriture", "Opérations diverses — écriture manuelle équilibrée"],
  balance: ["Balance générale", "Soldes par compte — SYSCOHADA (N / N-1)"],
  "grand-livre": ["Grand livre", "Détail des mouvements par compte"],
  lettrage: ["Lettrage des tiers", "Rapprocher débits et crédits — suivi des avances / factures"],
  rapprochement: ["Rapprochement bancaire", "Pointer le compte de banque contre le relevé"],
  analytique: ["Comptabilité analytique", "Ventiler charges et produits par centre / activité"],
  commandes: ["Commandes", "Bons de commande fournisseurs (circuit d'achat en gros)"],
  receptions: ["Réceptions", "Entrées en stock des commandes — puis facturation"],
  achats: ["Achats", "Factures fournisseurs — stock & TVA déductible"],
  courses: ["Fiches de course", "Transport — de la demande à la facturation (PROC-KL-01 → 04)"],
  flotte: ["Flotte & maintenance", "Camions propres et sous-traités — disponibilité, pannes, entretiens"],
  "contrats-transport": ["Contrats de transport", "Contrats-cadres clients et grilles tarifaires par trajet"],
  "engins-parc": ["Parc d'engins", "Engins loués — tarifs, disponibilité et maintenance"],
  "maintenance-parc": ["Maintenance — parc & échéances", "Tout le parc (camions + engins), usage réel et plans d'entretien préventif"],
  "flotte-documents": ["Documents & échéances", "Assurances, contrôles techniques, permis… — alertes avant expiration"],
  carburant: ["Suivi carburant", "Pleins, consommation réelle vs théorique et coût au km / à l'heure"],
  "hotel-reception": ["Réception & séjours", "Réservations, check-in / check-out, notes de séjour et occupation"],
  "hotel-chambres": ["Chambres & ménage", "Parc de chambres, tarifs et housekeeping (libre / sale / nettoyage / maintenance)"],
  "config-hotel": ["Configuration — Hôtel", "Guide de démarrage : chambres, points de vente, articles, équipe"],
  "config-engins": ["Configuration — Location d'engins", "Réglages du module et données de base : parc, tarifs, locataire"],
  "config-transport": ["Configuration — Transport", "Réglages du module et données de base : camions, chauffeurs, contrats"],
  "config-maintenance": ["Configuration — Maintenance", "Équipe, plans d'entretien préventif et documents du parc"],
  depots: ["Dépôts & transferts", "Le dépôt central approvisionne les dépôts dédiés (bar, restaurant, cuisine…) par bons de transfert"],
  cuisine: ["Cuisine & food cost", "Fiches techniques des plats, consommation théorique journalière et ratio coût/CA"],
  "maintenance-interventions": ["Maintenance — interventions", "Pannes, entretiens et planification — camions et engins confondus"],
  "engins-heures": ["Heures prestées", "Fiches de service journalières — heures arrondies à 5 minutes"],
  "engins-rpe": ["RPE & facturation", "Relevé mensuel de prestation engins, forfait et heures supplémentaires"],
  intersociete: ["Opérations intersociétés", "Positions du groupe, factures miroir et règlements entre sociétés"],
  devis: ["Devis & commandes clients", "Devis → commande → livraison → facture — le cycle de vente complet"],
  ventes: ["Factures de vente", "Factures clients — règlements, TVA collectée & marge"],
  stock: ["Stock", "État du stock valorisé (coût moyen pondéré)"],
  articles: ["Articles", "Référentiel des produits — prix, comptes, TVA"],
  "tarifs-pos": ["Tarifs & points de vente", "Listes de prix par point de vente — préparation POS"],
  "rapports-commercial": ["Rapports commerciaux", "Historique des achats & synthèse des ventes"],
  cockpit: ["Cockpit financier", "Vue de synthèse du DAF — trésorerie, résultat, créances, dettes"],
  etats: ["États financiers OHADA", "Compte de résultat & Bilan — SYSCOHADA révisé"],
  "plan-comptable": ["Plan comptable & journaux", "Référentiel SYSCOHADA révisé — comptes et journaux"],
  config: ["Paramétrage", "Grille de validation, seuils et intervenants — par société"],
  administration: ["Administration", "Sociétés du groupe, agents & rôles, tiers — la fondation de l'ERP"],
};
async function go(view, groupePrefere) {
  if(activeView==='tva' && !Clotures.confirmLeave())return;
  if (!$("#view-" + view)) return;
  const version = ++navigationVersion;
  activeView = view;
  setMobileMenu(false);
  Navigation.selectionner(view,groupePrefere);
  if($('#nav-search').value){$('#nav-search').value='';Navigation.rechercher('');}
  document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
  $("#view-" + view).classList.add("active");
  $("#page-title").textContent = (TITLES[view] || [view, ""])[0];
  $("#page-sub").textContent = (TITLES[view] || ["", ""])[1];
  $(".content").scrollTop = 0;
  if (view !== "accueil" && me) {
    const key = "kh_recent_" + me.id;
    const recent = savedJSON(key, []).filter((v) => v !== view);
    localStorage.setItem(key, JSON.stringify([view, ...recent].slice(0, 5)));
  }
  refreshFluxBadges();
  try { await (RENDER[view] || (() => {}))(); }
  catch (e) {
    if (version !== navigationVersion || !token) return;
    const target = $("#view-" + view);
    target.innerHTML = `<div class="load-error" role="alert"><h2>Chargement interrompu</h2><p>${esc(e.message)}</p><button class="btn btn-primary" id="retry-view">Réessayer</button></div>`;
    target.querySelector("#retry-view").onclick = () => go(view);
  }
}
async function refreshBadge() {
  try {
    const a = await api("/approbations");
    const b = document.querySelector('[data-badge="appro"]');
    if (b) { b.textContent = a.total; b.classList.toggle("hidden", a.total === 0); }
  } catch {}
}

// Bannières des flux intersociétés : PO à prendre en charge (vendeur),
// marchandises à réceptionner (acheteur), demandes + confirmations (transporteur)
async function refreshFluxBadges() {
  try {
    const b = await api(`/intersociete/badges?societe_id=${currentSocieteId}`);
    for (const [cle, n] of [["devispo", b.devis_po], ["recv", b.receptions], ["crs", b.courses]]) {
      const el2 = document.querySelector(`[data-badge="${cle}"]`);
      if (el2) { el2.textContent = n; el2.classList.toggle("hidden", !n); }
    }
  } catch {}
}

// ── Modale ───────────────────────────────────────────────────────────
function modal({ title, body, footer, wide }) {
  const ov = document.createElement("div");
  ov.className = "modal-overlay";
  ov._returnFocus = document.activeElement;
  ov.innerHTML = `<div class="modal ${wide ? "wide" : ""}" role="dialog" aria-modal="true" aria-label="${esc(title)}" tabindex="-1">
      <div class="modal-hdr"><h3>${esc(title)}</h3><button class="x" aria-label="Fermer">×</button></div>
      <div class="modal-body">${body}</div>
      <div class="modal-foot">${footer || ""}</div>
    </div>`;
  $("#modal-root").appendChild(ov);            // empile (permet la création à la volée sans perdre le formulaire parent)
  ov.querySelector(".x").onclick = closeModal;
  ModuleUX.labelFields(ov);
  requestAnimationFrame(()=>{if(ov.isConnected)Catalogue.enhance(ov);});
  ov.querySelector(".modal").focus();
}
function closeModal() {
  const ov = $("#modal-root").lastElementChild;
  if (ov) { const focus = ov._returnFocus; ov.remove(); if (focus?.isConnected) focus.focus(); }
}

// Pièces jointes (justificatifs)
async function piecesModal(docType, docId, titre) {
  modal({
    title: titre || "Pièces jointes",
    body: `<div id="pj-list" class="card" style="padding:10px 14px;margin-bottom:14px"><div class="muted">Chargement…</div></div>
      <div class="form-group"><label class="form-label">Ajouter un fichier (max 10 Mo)</label>
      <input id="pj-file" type="file" class="form-input" /></div>`,
    footer: `<button class="btn" onclick="closeModal()">Fermer</button><button class="btn btn-primary" id="pj-up"><i class="ti ti-upload"></i> Téléverser</button>`,
  });
  const render = async () => {
    const list = await api(`/pieces-jointes?document_type=${docType}&document_id=${docId}`);
    $("#pj-list").innerHTML = list.length ? list.map((p) => `
      <div style="display:flex;justify-content:space-between;align-items:center;padding:6px 0;border-bottom:1px solid var(--bdr)">
        <span><i class="ti ti-file-text"></i> ${esc(p.nom_fichier)} <span class="muted">(${Math.round((p.taille_octets || 0) / 1024)} Ko)</span></span>
        <button class="btn btn-sm" onclick="downloadPiece('${p.id}','${esc(p.nom_fichier)}')"><i class="ti ti-download"></i></button></div>`).join("")
      : `<div class="muted">Aucune pièce jointe.</div>`;
  };
  await render();
  $("#pj-up").onclick = async () => {
    const up = $("#pj-up");
    if (up.disabled) return;
    const f = $("#pj-file").files[0];
    if (!f) { toast("Choisissez un fichier.", "ko"); return; }
    up.disabled = true; up.innerHTML = `<i class="ti ti-loader"></i> Envoi…`;
    const fd = new FormData();
    fd.append("document_type", docType); fd.append("document_id", docId); fd.append("file", f);
    const res = await fetch(API + "/pieces-jointes", { method: "POST", headers: { Authorization: "Bearer " + token }, body: fd });
    if (!res.ok) {
      toast("Échec du téléversement.", "ko");
      up.disabled = false; up.innerHTML = `<i class="ti ti-upload"></i> Téléverser`;
      return;
    }
    toast("Pièce jointe ajoutée.", "ok");
    closeModal();   // on referme après un téléversement réussi (pour rouvrir : bouton trombone)
  };
}
async function downloadPiece(id, nom) {
  const res = await fetch(API + `/pieces-jointes/${id}/download`, { headers: { Authorization: "Bearer " + token } });
  if (!res.ok) { toast("Téléchargement impossible.", "ko"); return; }
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a"); a.href = url; a.download = nom; a.click(); URL.revokeObjectURL(url);
}
window.piecesModal = piecesModal; window.downloadPiece = downloadPiece;

// ── Vues ─────────────────────────────────────────────────────────────
const RENDER = {};

// ── Accueil : portail des menus principaux + raccourcis ──────────────
const HOME = [
  { key: "Approbations", icon: "ti-checks", desc: "Réquisitions et validations", actions: [
    { l: "Nouvelle réquisition", i: "ti-file-plus", go: "nouvelle-req" },
    { l: "Centre d'approbation", i: "ti-checks", go: "approbation" },
    { l: "Réquisitions", i: "ti-files", go: "requisitions" }] },
  { key: "Décaissements", icon: "ti-receipt", desc: "Ordres de dépense et paiements", actions: [
    { l: "Ordres de dépense", i: "ti-receipt", go: "ordres" },
    { l: "Décaissements à exécuter", i: "ti-arrow-bar-to-down", go: "caisse-exec" }] },
  { key: "Avances", icon: "ti-cash", desc: "Suivi et justification des avances", actions: [
    { l: "Avances à justifier", i: "ti-cash", go: "avances" }] },
  { key: "Caisse", icon: "ti-book-2", desc: "Encaissements, sorties, transferts", actions: [
    { l: "Journal & soldes", i: "ti-book-2", go: "caisse" },
    { l: "Transferts", i: "ti-arrows-exchange", go: "transferts" }] },
  { key: "Comptabilité", icon: "ti-calculator", roles: ["COMPTABLE", "DFI"], desc: "Écritures, grand livre, balance", actions: [
    { l: "Saisir une écriture", i: "ti-pencil-plus", act: "saisie" },
    { l: "Pièces en attente", i: "ti-file-invoice", go: "compta" },
    { l: "Grand livre", i: "ti-list-details", go: "grand-livre" }] },
];

RENDER.accueil = () => {
  const el = $("#view-accueil");
  const nm = (me && (me.prenom || me.nom)) ? esc(me.prenom || me.nom) : "";
  const quick = [
    { l: "Soumettre une réquisition", i: "ti-file-plus", go: "nouvelle-req" },
    { l: "Faire un décaissement", i: "ti-arrow-bar-to-down", go: "caisse-exec" },
    { l: "Enregistrer une écriture", i: "ti-pencil-plus", act: "saisie", roles: ["COMPTABLE", "DFI"] },
  ].filter((q) => !q.roles || hasGlobal(...q.roles));
  const cards = HOME.filter((c) => !c.roles || hasGlobal(...c.roles));
  el.innerHTML = `<div class="home-hero">
      <h2>Bonjour ${nm} 👋</h2>
      <p class="muted">Accédez rapidement à vos opérations courantes, ou choisissez un menu ci-dessous.</p>
      <div class="home-quick">${quick.map((q) => `<button class="home-quick-btn" ${q.go ? `data-go="${q.go}"` : `data-act="${q.act}"`}><i class="ti ${q.i}"></i> ${esc(q.l)}</button>`).join("")}</div>
    </div>
    <div class="home-grid">${cards.map((c) => `<div class="home-card">
      <div class="home-card-hdr"><i class="ti ${c.icon}"></i> ${esc(c.key)}</div>
      <p class="home-card-desc muted">${esc(c.desc)}</p>
      <div class="home-acts">${c.actions.map((a) => `<button class="home-act" ${a.go ? `data-go="${a.go}"` : `data-act="${a.act}"`}><i class="ti ${a.i}"></i> ${esc(a.l)}</button>`).join("")}</div>
    </div>`).join("")}</div>`;
  el.querySelectorAll("[data-go]").forEach((b) => b.onclick = () => go(b.dataset.go));
  el.querySelectorAll('[data-act="saisie"]').forEach((b) => b.onclick = () => saisieODModal(() => toast("Écriture enregistrée.", "ok")));
};

RENDER.dashboard = async () => {
  const el = $("#view-dashboard");
  el.innerHTML = `<div class="muted">Chargement…</div>`;
  const d = await api(`/dashboard?societe_id=${currentSocieteId}`);
  const k = (label, val, sub, color, icon) => `
    <div class="kpi-card" style="--accent:${color};--kpi-color:${color}">
      <div class="kpi-label"><i class="ti ti-${icon}"></i>${label}</div>
      <div class="kpi-val">${val}</div><div class="kpi-sub">${sub || ""}</div></div>`;
  el.innerHTML = `
    <div class="kpi-row">
      ${k("Réquisitions soumises", d.requisitions_soumises, "en attente de validation", "var(--a)", "file-text")}
      ${k("Ordres à valider", d.ordres_a_valider, "sortie de fonds", "var(--p)", "receipt")}
      ${k("Avances en cours", d.avances_en_cours, fmtUSD(d.avances_montant_usd), "var(--t)", "cash")}
      ${k("Avances en retard", d.avances_en_retard, "non justifiées à temps", "var(--r)", "alarm")}
      ${k("Bénéficiaires bloqués", d.beneficiaires_bloques, "blocage automatique", "var(--r)", "lock")}
    </div>
    <div class="card"><div class="card-hdr"><div class="card-hdr-title"><i class="ti ti-bolt"></i> Raccourcis</div></div>
      <div class="card-body" style="display:flex;gap:10px;flex-wrap:wrap">
        <button class="btn btn-primary" onclick="go('nouvelle-req')"><i class="ti ti-file-plus"></i> Nouvelle réquisition</button>
        <button class="btn" onclick="go('approbation')"><i class="ti ti-checkbox"></i> Centre d'approbation</button>
        <button class="btn" onclick="go('avances')"><i class="ti ti-cash"></i> Avances</button>
      </div></div>`;
};

RENDER.approbation = async () => {
  const el = $("#view-approbation");
  el.innerHTML = `<div class="muted">Chargement…</div>`;
  const d = await api("/approbations");
  if (d.total === 0) { el.innerHTML = `<div class="empty"><i class="ti ti-checks"></i>Rien à valider pour le moment.</div>`; return; }
  let h = "";
  if (d.a_emettre && d.a_emettre.length) {
    h += secHdr("ti-receipt", "Niveau 2 — Sortie de fonds à initier (DFI)");
    for (const r of d.a_emettre) h += `<div class="item ordre">
      <div class="top"><div><div class="num">${esc(r.numero)} <span class="muted">· ${esc(r.societe)}</span></div>
      <div class="titre"><span class="tag" style="background:var(--pl);color:var(--p);font-weight:700">NIVEAU 2</span> ${esc(r.objet)}</div>
      <div class="meta">Demande validée (Niveau 1) — à valider en sortie de fonds et choisir le moyen de paiement</div></div>
      <div class="montant">${fmtUSD(r.montant_total_usd)}</div></div>
      <div class="actions"><button class="btn btn-sm" data-detail="${r.id}"><i class="ti ti-eye"></i> Détails</button>
      <button class="btn btn-primary btn-sm" data-emit="${r.id}"><i class="ti ti-check"></i> Valider la sortie de fonds</button></div></div>`;
  }
  if (d.requisitions.length) {
    h += secHdr("ti-file-text", "Niveau 1 — Validation de la demande");
    for (const r of d.requisitions) {
      const prio = r.priorite !== "normal" ? `<span class="tag ${r.priorite}">${r.priorite.replace("_", " ")}</span>` : "";
      h += itemCard("requisition", r.id, r.numero, r.societe, "Validation de la demande",
        esc(r.objet), r.montant_total_usd, prio + `Validateurs : ${r.roles_requis.join(", ")}`, false, true, 1);
    }
  }
  if (d.ordres_depense.length) {
    h += secHdr("ti-cash", "Niveau 2 — Validation de la sortie de fonds");
    for (const o of d.ordres_depense) {
      h += itemCard("ordre_depense", o.id, o.numero, o.societe, "Validation de la sortie de fonds",
        esc(o.motif || "(sans motif)"), o.montant_autorise_usd,
        `<span class="tag">${esc(o.palier)}</span>Validateurs : ${o.roles_requis.join(", ")}`, true, false, 2);
    }
  }
  el.innerHTML = h;
  el.querySelectorAll("[data-act]").forEach((b) => b.onclick = () => decider(b.dataset.kind, b.dataset.id, b.dataset.act));
  el.querySelectorAll("[data-prec]").forEach((b) => b.onclick = () => demanderPrecisions(b.dataset.prec));
  el.querySelectorAll("[data-emit]").forEach((b) => b.onclick = () => emettreOrdre(b.dataset.emit));
  el.querySelectorAll("[data-detail]").forEach((b) => b.onclick = () => detailsRequisition(b.dataset.detail));
};
const secHdr = (icon, t) => `<div class="section-hdr"><div class="section-title"><i class="ti ${icon}"></i> ${t}</div></div>`;
function itemCard(kind, id, num, soc, titre, desc, montant, info, isOrdre, showPrec, niveau) {
  const niv = niveau ? `<span class="tag" style="background:var(--pl);color:var(--p);font-weight:700">NIVEAU ${niveau}</span> ` : "";
  return `<div class="item ${isOrdre ? "ordre" : ""}">
    <div class="top"><div>
      <div class="num">${esc(num)} <span class="muted">· ${esc(soc)}</span></div>
      <div class="titre">${niv}${titre}</div><div class="meta">${desc}</div>
      <div class="meta">${info}</div></div>
      <div class="montant">${fmtUSD(montant)}</div></div>
    <div class="actions">
      ${kind === "requisition" ? `<button class="btn btn-sm" data-detail="${id}"><i class="ti ti-eye"></i> Détails</button>` : ""}
      <button class="btn btn-success btn-sm" data-act="valide" data-kind="${kind}" data-id="${id}"><i class="ti ti-check"></i> Approuver</button>
      ${showPrec ? `<button class="btn btn-sm" data-prec="${id}"><i class="ti ti-message-2"></i> Demander des précisions</button>` : ""}
      <button class="btn btn-danger btn-sm" data-act="rejete" data-kind="${kind}" data-id="${id}"><i class="ti ti-x"></i> Rejeter</button>
    </div></div>`;
}
async function demanderPrecisions(id) {
  const fil = await api(`/requisitions/${id}/commentaires`);
  modal({
    title: "Demander des précisions à l'initiateur",
    body: `${threadHTML(fil)}<div class="form-group"><label class="form-label">Votre question / précision demandée</label>
      <textarea id="p-msg" class="form-textarea" placeholder="Ex. : Merci de préciser le fournisseur et de joindre un devis."></textarea></div>
      <div class="muted">La réquisition est renvoyée à l'initiateur sans être rejetée ; il pourra répondre et la re-soumettre.</div>`,
    footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="p-ok"><i class="ti ti-send"></i> Renvoyer pour précisions</button>`,
  });
  $("#p-ok").onclick = async () => {
    const msg = $("#p-msg").value.trim();
    if (!msg) { toast("Veuillez saisir votre question.", "ko"); return; }
    try {
      await api(`/requisitions/${id}/demander-precisions`, { method: "POST", body: { decision: "valide", commentaire: msg } });
      closeModal(); toast("Renvoyée à l'initiateur pour précisions.", "ok");
      await refreshBadge(); RENDER.approbation();
    } catch (e) { toast(e.message, "ko"); }
  };
}
function threadHTML(fil) {
  if (!fil || !fil.length) return "";
  return `<div class="card" style="margin-bottom:14px"><div class="card-body" style="padding:10px 14px">` +
    fil.map((c) => `<div style="padding:6px 0;border-bottom:1px solid var(--bdr)">
      <span class="tag ${c.type === "precision_demandee" ? "urgent" : ""}">${c.type === "precision_demandee" ? "Précision demandée" : c.type === "reponse" ? "Réponse" : "Note"}</span>
      <b>${esc(c.auteur)}</b> <span class="muted">${c.created_at ? new Date(c.created_at).toLocaleString("fr-FR") : ""}</span>
      <div>${esc(c.message)}</div></div>`).join("") + `</div>`;
}
async function decider(kind, id, decision) {
  const path = kind === "requisition" ? `/requisitions/${id}/valider-demande` : `/ordres-depense/${id}/valider`;
  try {
    const r = await api(path, { method: "POST", body: { decision } });
    toast(`${decision === "valide" ? "Approuvé" : "Rejeté"} — statut : ${r.statut}`, decision === "valide" ? "ok" : "ko");
    await refreshBadge(); RENDER.approbation();
  } catch (e) { toast(e.message, "ko"); }
}

// Nouvelle réquisition
let lignes = [];
RENDER["nouvelle-req"] = () => {
  lignes = [{ description: "", quantite: 1, prix_unitaire: 0 }];
  const el = $("#view-nouvelle-req");
  el.innerHTML = `
    <div class="card"><div class="card-body" style="max-width:760px">
      <div class="req-form-intro"><span class="req-step">01</span><div><h2>Préparer votre demande</h2><p>Décrivez le besoin, choisissez le type de dépense puis détaillez les montants.</p></div></div>
      <div class="form-row"><div class="form-group"><label class="form-label">Objet</label>
        <input id="r-objet" class="form-input" placeholder="Ex. Achat de fournitures" /></div>
        <div class="form-group"><label class="form-label">Priorité</label>
        <select id="r-prio" class="form-select"><option value="normal">Normale</option><option value="urgent">Urgente</option><option value="top_urgent">Très urgente</option></select></div></div>
      <div class="form-group"><label class="form-label">Motif de la demande</label>
        <textarea id="r-justif" class="form-textarea" placeholder="Expliquez la raison de cette dépense (ex. : achat de carburant pour la livraison de ciment à Kolwezi)."></textarea></div>
      <div class="req-section-label">02 · Choisir le circuit et la devise</div>
      <div class="form-row-3">
        <div class="form-group"><label class="form-label">Type de décaissement</label>
          <select id="r-mode" class="form-select">
            <option value="avance">Avance à justifier (paiement avant justification)</option>
            <option value="paiement_direct">Paiement direct sur justificatif (facture déjà reçue)</option></select></div>
        <div class="form-group"><label class="form-label">Nature de la dépense</label>
          <select id="r-nature" class="form-select">
            <option value="charge">Dépense pure (charge — rien n'entre en stock)</option>
            <option value="marchandise">Achats stockables (marchandises, matières premières, consommables)</option></select></div>
        <div class="form-group"><label class="form-label">Devise</label>
          <select id="r-devise" class="form-select"><option>USD</option><option>CDF</option></select></div>
      </div>
      <div class="muted" id="r-mode-help" style="margin:-6px 0 8px"></div>
      <div class="muted" id="r-nature-help" style="margin-bottom:14px"></div>
      <div class="req-section-label">03 · Détailler les dépenses</div>
      <div class="list-table-scroll"><table class="lignes-table"><thead><tr><th>Description</th><th style="width:90px">Qté</th><th style="width:130px">Prix unit.</th><th style="width:120px" class="right">Montant</th><th style="width:36px"></th></tr></thead>
      <tbody id="r-lignes"></tbody></table></div>
      <button class="btn btn-sm" id="r-add" style="margin-top:8px"><i class="ti ti-plus"></i> Ajouter une ligne</button>
      <div class="total-bar"><span class="lbl">Total</span><span class="val" id="r-total">0,00</span></div>
      <div class="req-next-note">Après soumission, retrouvez l'avancement dans <b>Réquisitions</b>. Le montant et les règles de votre société déterminent les validations à obtenir.</div>
      <div style="margin-top:18px;display:flex;gap:10px"><button class="btn btn-primary" id="r-submit"><i class="ti ti-send"></i> Soumettre la réquisition</button></div>
      <div class="err" id="r-err"></div>
    </div></div>`;
  renderLignes();
  const modeHelp = () => {
    $("#r-mode-help").textContent = $("#r-mode").value === "paiement_direct"
      ? "Les marchandises et la facture sont déjà reçues : joignez le justificatif. Aucune justification après paiement."
      : "Les fonds sont remis au bénéficiaire, qui justifie ensuite ses dépenses dans le délai.";
  };
  modeHelp();
  $("#r-mode").onchange = modeHelp;
  const natureHelp = () => { $("#r-nature-help").textContent = $("#r-nature").value === "marchandise"
    ? "Achats stockables : marchandises, matières premières ou consommables."
    : "Charge : la dépense ne fait pas entrer de marchandises en stock."; };
  natureHelp(); $("#r-nature").onchange = natureHelp;
  $("#r-add").onclick = () => { lignes.push({ description: "", quantite: 1, prix_unitaire: 0 }); renderLignes(); };
  $("#r-devise").onchange = renderLignes;
  $("#r-submit").onclick = submitReq;
};
const fmtNum = (v) => new Intl.NumberFormat("fr-FR", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(v || 0);

// ── Fil d'avancement d'une commande intersociété ─────────────────────
// La même bannière chez l'acheteur, le vendeur et le transporteur : les étapes
// faites, l'étape EN COURS mise en évidence, et qui doit agir maintenant.
const bandeauEtapesPO = (ep) => {
  if (!ep || !ep.etapes || !ep.etapes.length) return "";
  if (ep.annulee) return `<div class="banner" style="margin:8px 0"><i class="ti ti-ban"></i> Circuit intersociété <b>annulé</b>.</div>`;
  const puce = (e) => {
    const encours = ep.prochaine && e.cle === ep.prochaine.cle;
    const style = e.fait ? "color:var(--g)"
      : encours ? "color:var(--p);font-weight:700" : "opacity:.5";
    const icone = e.fait ? "ti-circle-check-filled" : encours ? "ti-progress" : "ti-circle";
    return `<span title="${esc(e.libelle)} — ${esc(e.acteur)}" style="display:inline-flex;align-items:center;gap:3px;font-size:11.5px;white-space:nowrap;${style}"><i class="ti ${icone}"></i>${esc(e.libelle)}</span>`;
  };
  const fil = ep.etapes.map(puce).join('<i class="ti ti-chevron-right" style="opacity:.3;font-size:10px"></i>');
  const attente = ep.terminee
    ? `<div style="margin-top:7px;font-size:12.5px;color:var(--g)"><i class="ti ti-checks"></i> <b>Circuit terminé</b> — toutes les étapes sont faites.</div>`
    : `<div style="margin-top:7px;font-size:12.5px"><i class="ti ti-hourglass" style="color:var(--p)"></i>
        On attend maintenant : <b style="color:var(--p)">${esc(ep.prochaine.acteur)}</b> — ${esc(ep.prochaine.libelle)}</div>`;
  return `<div class="card" style="margin:8px 0"><div class="card-body" style="padding:10px 14px">
      <div class="muted" style="font-size:11px;text-transform:uppercase;letter-spacing:.4px;margin-bottom:6px"><i class="ti ti-route"></i> Suivi du circuit intersociété</div>
      <div style="display:flex;align-items:center;gap:5px;flex-wrap:wrap;row-gap:7px">${fil}</div>${attente}</div></div>`;
};
function updateMontantLigne(i) {
  const dev = $("#r-devise").value, l = lignes[i], c = $("#m-" + i);
  if (c) c.textContent = fmtNum((l.quantite || 0) * (l.prix_unitaire || 0)) + " " + dev;
}
function updateTotalReq() {
  const dev = $("#r-devise").value;
  const t = lignes.reduce((s, l) => s + (l.quantite || 0) * (l.prix_unitaire || 0), 0);
  $("#r-total").textContent = fmtNum(t) + " " + dev;
}
function renderLignes() {
  const dev = $("#r-devise")?.value || "USD";
  const tb = $("#r-lignes");
  // On (re)construit les rangées seulement à l'ajout/suppression — PAS à chaque frappe,
  // pour ne pas perdre le focus du champ en cours de saisie.
  tb.innerHTML = lignes.map((l, i) => `
    <tr><td><input class="form-input" aria-label="Description, ligne ${i+1}" data-i="${i}" data-f="description" value="${esc(l.description)}" /></td>
    <td><input class="form-input" aria-label="Quantité, ligne ${i+1}" type="number" min="0" step="any" data-i="${i}" data-f="quantite" value="${l.quantite}" /></td>
    <td><input class="form-input" aria-label="Prix unitaire en ${dev}, ligne ${i+1}" type="number" min="0" step="any" data-i="${i}" data-f="prix_unitaire" value="${l.prix_unitaire}" /></td>
    <td class="right" id="m-${i}">${fmtNum((l.quantite || 0) * (l.prix_unitaire || 0))} ${dev}</td>
    <td>${lignes.length > 1 ? `<button class="btn btn-sm" aria-label="Retirer la ligne ${i+1}" data-del="${i}">×</button>` : ""}</td></tr>`).join("");
  tb.querySelectorAll("input").forEach((inp) => inp.oninput = () => {
    const i = inp.dataset.i, f = inp.dataset.f;
    lignes[i][f] = f === "description" ? inp.value : parseFloat(inp.value || 0);
    updateMontantLigne(i); updateTotalReq();   // mise à jour ciblée, sans recréer les champs
  });
  tb.querySelectorAll("[data-del]").forEach((b) => b.onclick = () => { lignes.splice(b.dataset.del, 1); renderLignes(); });
  updateTotalReq();
}
async function submitReq() {
  $("#r-err").textContent = "";
  const objet = $("#r-objet").value.trim();
  if (!objet) { $("#r-err").textContent = "L'objet est requis."; return; }
  const mode = $("#r-mode").value;
  const body = {
    societe_id: currentSocieteId, objet, justification: $("#r-justif").value || null,
    mode_decaissement: mode, nature: $("#r-nature").value, priorite: $("#r-prio").value, devise: $("#r-devise").value,
    lignes: lignes.filter((l) => l.description).map((l) => ({
      description: l.description, quantite: l.quantite, prix_unitaire: l.prix_unitaire })),
  };
  if (!body.lignes.length) { $("#r-err").textContent = "Au moins une ligne avec description."; return; }
  const btn = $("#r-submit");
  if (btn.disabled) return;                 // évite le double-clic
  btn.disabled = true; btn.innerHTML = `<i class="ti ti-loader"></i> Envoi…`;
  try {
    const r = await api("/requisitions", { method: "POST", body });
    toast(`Réquisition ${r.numero} soumise (${fmtUSD(r.montant_total_usd)})`, "ok");
    go("requisitions");                     // on quitte le formulaire → plus de re-soumission possible
    if (mode === "paiement_direct")          // facture déjà reçue : on invite à joindre le justificatif
      piecesModal("requisition", r.id, "Joindre le justificatif (facture / bon de livraison)");
  } catch (e) {
    $("#r-err").textContent = e.message;
    btn.disabled = false; btn.innerHTML = `<i class="ti ti-send"></i> Soumettre la réquisition`;
  }
}

// Réquisitions
RENDER.requisitions = async () => {
  const el = $("#view-requisitions");
  el.innerHTML = `<div class="muted">Chargement…</div>`;
  const list = await api(`/requisitions?societe_id=${currentSocieteId}`);
  if (!list.length) { el.innerHTML = `<div class="empty"><i class="ti ti-files"></i>Aucune réquisition.</div>`; return; }
  el.innerHTML = `<div class="card"><table><thead><tr><th>Numéro</th><th>Objet</th><th class="right">Montant</th><th>Avancement</th><th></th></tr></thead><tbody>
    ${list.map((r) => {
      let act = "";
      if (r.statut === "demande_validee" && has("DFI"))
        act += `<button class="btn btn-sm btn-primary" data-odp="${r.id}"><i class="ti ti-check"></i> Valider sortie de fonds</button> `;
      if (r.statut === "en_attente_info" && r.est_initiateur)
        act += `<button class="btn btn-sm btn-success" data-rep="${r.id}"><i class="ti ti-message-reply"></i> Répondre</button> `;
      if (r.nb_commentaires > 0)
        act += `<button class="btn btn-sm" data-voir="${r.id}"><i class="ti ti-messages"></i> ${r.nb_commentaires}</button> `;
      act += `<button class="btn btn-sm" data-pj="${r.id}" title="Pièces jointes"><i class="ti ti-paperclip"></i></button>`;
      const modeTag = r.mode_decaissement === "paiement_direct"
        ? ` <span class="tag">paiement direct</span>` : ` <span class="tag">avance</span>`;
      return `<tr><td class="num-cell"><button class="document-link" data-detail="${r.id}" title="Consulter la réquisition">${esc(r.numero)}</button></td><td>${esc(r.objet)}${modeTag}</td>
        <td class="right">${fmtUSD(r.montant_total_usd)}</td>
        <td>${pill(r.statut)}<div class="meta" style="margin-top:4px">${esc(r.progression.label)}</div></td>
        <td class="right" style="white-space:nowrap">${act}</td></tr>`;
    }).join("")}
  </tbody></table></div>`;
  el.querySelectorAll("[data-detail]").forEach((b) => b.onclick = () => detailsRequisition(b.dataset.detail));
  el.querySelectorAll("[data-odp]").forEach((b) => b.onclick = () => emettreOrdre(b.dataset.odp));
  el.querySelectorAll("[data-rep]").forEach((b) => b.onclick = () => repondre(b.dataset.rep));
  el.querySelectorAll("[data-voir]").forEach((b) => b.onclick = () => voirEchanges(b.dataset.voir));
  el.querySelectorAll("[data-pj]").forEach((b) => b.onclick = () => piecesModal("requisition", b.dataset.pj));
};
async function repondre(id) {
  const fil = await api(`/requisitions/${id}/commentaires`);
  modal({
    title: "Répondre aux précisions demandées",
    body: `${threadHTML(fil)}<div class="form-group"><label class="form-label">Votre réponse</label>
      <textarea id="rep-msg" class="form-textarea" placeholder="Apportez les précisions demandées…"></textarea></div>
      <div class="muted">La réquisition sera re-soumise aux validateurs.</div>`,
    footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="rep-ok"><i class="ti ti-send"></i> Répondre et re-soumettre</button>`,
  });
  $("#rep-ok").onclick = async () => {
    const msg = $("#rep-msg").value.trim();
    if (!msg) { toast("Veuillez saisir votre réponse.", "ko"); return; }
    try {
      await api(`/requisitions/${id}/repondre`, { method: "POST", body: { decision: "valide", commentaire: msg } });
      closeModal(); toast("Réponse envoyée — réquisition re-soumise.", "ok"); RENDER.requisitions();
    } catch (e) { toast(e.message, "ko"); }
  };
}
async function voirEchanges(id) {
  const fil = await api(`/requisitions/${id}/commentaires`);
  modal({ title: "Échanges sur la réquisition", body: threadHTML(fil) || `<div class="muted">Aucun échange.</div>`,
    footer: `<button class="btn" onclick="closeModal()">Fermer</button>` });
}
async function emettreOrdre(reqId) {
  const tiers = await api(`/beneficiaires?societe_id=${currentSocieteId}`);
  modal({
    title: "Valider la sortie de fonds — Niveau 2 (DFI)",
    body: `<div class="banner"><i class="ti ti-info-circle"></i> En émettant l'ordre, vous validez la sortie de fonds (Niveau 2) et choisissez le moyen de paiement. Si d'autres co-signataires sont requis selon le montant, l'ordre les attendra.</div>
      <div class="form-group"><label class="form-label">Bénéficiaire provisoire</label>
      <select id="o-benef" class="form-select"><option value="">— Choisir un agent ou un tiers —</option>${tiers.map((t) => `<option value="${t.id}">${esc(Catalogue.label(t))} (${t.type}${t.agent_existant?' existant':''})</option>`).join("")}</select><p class="muted">Le caissier ou le comptable confirmera le bénéficiaire réel à la remise des fonds.</p></div>
      <div class="form-group"><label class="form-label">Moyen de paiement</label>
      <select id="o-mode" class="form-select"><option value="caisse">Caisse</option><option value="banque">Banque</option></select></div>
      <div class="form-group"><label class="form-label">Motif (optionnel)</label><input id="o-motif" class="form-input" /></div>`,
    footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="o-ok"><i class="ti ti-check"></i> Valider & émettre</button>`,
  });
  $("#o-ok").onclick = async () => {
    try {
      const r = await api("/ordres-depense", { method: "POST", body: {
        requisition_id: reqId, beneficiaire_tiers_id: $("#o-benef").value,
        mode_paiement: $("#o-mode").value, motif: $("#o-motif").value || null } });
      closeModal();
      toast(r.statut === "valide"
        ? `Ordre ${r.numero} validé — sortie de fonds autorisée.`
        : `Ordre ${r.numero} émis — en attente des co-signataires (${r.palier_applique}).`, "ok");
      await refreshBadge(); go("ordres");
    } catch (e) { toast(e.message, "ko"); }
  };
}

// Ordres de dépense
RENDER.ordres = async () => {
  const el = $("#view-ordres");
  el.innerHTML = `<div class="muted">Chargement…</div>`;
  const list = await api(`/ordres-depense?societe_id=${currentSocieteId}`);
  if (!list.length) { el.innerHTML = `<div class="empty"><i class="ti ti-receipt"></i>Aucun ordre de dépense.</div>`; return; }
  el.innerHTML = `<div class="card"><table><thead><tr><th>Numéro</th><th>Bénéficiaire</th><th>Palier</th><th class="right">Montant</th><th>Statut</th><th></th></tr></thead><tbody>
    ${list.map((o) => {
      let act = "";
      if (o.statut === "a_valider") act = `<button class="btn btn-sm btn-success" data-val="${o.id}">Valider</button>`;
      else if (o.statut === "valide" && has("CAISSIER_CENTRAL", "CAISSIER_VENDEUR", "COMPTABLE", "DFI")) act = `<button class="btn btn-sm btn-primary" data-exec="${o.id}" data-mode="${o.mode_paiement}" data-md="${o.mode_decaissement}" data-benef="${o.beneficiaire_tiers_id}" data-devise="${o.devise}" data-reste="${o.reste_usd}" data-req="${esc(o.requisition_numero || "")}" data-objet="${esc(o.requisition_objet || "")}"><i class="ti ti-cash"></i> ${o.mode_decaissement === "paiement_direct" ? "Payer" : "Exécuter"}</button>`;
      else if (["execute", "paye"].includes(o.statut)) act = `<button class="btn btn-sm" data-print="${o.id}"><i class="ti ti-printer"></i> Bon de sortie</button>`;
      const moyen = o.mode_paiement === "banque" ? `<span class="tag"><i class="ti ti-building-bank"></i> banque</span>` : `<span class="tag"><i class="ti ti-cash"></i> caisse</span>`;
      return `<tr><td class="num-cell">${esc(o.numero)}</td><td>${esc(o.beneficiaire || "")} ${moyen}</td>
        <td><span class="tag">${esc(o.palier_applique || "")}</span></td><td class="right">${fmtUSD(o.montant_autorise_usd)}</td>
        <td>${pill(o.statut)}</td><td class="right">${act}</td></tr>`;
    }).join("")}
  </tbody></table></div>`;
  el.querySelectorAll("[data-val]").forEach((b) => b.onclick = () => decider("ordre_depense", b.dataset.val, "valide"));
  el.querySelectorAll("[data-exec]").forEach((b) => b.onclick = () => executer(b.dataset.exec, b.dataset.mode, b.dataset.md, b.dataset.benef, b.dataset.devise, b.dataset.reste, b.dataset.req, b.dataset.objet));
  el.querySelectorAll("[data-print]").forEach((b) => b.onclick = () => printBonSortie(b.dataset.print));
};
async function executer(ordreId, mode, modeDec, benefId, devise, reste, reqNum, objet) {
  const banque = mode === "banque";
  const direct = modeDec === "paiement_direct";
  const dev = devise || "USD";
  const resteUsd = parseFloat(reste || 0);
  let bill = false;
  const [sources, tiers] = await Promise.all([
    banque ? api(`/comptes-bancaires?societe_id=${currentSocieteId}`) : api(`/caisses?societe_id=${currentSocieteId}`),
    api(`/beneficiaires?societe_id=${currentSocieteId}`),
  ]);
  modal({
    title: direct ? "Enregistrer le paiement (sur justificatif)" : "Décaissement — sortie de fonds",
    body: `<div class="banner"><i class="ti ti-info-circle"></i> ${direct ? "Paiement sur facture déjà reçue : aucune justification ne sera requise après." : "Confirmez la personne qui reçoit les fonds : l’avance à justifier sera établie à son nom. Le choix du DFI reste modifiable."}</div>
      ${reqNum ? `<div style="background:var(--pl);color:var(--p);padding:10px 12px;border-radius:6px;margin-bottom:12px"><i class="ti ti-file-text"></i> <b>Réquisition ${esc(reqNum)}</b>${objet ? " — " + esc(objet) : ""}</div>` : ""}
      <div class="form-group"><label class="form-label">Bénéficiaire réel — à confirmer pour ce paiement</label>
        <select id="x-benef" class="form-select"><option value="">— Choisir le bénéficiaire réel —</option>${tiers.map((t) => `<option value="${t.id}" ${t.id === benefId ? "selected" : ""}>${esc(Catalogue.label(t))} (${t.type}${t.agent_existant?' existant':''})</option>`).join("")}</select>
        <div class="catalogue-scope" id="x-benef-summary" style="margin-top:10px"></div></div>
      <div class="form-group"><label class="form-label">${banque ? "Compte bancaire" : "Caisse"}</label>
        <select id="x-src" class="form-select">${sources.map((c) => `<option value="${c.id}">${esc(c.libelle)}</option>`).join("")}</select></div>
      ${banque ? `<div class="form-group"><label class="form-label">Référence OP / chèque</label><input id="x-ref" class="form-input" placeholder="ex. OP-2026-001 ou n° de chèque" /></div>` : ""}
      ${direct ? "" : `<div class="form-group"><label class="form-label">Montant à décaisser (reste : ${fmtNum(resteUsd)} USD)</label>
        <input id="x-montant" class="form-input" type="number" step="any" value="${dev === "USD" ? resteUsd : ""}" placeholder="Vide = tout le reste. Décaissement partiel possible." />
        <div class="muted" style="margin-top:4px">Vous pouvez ne payer qu'une partie ; l'ordre restera ouvert pour le solde.</div></div>
      <div class="form-group"><label class="form-label">Type d'avance</label><select id="x-type" class="form-select"><option value="">(standard 24h)</option><option value="course">Course (2h)</option><option value="marche">Marché (2h)</option><option value="pieces">Pièces (24h)</option><option value="boissons">Boissons (24h)</option></select></div>`}
      ${banque ? "" : `<div class="form-group"><label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-size:13px"><input type="checkbox" id="x-bill-tgl" style="width:auto" /> Détailler le billetage (${dev})</label></div><div id="x-bill" class="hidden"></div>`}`,
    footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="x-ok">Confirmer (${banque ? "banque" : "caisse"})</button>`,
  });
  const confirmBeneficiary=()=>{
    const select=$('#x-benef');
    $('#x-benef-summary').textContent=select.value
      ? `${direct?'Paiement enregistré au nom de':'Avance à justifier rattachée à'} : ${select.selectedOptions[0].textContent}`
      : 'Le bénéficiaire précédent n’est pas disponible ou aucun bénéficiaire n’est choisi. Sélectionnez une fiche avant de confirmer.';
    $('#x-ok').disabled=!select.value;
  };
  $('#x-benef').onchange=confirmBeneficiary;confirmBeneficiary();
  if (!banque) {
    const drawBill = () => {
      $("#x-bill").innerHTML = `<table class="lignes-table"><thead><tr><th>Coupure</th><th>Nombre</th><th class="right">Sous-total</th></tr></thead><tbody>
        ${DENOM[dev].map((d) => `<tr><td>${fmtNum(d)} ${dev}</td><td><input class="form-input xbn" data-d="${d}" type="number" min="0" step="1" style="width:90px" value="0" /></td><td class="right" id="xbst-${d}">0</td></tr>`).join("")}
        </tbody></table><div class="total-bar"><span class="lbl">Total billetage</span><span class="val" id="x-bill-total">0</span></div>`;
      $("#x-bill").querySelectorAll(".xbn").forEach((inp) => inp.oninput = () => {
        let t = 0; $("#x-bill").querySelectorAll(".xbn").forEach((x) => { const st = (parseFloat(x.dataset.d) || 0) * (parseInt(x.value || 0) || 0); $("#xbst-" + x.dataset.d).textContent = fmtNum(st); t += st; });
        $("#x-bill-total").textContent = fmtNum(t);
      });
    };
    $("#x-bill-tgl").onchange = (e) => { bill = e.target.checked; $("#x-bill").classList.toggle("hidden", !bill); if (bill) drawBill(); else $("#x-bill").innerHTML = ""; };
  }
  $("#x-ok").onclick = async () => {
    const body = {};
    body[banque ? "compte_bancaire_id" : "caisse_id"] = $("#x-src").value;
    if (banque) { const ref = $("#x-ref").value.trim(); if (ref) body.reference_paiement = ref; }
    if (!direct) { const t = $("#x-type").value; if (t) body.type_avance = t; }
    if (!direct && $("#x-montant")) { const mt = parseFloat($("#x-montant").value || 0); if (mt > 0) body.montant = mt; }
    if (!$('#x-benef').value) {toast('Confirmez le bénéficiaire réel.','ko');return;}
    body.beneficiaire_tiers_id = $("#x-benef").value;
    if (!banque && bill) { const b = {}; $("#x-bill").querySelectorAll(".xbn").forEach((x) => { const n = parseInt(x.value || 0); if (n > 0) b[x.dataset.d] = n; }); if (Object.keys(b).length) body.billetage = b; }
    try {
      const r = await api(`/ordres-depense/${ordreId}/executer`, { method: "POST", body });
      closeModal();
      // Bon imprimé automatiquement à chaque décaissement
      if (r.mouvement_id) printBonCaisse(r.mouvement_id); else printBonSortie(ordreId);
      if (r.mode === "paiement_direct") { toast(`Paiement enregistré (écriture ${r.ecriture}).`, "ok"); go("ordres"); }
      else if (r.partiel) { toast(`Décaissement partiel — avance ${r.avance_numero}. Reste ${fmtNum(r.reste_usd)} USD à décaisser (ordre encore ouvert).`, "ok"); go("avances"); }
      else { toast(`Avance ${r.avance_numero} créée. Justification avant ${new Date(r.echeance_justification).toLocaleString("fr-FR")}`, "ok"); go("avances"); }
    } catch (e) { toast(e.message, "ko"); }
  };
}

// Avances
let jlignes = [];
RENDER.avances = async () => {
  const el = $("#view-avances");
  el.innerHTML = `<div class="muted">Chargement…</div>`;
  const list = await api(`/avances?societe_id=${currentSocieteId}`);
  if (!list.length) { el.innerHTML = `<div class="empty"><i class="ti ti-cash"></i>Aucune avance.</div>`; return; }
  el.innerHTML = `<div class="card"><table><thead><tr><th>Numéro</th><th>Bénéficiaire</th><th>Type</th><th class="right">Montant</th><th>Échéance</th><th>Statut</th><th></th></tr></thead><tbody>
    ${list.map((a) => {
      const act = (a.statut === "a_justifier" || a.statut === "en_retard")
        ? `<button class="btn btn-sm btn-primary" data-just='${esc(JSON.stringify({ id: a.id, num: a.numero, montant: a.montant_avance_usd, nature: a.nature }))}'><i class="ti ti-receipt"></i> Justifier</button>` : "";
      return `<tr><td class="num-cell">${esc(a.numero)}${a.nature === "marchandise" ? ' <span class="tag">marchandises</span>' : ""}</td><td>${esc(a.beneficiaire || "")}</td><td>${esc(a.type_avance || "—")}</td>
        <td class="right">${fmtUSD(a.montant_avance_usd)}</td><td>${a.echeance_justif ? new Date(a.echeance_justif).toLocaleString("fr-FR") : "—"}</td>
        <td>${pill(a.statut)}</td><td class="right">${act}</td></tr>`;
    }).join("")}
  </tbody></table></div>`;
  el.querySelectorAll("[data-just]").forEach((b) => b.onclick = () => justifier(JSON.parse(b.dataset.just)));
};
async function justifier(av) {
  jlignes = [{ nature: "", montant: 0 }];
  const articles = await api(`/commercial/articles?societe_id=${currentSocieteId}`).catch(() => []);
  const byId = Object.fromEntries(articles.map((a) => [a.id, a]));
  const tagNature = (a) => a.nature === "matiere_premiere" ? " · matière première"
    : a.nature === "consommable" ? " · consommable" : "";
  let artOpts = `<option value="">(choisir)</option>` + articles
    .slice().sort((x, y) => x.designation.localeCompare(y.designation))
    .map((a) => `<option value="${a.id}">${esc(a.code)} — ${esc(a.designation)}${tagNature(a)}</option>`).join("");
  const mHTML = () => `<tr class="jm-row">
    <td><div style="display:flex;gap:4px"><select class="form-select jm-art" style="min-width:120px">${artOpts}</select><button class="btn btn-sm jm-anew" title="Nouvel article"><i class="ti ti-plus"></i></button></div></td>
    <td><input class="form-input jm-des" placeholder="désignation" /></td>
    <td><input class="form-input jm-qte right" type="number" step="any" value="1" style="width:58px" /></td>
    <td><input class="form-input jm-pu right" type="number" step="any" value="0" style="width:78px" /></td>
    <td><input class="form-input jm-tva right" type="number" step="any" value="16" style="width:48px" /></td>
    <td class="right jm-ce num-cell">—</td>
    <td><button class="btn btn-sm jm-del"><i class="ti ti-trash"></i></button></td></tr>`;
  const fHTML = () => `<tr class="jf-row"><td><input class="form-input jf-lib" placeholder="ex. Transport" /></td>
    <td><input class="form-input jf-mt right" type="number" step="any" value="0" style="width:80px" /></td>
    <td><input class="form-input jf-tva right" type="number" step="any" value="16" style="width:48px" /></td>
    <td><button class="btn btn-sm jf-del"><i class="ti ti-trash"></i></button></td></tr>`;
  modal({
    title: `Justifier l'avance ${av.num}`,
    wide: true,
    body: `<div class="banner"><i class="ti ti-scale"></i> Avance reçue : <b>${fmtUSD(av.montant)}</b>. Justifiez par des dépenses (charges) et/ou des marchandises (qui entrent en stock). Le total doit s'équilibrer.</div>
      <b style="font-size:13px">Dépenses (charges)</b>
      <table class="lignes-table" style="margin-top:4px"><thead><tr><th>Nature</th><th style="width:80px">Devise</th><th style="width:110px">Montant</th><th style="width:28px"></th></tr></thead><tbody id="j-lignes"></tbody></table>
      <button class="btn btn-sm" id="j-add" style="margin-top:4px"><i class="ti ti-plus"></i> Ligne</button>
      <div style="display:flex;align-items:center;gap:14px;margin:18px 0 4px"><b style="font-size:13px">Marchandises achetées <span class="muted" style="font-weight:400">(entrent en stock)</span></b>
        <label style="font-size:12px;color:var(--text2)">Répartition frais <select id="j-rep" class="form-select" style="width:auto;display:inline-block;padding:4px 8px"><option value="quantite">par quantité</option><option value="valeur">par valeur</option></select></label></div>
      <table class="lignes-table"><thead><tr><th>Article</th><th>Désignation</th><th class="right">Qté</th><th class="right">P.U.</th><th class="right">TVA%</th><th class="right">Coût entrée</th><th></th></tr></thead><tbody id="j-march"></tbody></table>
      <button class="btn btn-sm" id="jm-add" style="margin-top:4px"><i class="ti ti-plus"></i> Marchandise</button>
      <b style="font-size:13px;display:block;margin-top:16px">Frais annexes <span class="muted" style="font-weight:400">(intégrés au coût du stock)</span></b>
      <table class="lignes-table" style="margin-top:4px"><thead><tr><th>Frais</th><th class="right">Montant HT</th><th class="right">TVA%</th><th></th></tr></thead><tbody id="j-frais"></tbody></table>
      <button class="btn btn-sm" id="jf-add" style="margin-top:4px"><i class="ti ti-plus"></i> Frais</button>
      <div class="form-row" style="margin-top:16px"><div class="form-group"><label class="form-label">Solde rendu en caisse</label><input id="j-solde" class="form-input" type="number" step="any" value="0" /></div>
      <div class="form-group"><label class="form-label">Devise solde</label><select id="j-solde-dev" class="form-select"><option>USD</option><option>CDF</option></select></div></div>
      <div id="j-info" class="total-bar" style="justify-content:flex-start"></div>`,
    footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="j-ok"><i class="ti ti-check"></i> Soumettre la justification</button>`,
  });
  const av_montant = av.montant;
  const draw = () => {
    const tb = $("#j-lignes");
    tb.innerHTML = jlignes.map((l, i) => `<tr>
      <td><input class="form-input" data-i="${i}" data-f="nature" value="${esc(l.nature)}" /></td>
      <td><select class="form-input" data-i="${i}" data-f="devise"><option>USD</option><option ${l.devise === "CDF" ? "selected" : ""}>CDF</option></select></td>
      <td><input class="form-input" type="number" step="any" data-i="${i}" data-f="montant" value="${l.montant}" /></td>
      <td>${jlignes.length > 1 ? `<button class="btn btn-sm" data-del="${i}">×</button>` : ""}</td></tr>`).join("");
    tb.querySelectorAll("input,select").forEach((inp) => inp.oninput = () => {
      const l = jlignes[inp.dataset.i], f = inp.dataset.f;
      l[f] = f === "montant" ? parseFloat(inp.value || 0) : inp.value; info();
    });
    tb.querySelectorAll("[data-del]").forEach((b) => b.onclick = () => { jlignes.splice(b.dataset.del, 1); draw(); });
    info();
  };
  const info = () => {
    const charges = jlignes.filter((l) => (l.devise || "USD") === "USD").reduce((s, l) => s + (l.montant || 0), 0);
    const march = [];
    $("#j-march").querySelectorAll(".jm-row").forEach((tr) => {
      const q = +tr.querySelector(".jm-qte").value || 0, pu = +tr.querySelector(".jm-pu").value || 0, tx = +tr.querySelector(".jm-tva").value || 0;
      const ht = Math.round(q * pu * 100) / 100;
      march.push({ tr, ht, qte: q, tva: Math.round(ht * tx) / 100 });
    });
    let frais = 0, fraisTva = 0;
    $("#j-frais").querySelectorAll(".jf-row").forEach((tr) => {
      const mt = +tr.querySelector(".jf-mt").value || 0, tx = +tr.querySelector(".jf-tva").value || 0;
      frais += mt; fraisTva += Math.round(mt * tx) / 100;
    });
    frais = Math.round(frais * 100) / 100;
    if (march.length) {
      const key = $("#j-rep").value;
      const w = march.map((m) => key === "valeur" ? m.ht : m.qte);
      const tw = w.reduce((a, b) => a + b, 0) || 1; let cumul = 0;
      march.forEach((m, i) => {
        const part = i < march.length - 1 ? Math.round(frais * w[i] / tw * 100) / 100 : Math.round((frais - cumul) * 100) / 100;
        cumul = Math.round((cumul + part) * 100) / 100;
        m.tr.querySelector(".jm-ce").textContent = fmtNum(Math.round((m.ht + part) * 100) / 100);
      });
    }
    const marchTTC = march.reduce((s, m) => s + m.ht + m.tva, 0) + frais + fraisTva;
    const solde = $("#j-solde-dev").value === "USD" ? parseFloat($("#j-solde").value || 0) : 0;
    const justifie = Math.round((charges + marchTTC) * 100) / 100;
    const ecart = Math.round((av_montant - (justifie + solde)) * 100) / 100;
    $("#j-info").innerHTML = `<span class="lbl">Justifié <b>${fmtNum(justifie)}</b> + rendu <b>${fmtNum(solde)}</b> · écart <b style="color:${Math.abs(ecart) < 0.01 ? "var(--g)" : "var(--r)"}">${fmtNum(ecart)}${Math.abs(ecart) < 0.01 ? " ✓" : ""}</b></span>`;
  };
  const wireM = () => $("#j-march").querySelectorAll(".jm-row").forEach((tr) => {
    tr.querySelector(".jm-art").onchange = (e) => { const a = byId[e.target.value]; if (a) { tr.querySelector(".jm-des").value = a.designation; tr.querySelector(".jm-pu").value = a.prix_achat; tr.querySelector(".jm-tva").value = a.taux_tva; } info(); };
    ["jm-qte", "jm-pu", "jm-tva"].forEach((c) => tr.querySelector("." + c).oninput = info);
    tr.querySelector(".jm-del").onclick = () => { tr.remove(); info(); };
    tr.querySelector(".jm-anew").onclick = () => articleQuickModal((a) => {
      byId[a.id] = a;
      if(!artOpts.includes(`value="${a.id}"`))artOpts+=`<option value="${a.id}">${esc(a.code)} — ${esc(a.designation)}</option>`;
      document.querySelectorAll('.jm-art').forEach(sel=>Catalogue.addOption(sel,a,true));
      const sel = tr.querySelector(".jm-art"); sel.value = a.id; sel.dispatchEvent(new Event("change", { bubbles: true }));
    });
  });
  const wireF = () => $("#j-frais").querySelectorAll(".jf-row").forEach((tr) => {
    tr.querySelector(".jf-mt").oninput = info; tr.querySelector(".jf-tva").oninput = info;
    tr.querySelector(".jf-del").onclick = () => { tr.remove(); info(); };
  });
  $("#j-add").onclick = () => { jlignes.push({ nature: "", montant: 0 }); draw(); };
  $("#jm-add").onclick = () => { $("#j-march").insertAdjacentHTML("beforeend", mHTML()); wireM(); info(); };
  $("#jf-add").onclick = () => { $("#j-frais").insertAdjacentHTML("beforeend", fHTML()); wireF(); info(); };
  $("#j-rep").onchange = info;
  $("#j-solde").oninput = info; $("#j-solde-dev").onchange = info;
  $("#j-ok").onclick = async () => {
    const marchandises = [];
    for (const tr of $("#j-march").querySelectorAll(".jm-row")) {
      const qte = +tr.querySelector(".jm-qte").value || 0, pu = +tr.querySelector(".jm-pu").value || 0;
      const artId = tr.querySelector(".jm-art").value;
      if (!(qte > 0) || (!artId && !tr.querySelector(".jm-des").value.trim())) continue;
      marchandises.push({ article_id: artId || null, designation: tr.querySelector(".jm-des").value.trim() || null, qte, prix_unitaire: pu, taux_tva: +tr.querySelector(".jm-tva").value || 0 });
    }
    const frais = [];
    for (const tr of $("#j-frais").querySelectorAll(".jf-row")) {
      const mt = +tr.querySelector(".jf-mt").value || 0;
      if (!(mt > 0)) continue;
      frais.push({ libelle: tr.querySelector(".jf-lib").value.trim() || "Frais", montant_ht: mt, taux_tva: +tr.querySelector(".jf-tva").value || 0 });
    }
    try {
      const r = await api("/avances/justifier", { method: "POST", body: {
        avance_id: av.id, solde_retourne: parseFloat($("#j-solde").value || 0), devise_solde: $("#j-solde-dev").value,
        lignes: jlignes.filter((l) => l.nature).map((l) => ({ nature: l.nature, devise: l.devise || "USD", montant: l.montant })),
        marchandises, frais, repartition: $("#j-rep").value } });
      closeModal();
      toast(`Justification ${r.numero} enregistrée — écart ${fmtUSD(r.ecart_usd)}${r.complement_demande ? " (complément à demander)" : ""}`, "ok");
      go("avances");
    } catch (e) { toast(e.message, "ko"); }
  };
  draw();
  if (av.nature === "marchandise") { $("#jm-add").click(); }   // achat marchandises → onglet pré-ouvert
}

// Taux du jour
RENDER.taux = () => {
  const el = $("#view-taux");
  const today = isoLocal(new Date());
  el.innerHTML = `<div class="card" style="max-width:460px"><div class="card-body">
    <div class="banner"><i class="ti ti-info-circle"></i> Seul le DFI peut définir le taux du jour.</div>
    <div class="form-group"><label class="form-label">Date</label><input id="t-date" class="form-input" type="date" value="${today}" /></div>
    <div class="form-group"><label class="form-label">1 USD =</label>
      <div style="display:flex;gap:8px;align-items:center"><input id="t-taux" class="form-input" type="number" step="any" placeholder="2800" /><span class="tag">CDF</span></div></div>
    <button class="btn btn-primary" id="t-ok"><i class="ti ti-device-floppy"></i> Enregistrer le taux</button>
    <div class="err" id="t-err"></div></div></div>`;
  $("#t-ok").onclick = async () => {
    $("#t-err").textContent = "";
    try {
      await api("/taux", { method: "POST", body: { date_taux: $("#t-date").value, devise: "CDF", taux_usd: parseFloat($("#t-taux").value) } });
      toast("Taux enregistré.", "ok");
    } catch (e) { $("#t-err").textContent = e.message; }
  };
};

// ── Comptabilité : pièces en attente (couture caisse → compta) ───────
async function refreshComptaBadge() {
  try {
    const list = await api(`/comptabilite/ecritures?societe_id=${currentSocieteId}`);
    const b = document.querySelector('[data-badge="compta"]');
    if (b) { b.textContent = list.length; b.classList.toggle("hidden", list.length === 0); }
  } catch {}
}
const PROV_ICONS = { Caisse: "ti-cash", POS: "ti-device-desktop-analytics", Banque: "ti-building-bank",
  Achat: "ti-shopping-cart", Vente: "ti-tag", Transfert: "ti-arrows-exchange", "À-nouveaux": "ti-history", Divers: "ti-dots" };
const comptaExpanded = new Set();

// Filtres persistants de l'écran Pièces en attente (demande NB4 de Laurent)
let comptaFiltres = { q: "", prov: "", min: "", du: "", au: "" };
let _axesCache = null;
async function loadAxes(force) {
  if (force || !_axesCache || _axesCache.sid !== currentSocieteId) {
    _axesCache = { sid: currentSocieteId,
                   axes: await api(`/analytique/axes?societe_id=${currentSocieteId}`).catch(() => []) };
  }
  return _axesCache.axes.filter((a) => a.actif && (a.sections || []).some((s) => s.actif));
}

RENDER.compta = async () => {
  const el = $("#view-compta");
  el.innerHTML = `<div class="muted">Chargement…</div>`;
  let list, axes;
  try {
    [list, axes] = await Promise.all([
      api(`/comptabilite/ecritures?societe_id=${currentSocieteId}`), loadAxes(true)]);
  } catch (e) { el.innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }
  const plan = await loadPlan();
  const planDL = `<datalist id="compta-plan">${plan.map((c) => `<option value="${esc(c.numero)}">${esc(c.numero)} — ${esc(c.intitule)}</option>`).join("")}</datalist>`;
  window._comptaAxes = axes;

  // ── filtrage client (texte, provenance, montant, période) ──
  const f = comptaFiltres;
  const provs = [...new Set(list.map((e) => e.provenance || "Divers"))].sort();
  const visible = list.filter((e) =>
    (!f.prov || (e.provenance || "Divers") === f.prov)
    && (!f.min || e.montant >= +f.min)
    && (!f.du || e.date >= f.du) && (!f.au || e.date <= f.au)
    && (!f.q || `${e.numero} ${e.libelle} ${e.piece || ""} ${e.source || ""} ${e.journal || ""} ${e.lignes.map((l) => l.compte + " " + (l.tiers || "")).join(" ")}`
        .toLowerCase().includes(f.q.toLowerCase())));
  const total = Math.round(visible.reduce((s, e) => s + e.montant, 0) * 100) / 100;

  const barre = `<div class="card" style="margin-bottom:12px"><div class="card-body" style="display:flex;gap:10px;flex-wrap:wrap;align-items:center">
      <input id="pcf-q" class="form-input" placeholder="🔍 N°, libellé, compte, tiers, réf. pièce…" value="${esc(f.q)}" style="flex:1;min-width:220px" />
      <select id="pcf-prov" class="form-select" style="width:auto"><option value="">Toutes provenances</option>
        ${provs.map((p) => `<option ${f.prov === p ? "selected" : ""}>${esc(p)}</option>`).join("")}</select>
      <input id="pcf-min" class="form-input right" type="number" step="any" placeholder="Montant ≥" value="${esc(f.min)}" style="width:110px" />
      <input id="pcf-du" class="form-input" type="date" value="${esc(f.du)}" title="Du" style="width:150px" />
      <input id="pcf-au" class="form-input" type="date" value="${esc(f.au)}" title="Au" style="width:150px" />
      ${f.q || f.prov || f.min || f.du || f.au ? `<button class="btn btn-sm" id="pcf-raz"><i class="ti ti-x"></i> Effacer</button>` : ""}
      <span class="muted" style="margin-left:auto;font-size:12.5px"><b>${visible.length}</b> / ${list.length} pièce(s) · ${fmtUSD(total)}</span></div></div>`;

  if (!list.length) { el.innerHTML = `<div class="empty"><i class="ti ti-checks"></i>Aucune pièce comptable en attente — tout est validé.</div>`; return; }

  const estVentilable = (l) => l.compte && "67".includes(l.compte[0]);
  const lineRow = (l) => `<tr data-line="${l.id}" data-orig="${esc(l.compte)}" data-montant="${l.montant_usd}">
    <td><span class="pill" style="background:${l.sens === "D" ? "var(--tl)" : "var(--al)"};color:${l.sens === "D" ? "var(--t)" : "var(--a)"}">${l.sens === "D" ? "Débit" : "Crédit"}</span></td>
    <td><input class="form-input pc-compte" list="compta-plan" style="width:120px" value="${esc(l.compte)}" /><div class="pc-cint muted">${esc(l.intitule || "")}</div></td>
    <td class="muted">${esc(l.libelle || "")}</td><td>${esc(l.tiers || "—")}</td>
    <td class="right">${fmtUSD(l.montant_usd)}</td>
    <td class="right" style="white-space:nowrap">
      ${axes.length && estVentilable(l) ? `<button class="btn btn-sm pc-venti" data-line="${l.id}" title="Ventilation analytique (centres de coûts)"><i class="ti ti-chart-pie"></i></button>` : ""}
      <button class="btn btn-sm pc-split" data-line="${l.id}" title="Éclater sur plusieurs comptes"><i class="ti ti-arrows-split-2"></i></button></td></tr>`;

  const piece = (e) => `<div class="pc-piece ${comptaExpanded.has(e.id) ? "open" : ""}" data-piece="${e.id}">
    <div class="pc-head" data-toggle="${e.id}">
      <i class="ti ti-chevron-right chev"></i>
      <span class="num-cell">${esc(e.numero)}</span>
      <span class="muted" style="font-size:11.5px;white-space:nowrap">${e.date}</span>
      ${e.journal ? `<span class="tag">${esc(e.journal)}</span>` : ""}
      <span class="pc-lib">${esc(e.libelle)}${e.piece ? ` <span class="muted" style="font-size:11px">· pièce ${esc(e.piece)}</span>` : ""}</span>
      <button class="btn btn-sm" data-pj="${e.id}" title="Justificatifs (facture, bon de livraison, reçu…)"><i class="ti ti-paperclip"></i>${e.nb_pj ? ` ${e.nb_pj}` : ""}</button>
      <span class="pc-mt">${fmtUSD(e.montant)}</span>
      <button class="btn btn-sm btn-success" data-val="${e.id}"><i class="ti ti-check"></i> Valider</button></div>
    <div class="pc-body"><table class="pc-lines"><thead><tr><th style="width:64px">Sens</th><th>Compte d'imputation</th><th>Libellé</th><th>Tiers</th><th class="right">Montant</th><th></th></tr></thead>
      <tbody>${e.lignes.map(lineRow).join("")}</tbody></table>
      <div class="pc-hint muted"><i class="ti ti-info-circle"></i> Corrigez le compte, éclatez une ligne (<i class="ti ti-arrows-split-2"></i>), ventilez en analytique (<i class="ti ti-chart-pie"></i>), joignez les preuves (<i class="ti ti-paperclip"></i>) — puis validez.</div></div></div>`;

  const groups = {};
  visible.forEach((e) => (groups[e.provenance || "Divers"] ||= []).push(e));
  const cats = Object.keys(groups).sort();
  el.innerHTML = planDL + barre +
    (!visible.length ? `<div class="empty"><i class="ti ti-filter-off"></i>Aucune pièce ne correspond aux filtres.</div>`
      : cats.map((cat) => `<div class="pc-group">
        <div class="pc-group-hdr"><i class="ti ${PROV_ICONS[cat] || "ti-folder"}"></i> ${esc(cat)} <span class="muted">· ${groups[cat].length} · ${fmtUSD(Math.round(groups[cat].reduce((s, e) => s + e.montant, 0) * 100) / 100)}</span></div>
        ${groups[cat].map(piece).join("")}</div>`).join(""));

  // filtres
  const applique = () => { comptaFiltres = { q: $("#pcf-q").value, prov: $("#pcf-prov").value, min: $("#pcf-min").value, du: $("#pcf-du").value, au: $("#pcf-au").value }; RENDER.compta(); };
  let tmr;
  $("#pcf-q").oninput = () => { clearTimeout(tmr); tmr = setTimeout(applique, 350); };
  ["pcf-prov", "pcf-min", "pcf-du", "pcf-au"].forEach((i) => { const n = $("#" + i); if (n) n.onchange = applique; });
  if ($("#pcf-raz")) $("#pcf-raz").onclick = () => { comptaFiltres = { q: "", prov: "", min: "", du: "", au: "" }; RENDER.compta(); };

  el.querySelectorAll("[data-toggle]").forEach((h) => h.onclick = (ev) => {
    if (ev.target.closest("[data-val],[data-pj]")) return;
    const p = h.closest(".pc-piece"); p.classList.toggle("open");
    comptaExpanded[p.classList.contains("open") ? "add" : "delete"](h.dataset.toggle);
  });
  el.querySelectorAll("[data-pj]").forEach((b) => b.onclick = () => {
    const e = list.find((x) => x.id === b.dataset.pj);
    piecesModal("ecriture", e.id, `Justificatifs — ${e.numero}`);
  });
  el.querySelectorAll(".pc-split").forEach((b) => b.onclick = () => toggleSplit(b.closest(".pc-piece"), b.closest("tr")));
  el.querySelectorAll(".pc-venti").forEach((b) => b.onclick = () => toggleVentilation(b.closest(".pc-piece"), b.closest("tr")));
  el.querySelectorAll("[data-val]").forEach((b) => b.onclick = () => validerPiece(b.closest(".pc-piece"), b.dataset.val));
};

// Ventilation analytique d'une ligne — appliquée à la validation (NB4)
function toggleVentilation(pieceEl, lineTr) {
  const lineId = lineTr.dataset.line;
  const existing = pieceEl.querySelector(`.pc-venti-row[data-for="${lineId}"]`);
  if (existing) { existing.remove(); return; }
  const axes = window._comptaAxes || [];
  if (!axes.length) { toast("Créez d'abord vos axes analytiques (Comptabilité › Analytique).", "ko"); return; }
  const montant = parseFloat(lineTr.dataset.montant) || 0;
  const row = document.createElement("tr");
  row.className = "pc-venti-row"; row.dataset.for = lineId;
  const secOpts = (axe) => (axe.sections || []).filter((s) => s.actif)
    .map((s) => `<option value="${s.id}">${esc(s.code)} — ${esc(s.libelle)}</option>`).join("");
  row.innerHTML = `<td colspan="6"><div class="split-box" style="border-left:3px solid var(--t)">
    <div style="display:flex;gap:10px;align-items:center;margin-bottom:6px">
      <i class="ti ti-chart-pie" style="color:var(--t)"></i>
      <b style="font-size:12.5px">Ventilation analytique de ${fmtUSD(montant)}</b>
      <select class="form-select vt-axe" style="width:auto">${axes.map((a, i) => `<option value="${a.id}" data-i="${i}">${esc(a.code)} — ${esc(a.libelle)}</option>`).join("")}</select></div>
    <div class="vt-lines"></div>
    <div style="display:flex;gap:12px;align-items:center;margin-top:4px">
      <button class="btn btn-sm vt-add"><i class="ti ti-plus"></i> Ajouter une section</button>
      <span class="vt-reste muted"></span></div></div></td>`;
  lineTr.after(row);
  const box = row.querySelector(".vt-lines");
  const reste = () => {
    let t = 0; box.querySelectorAll(".vt-mt").forEach((x) => t += parseFloat(x.value || 0) || 0);
    const r = Math.round((montant - t) * 100) / 100, s = row.querySelector(".vt-reste");
    s.textContent = Math.abs(r) < 0.01 ? "entièrement ventilé ✓" : (r > 0 ? `non ventilé : ${fmtNum(r)}` : `dépassement de ${fmtNum(-r)} !`);
    s.style.color = r < -0.009 ? "var(--r)" : (Math.abs(r) < 0.01 ? "var(--g)" : "var(--a)");
  };
  const axeCourant = () => axes[+row.querySelector(".vt-axe").selectedOptions[0].dataset.i];
  const addLine = (m) => {
    const d = document.createElement("div");
    d.style = "display:flex;gap:8px;margin-bottom:6px";
    d.innerHTML = `<select class="form-select vt-sec" style="flex:1">${secOpts(axeCourant())}</select>
      <input class="form-input vt-mt right" type="number" step="any" placeholder="0.00" style="width:110px" value="${m || ""}" />
      <button class="btn btn-sm vt-del"><i class="ti ti-trash"></i></button>`;
    box.appendChild(d);
    d.querySelector(".vt-mt").oninput = reste;
    d.querySelector(".vt-del").onclick = () => { if (box.children.length > 1) { d.remove(); reste(); } };
  };
  row.querySelector(".vt-axe").onchange = () => { box.innerHTML = ""; addLine(montant); reste(); };
  row.querySelector(".vt-add").onclick = () => addLine("");
  addLine(montant); reste();
}

function toggleSplit(pieceEl, lineTr) {
  const lineId = lineTr.dataset.line;
  const existing = pieceEl.querySelector(`.pc-split-row[data-for="${lineId}"]`);
  if (existing) { existing.remove(); lineTr.classList.remove("splitting"); return; }
  const montant = parseFloat(lineTr.dataset.montant) || 0;
  const compte = lineTr.querySelector(".pc-compte").value;
  lineTr.classList.add("splitting");
  const row = document.createElement("tr");
  row.className = "pc-split-row"; row.dataset.for = lineId;
  row.innerHTML = `<td colspan="6"><div class="split-box">
    <div class="muted" style="margin-bottom:6px">Répartir <b>${fmtUSD(montant)}</b> sur plusieurs comptes :</div>
    <div class="split-lines"></div>
    <div style="display:flex;gap:12px;align-items:center;margin-top:4px">
      <button class="btn btn-sm split-add"><i class="ti ti-plus"></i> Ajouter un compte</button>
      <span class="split-reste"></span></div></div></td>`;
  lineTr.after(row);
  const box = row.querySelector(".split-lines");
  const reste = () => {
    let t = 0; box.querySelectorAll(".sl-mt").forEach((x) => t += parseFloat(x.value || 0) || 0);
    const r = Math.round((montant - t) * 100) / 100, s = row.querySelector(".split-reste");
    s.textContent = Math.abs(r) < 0.01 ? "réparti ✓" : `reste ${fmtNum(r)}`;
    s.style.color = Math.abs(r) < 0.01 ? "var(--g)" : "var(--r)";
  };
  const addLine = (c, m) => {
    const d = document.createElement("div"); d.className = "split-line";
    d.style = "display:flex;gap:8px;margin-bottom:6px";
    d.innerHTML = `<input class="form-input sl-compte" list="compta-plan" placeholder="compte" style="width:120px" value="${c || ""}" />
      <input class="form-input sl-lib" placeholder="libellé (optionnel)" style="flex:1" />
      <input class="form-input sl-mt right" type="number" step="any" placeholder="0.00" style="width:110px" value="${m || ""}" />
      <button class="btn btn-sm sl-del"><i class="ti ti-trash"></i></button>`;
    box.appendChild(d);
    d.querySelector(".sl-mt").oninput = reste;
    d.querySelector(".sl-del").onclick = () => { if (box.children.length > 1) { d.remove(); reste(); } };
  };
  addLine(compte, montant); addLine("", ""); reste();
  row.querySelector(".split-add").onclick = () => addLine("", "");
}

async function validerPiece(pieceEl, id) {
  const reclassements = [], splits = [], ventilations = [];
  pieceEl.querySelectorAll("tbody > tr[data-line]").forEach((tr) => {
    const lineId = tr.dataset.line;
    const splitRow = pieceEl.querySelector(`.pc-split-row[data-for="${lineId}"]`);
    const ventiRow = pieceEl.querySelector(`.pc-venti-row[data-for="${lineId}"]`);
    if (splitRow) {
      const repartition = [];
      splitRow.querySelectorAll(".split-line").forEach((d) => {
        const compte = d.querySelector(".sl-compte").value.trim();
        const montant = parseFloat(d.querySelector(".sl-mt").value || 0) || 0;
        if (compte && montant > 0) repartition.push({ compte_numero: compte, montant, libelle: d.querySelector(".sl-lib").value.trim() || null });
      });
      if (repartition.length) splits.push({ ligne_id: lineId, repartition });
      if (ventiRow) toast("Ligne éclatée : ventilez l'analytique après validation, depuis le Grand livre.", "warn");
    } else {
      const v = tr.querySelector(".pc-compte").value.trim();
      if (v && v !== tr.dataset.orig) reclassements.push({ ligne_id: lineId, compte_numero: v });
      if (ventiRow) {
        const axeId = ventiRow.querySelector(".vt-axe").value;
        const repartition = [];
        ventiRow.querySelectorAll(".vt-lines > div").forEach((d) => {
          const montant = parseFloat(d.querySelector(".vt-mt").value || 0) || 0;
          if (montant > 0) repartition.push({ section_id: d.querySelector(".vt-sec").value, montant });
        });
        if (repartition.length) ventilations.push({ ligne_id: lineId, axe_id: axeId, repartition });
      }
    }
  });
  try {
    const r = await api(`/comptabilite/ecritures/${id}/valider`, { method: "POST", body: { reclassements, splits } });
    let nbVenti = 0;
    for (const v of ventilations) {
      try {
        await api(`/analytique/ventiler`, { method: "POST", body: { societe_id: currentSocieteId, ...v } });
        nbVenti++;
      } catch (e) { toast(`Analytique non appliquée sur une ligne : ${e.message}`, "warn"); }
    }
    const bits = [];
    if (r.reclassements) bits.push(`${r.reclassements} reclassement(s)`);
    if (r.splits) bits.push(`${r.splits} éclatement(s)`);
    if (nbVenti) bits.push(`${nbVenti} ventilation(s) analytique(s)`);
    comptaExpanded.delete(id);
    toast(`Pièce validée${bits.length ? " (" + bits.join(", ") + ")" : ""}.`, "ok");
    refreshComptaBadge(); RENDER.compta();
  } catch (err) { toast(err.message, "ko"); }
}

// ── Caisse : session, mouvements (dialogue + billetage), journal ─────
const DENOM = { USD: [100, 50, 20, 10, 5, 2, 1], CDF: [20000, 10000, 5000, 2000, 1000, 500, 200, 100, 50] };
const NATURES = {
  entree: ["Encaissement vente", "Encaissement client", "Réapprovisionnement", "Retour d'avance / trop-perçu", "Cession reçue", "Autre entrée"],
  sortie: ["Dépense", "Cession vers coffre / banque", "Remboursement", "Autre sortie"],
};
let caisseCourante = null;
const hhmm = (iso) => iso ? new Date(iso).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" }) : "";
RENDER.caisse = async () => {
  const el = $("#view-caisse");
  el.innerHTML = `<div class="muted">Chargement…</div>`;
  const caisses = await api(`/caisses?societe_id=${currentSocieteId}`);
  if (!caisses.length) { el.innerHTML = `<div class="empty"><i class="ti ti-cash"></i>Aucune caisse configurée.</div>`; return; }
  if (!caisseCourante || !caisses.find((c) => c.id === caisseCourante)) caisseCourante = caisses[0].id;
  const j = await api(`/caisse/${caisseCourante}/journal`);

  // Vue d'ensemble : une carte par caisse (solde, session), cliquable pour sélectionner
  const gestionnaire = has("DFI", "PRESIDENT", "ADMIN_SYS", "DG");
  let h = `${gestionnaire ? `<div class="section-hdr" style="margin-bottom:12px">
    <div class="section-title"><i class="ti ti-cash"></i> Caisses de la société (${caisses.length})</div>
    <button class="btn btn-sm btn-primary" id="ca-new" style="margin-left:auto"><i class="ti ti-plus"></i> Nouvelle caisse</button></div>` : ""}
  <div class="caisse-cards">
    ${caisses.map((c) => `<div class="caisse-card ${c.id === caisseCourante ? "on" : ""}" data-csel="${c.id}">
      <div class="cc-top"><b>${esc(c.libelle)}</b>${c.est_principale ? '<span class="tag">principale</span>' : ""}${c.point_vente ? `<span class="tag" title="point de vente lié">${esc(c.point_vente)}</span>` : ""}
        ${gestionnaire ? `<button class="btn btn-sm" data-cmod="${c.id}" title="Modifier la caisse" style="margin-left:auto"><i class="ti ti-pencil"></i></button>` : ""}</div>
      <div class="cc-soldes">${c.session_ouverte && c.soldes
        ? `<span>${fmtNum(c.soldes.USD || 0)} $</span><span class="cc-cdf">${fmtNum(c.soldes.CDF || 0)} FC</span>`
        : '<span class="muted">—</span>'}</div>
      <div class="cc-status ${c.session_ouverte ? "open" : ""}"><i class="ti ${c.session_ouverte ? "ti-lock-open" : "ti-lock"}"></i>
        ${c.session_ouverte ? `Ouverte${c.ouverte_depuis ? " depuis " + hhmm(c.ouverte_depuis) : ""}` : "Fermée"}</div>
    </div>`).join("")}</div>`;

  if (!j.ouverte) {
    h += `<div class="card"><div class="card-body" style="text-align:center;padding:38px">
      <i class="ti ti-lock" style="font-size:34px;color:var(--graym)"></i>
      <p class="muted" style="margin:8px 0 16px">La caisse « ${esc(j.caisse)} » est <b>fermée</b>. Ouvrez une session pour saisir des mouvements.</p>
      <button class="btn btn-primary" id="c-open"><i class="ti ti-lock-open"></i> Ouvrir la caisse</button></div></div>`;
  } else {
    const s = j.soldes;
    h += `<div class="kpi-row">
      <div class="kpi-card" style="--accent:var(--t);--kpi-color:var(--t)"><div class="kpi-label"><i class="ti ti-cash"></i> Solde caisse — USD</div><div class="kpi-val">${fmtNum(s.USD || 0)}</div><div class="kpi-sub">disponible en temps réel</div></div>
      <div class="kpi-card" style="--accent:var(--a);--kpi-color:var(--a)"><div class="kpi-label"><i class="ti ti-cash"></i> Solde caisse — CDF</div><div class="kpi-val">${fmtNum(s.CDF || 0)}</div><div class="kpi-sub">francs congolais</div></div></div>
      <div style="display:flex;gap:10px;margin-bottom:16px">
        <button class="btn btn-success" id="c-in"><i class="ti ti-arrow-down-left"></i> Encaissement (entrée)</button>
        <button class="btn btn-danger" id="c-out"><i class="ti ti-arrow-up-right"></i> Sortie</button>
        ${(() => { const cur = caisses.find((c) => c.id === caisseCourante), princ = caisses.find((c) => c.est_principale); return (cur && !cur.est_principale && princ) ? `<button class="btn" id="c-remise"><i class="ti ti-arrows-transfer-up"></i> Remettre au caissier principal</button>` : ""; })()}
        <button class="btn" id="c-close" style="margin-left:auto"><i class="ti ti-lock"></i> Clôturer la caisse</button></div>
      <div class="card"><div class="card-hdr"><div class="card-hdr-title"><i class="ti ti-book-2"></i> Journal de caisse</div></div>
      <div class="card-body">${j.mouvements.length ? `<table><thead><tr><th>Heure</th><th>N° bon</th><th>Nature</th><th>Bénéf./Provenance</th><th>Réf.</th><th>Sens</th><th class="right">Montant</th><th class="right">Solde après</th><th></th></tr></thead><tbody>
        ${j.mouvements.map((m) => `<tr><td>${hhmm(m.heure)}</td><td class="num-cell">${esc(m.numero || "")}</td><td>${esc(m.libelle || m.nature)} ${m.a_billetage ? '<i class="ti ti-coins" title="billetage saisi" style="color:var(--am)"></i>' : ""}</td>
          <td>${esc(m.tiers || "—")}</td><td class="muted">${esc(m.reference || "—")}</td>
          <td><span class="pill" style="background:${m.sens === "entree" ? "var(--gl)" : "var(--rl)"};color:${m.sens === "entree" ? "var(--g)" : "var(--r)"}">${m.sens === "entree" ? "Entrée" : "Sortie"}</span></td>
          <td class="right">${m.sens === "entree" ? "+" : "−"} ${fmtNum(m.montant)} ${m.devise}</td>
          <td class="right"><b>${fmtNum(m.solde_apres)} ${m.devise}</b></td>
          <td class="right"><button class="btn btn-sm" data-pbc="${m.id}" title="Imprimer le bon"><i class="ti ti-printer"></i></button></td></tr>`).join("")}
      </tbody></table>` : `<div class="muted">Aucun mouvement dans cette session.</div>`}</div></div>`;
  }

  el.innerHTML = h;
  el.querySelectorAll("[data-pbc]").forEach((b) => b.onclick = () => printBonCaisse(b.dataset.pbc));
  el.querySelectorAll("[data-csel]").forEach((c) => c.onclick = () => { caisseCourante = c.dataset.csel; RENDER.caisse(); });
  const caNew = $("#ca-new");
  if (caNew) caNew.onclick = () => caisseModal(null, () => RENDER.caisse());
  el.querySelectorAll("[data-cmod]").forEach((b) => b.onclick = (ev) => {
    ev.stopPropagation();
    caisseModal(caisses.find((x) => x.id === b.dataset.cmod), () => RENDER.caisse());
  });
  if ($("#c-open")) $("#c-open").onclick = () => ouvrirCaisseModal();
  if ($("#c-in")) $("#c-in").onclick = () => mouvementModal("entree");
  if ($("#c-out")) $("#c-out").onclick = () => mouvementModal("sortie");
  if ($("#c-remise")) $("#c-remise").onclick = () => { const princ = caisses.find((c) => c.est_principale); transfertModal({ sourceId: caisseCourante, destId: princ.id, motif: "Remise recette POS" }); };
  if ($("#c-close")) $("#c-close").onclick = () => clotureModal(j.soldes);
};

function ouvrirCaisseModal(caisseId, onDone) {
  caisseId = caisseId || caisseCourante;
  onDone = onDone || RENDER.caisse;
  modal({
    title: "Ouvrir la caisse — fond initial",
    body: `<div class="banner"><i class="ti ti-info-circle"></i> Saisissez le fond de caisse au démarrage de la journée (billets déjà présents).</div>
      <div class="form-row"><div class="form-group"><label class="form-label">Fond initial USD</label><input id="o-usd" class="form-input" type="number" step="any" value="0" /></div>
      <div class="form-group"><label class="form-label">Fond initial CDF</label><input id="o-cdf" class="form-input" type="number" step="any" value="0" /></div></div>`,
    footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="o-ok"><i class="ti ti-lock-open"></i> Ouvrir</button>`,
  });
  $("#o-ok").onclick = async () => {
    try {
      await api(`/caisse/${caisseId}/ouvrir`, { method: "POST", body: {
        fond_initial_usd: parseFloat($("#o-usd").value || 0), fond_initial_cdf: parseFloat($("#o-cdf").value || 0) } });
      closeModal(); toast("Caisse ouverte.", "ok"); onDone();
    } catch (e) { toast(e.message, "ko"); }
  };
}

async function mouvementModal(sens) {
  const entree = sens === "entree";
  const tiers = await api(`/tiers?societe_id=${currentSocieteId}`).catch(() => []);
  const st = { A: false, B: false };   // billetage activé par volet
  const voletHTML = (p, defDev) => `<div class="card ${p === "B" ? "hidden" : ""}" id="m${p}-wrap" style="margin-bottom:12px"><div class="card-body">
      <div class="form-row"><div class="form-group"><label class="form-label">Devise${p === "B" ? " (2)" : ""}</label>
        <select id="m${p}-dev" class="form-select">${["USD", "CDF"].map((d) => `<option ${d === defDev ? "selected" : ""}>${d}</option>`).join("")}</select></div>
      <div class="form-group"><label class="form-label">Montant</label><input id="m${p}-mt" class="form-input" type="number" step="any" placeholder="0.00" /></div></div>
      <label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-size:12px"><input type="checkbox" id="m${p}-btgl" style="width:auto" /> Détailler le billetage</label>
      <div id="m${p}-bill" class="hidden"></div></div></div>`;
  modal({
    title: entree ? "Encaissement — entrée de caisse" : "Sortie de caisse",
    body: `<div class="form-group"><label class="form-label">Nature</label>
        <select id="m-nature" class="form-select">${NATURES[sens].map((n) => `<option>${n}</option>`).join("")}</select></div>
      <div class="form-group"><label class="form-label">${entree ? "Provenance (de qui reçoit-on ?)" : "Bénéficiaire (à qui paie-t-on ?)"}</label>
        <input id="m-benef" class="form-input" list="m-tiers-list" placeholder="Nom ou choisir dans la liste" />
        <datalist id="m-tiers-list">${tiers.map((t) => `<option value="${esc(Catalogue.label(t))}">`).join("")}</datalist></div>
      <div class="form-group"><label class="form-label">Référence réquisition (optionnel${entree ? "" : ", recommandé"})</label>
        <input id="m-ref" class="form-input" placeholder="ex. REQ-PLA-2026-000012" /></div>
      ${voletHTML("A", "USD")}
      <label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-size:13px;margin-bottom:12px">
        <input type="checkbox" id="m-mixte" style="width:auto" /> Opération en <b>deux devises</b> (USD + CDF dans la même opération)</label>
      ${voletHTML("B", "CDF")}
      <div class="form-group"><label class="form-label">Libellé (optionnel)</label><input id="m-lib" class="form-input" /></div>`,
    footer: `<button class="btn" onclick="closeModal()">Annuler</button>
      <button class="btn ${entree ? "btn-success" : "btn-danger"}" id="m-ok"><i class="ti ti-check"></i> Enregistrer</button>`,
  });
  const grid = (dev) => `<table class="lignes-table"><thead><tr><th>Coupure</th><th>Nombre</th><th class="right">Sous-total</th></tr></thead><tbody>
      ${DENOM[dev].map((d) => `<tr><td>${fmtNum(d)} ${dev}</td><td><input class="form-input bn" data-d="${d}" type="number" min="0" step="1" style="width:80px" value="0" /></td><td class="right bst">0</td></tr>`).join("")}
    </tbody></table><div class="total-bar"><span class="lbl">Total</span><span class="val tot">0</span></div>`;
  const wire = (p) => {
    const draw = () => {
      const box = $(`#m${p}-bill`); box.innerHTML = grid($(`#m${p}-dev`).value);
      box.querySelectorAll(".bn").forEach((inp) => inp.oninput = () => {
        let t = 0; box.querySelectorAll(".bn").forEach((x) => { const s = (parseFloat(x.dataset.d) || 0) * (parseInt(x.value || 0) || 0); x.closest("tr").querySelector(".bst").textContent = fmtNum(s); t += s; });
        box.querySelector(".tot").textContent = fmtNum(t); $(`#m${p}-mt`).value = t;
      });
    };
    $(`#m${p}-btgl`).onchange = (e) => { st[p] = e.target.checked; $(`#m${p}-bill`).classList.toggle("hidden", !st[p]); $(`#m${p}-mt`).readOnly = st[p]; if (st[p]) draw(); else $(`#m${p}-bill`).innerHTML = ""; };
    $(`#m${p}-dev`).onchange = () => { if (st[p]) draw(); };
  };
  wire("A"); wire("B");
  $("#m-mixte").onchange = (e) => $("#mB-wrap").classList.toggle("hidden", !e.target.checked);
  $("#m-ok").onclick = async () => {
    const collect = (p) => {
      const montant = parseFloat($(`#m${p}-mt`).value || 0);
      if (!(montant > 0)) return null;
      let billetage = null;
      if (st[p]) { billetage = {}; $(`#m${p}-bill`).querySelectorAll(".bn").forEach((x) => { const n = parseInt(x.value || 0); if (n > 0) billetage[x.dataset.d] = n; }); if (!Object.keys(billetage).length) billetage = null; }
      return { devise: $(`#m${p}-dev`).value, montant, billetage };
    };
    const legs = []; const a = collect("A"); if (a) legs.push(a);
    if ($("#m-mixte").checked) { const b = collect("B"); if (b) legs.push(b); }
    if (!legs.length) { toast("Montant requis.", "ko"); return; }
    try {
      const r = await api(`/caisse/${caisseCourante}/operation`, { method: "POST", body: {
        sens, nature: $("#m-nature").value, beneficiaire: $("#m-benef").value || null,
        reference: $("#m-ref").value || null, libelle: $("#m-lib").value || null, legs } });
      closeModal(); toast(`Opération enregistrée (${esc(r.numero)}) — solde ${fmtNum(r.soldes.USD || 0)} USD / ${fmtNum(r.soldes.CDF || 0)} CDF`, "ok");
      if (r.mouvement_id) printBonCaisse(r.mouvement_id);   // bon de caisse imprimable auto
      RENDER.caisse();
    } catch (e) { toast(e.message, "ko"); }
  };
}

// Clôture de caisse — comptage physique, écart théorique/physique, rapport Z
function clotureModal(theorique, caisseId, onDone) {
  caisseId = caisseId || caisseCourante;
  onDone = onDone || RENDER.caisse;
  const th = { USD: theorique.USD || 0, CDF: theorique.CDF || 0 };
  const bill = { USD: false, CDF: false };   // billetage détaillé activé par devise
  const devBloc = (dev) => `<div class="card" style="margin-bottom:12px"><div class="card-body">
      <div class="form-row">
        <div class="form-group"><label class="form-label">Solde théorique ${dev}</label>
          <input class="form-input" value="${fmtNum(th[dev])}" readonly style="background:#f4f4f8" /></div>
        <div class="form-group"><label class="form-label">Comptage physique ${dev}</label>
          <input id="z-${dev}-phys" class="form-input" type="number" step="any" value="${th[dev]}" /></div>
        <div class="form-group"><label class="form-label">Écart</label>
          <input id="z-${dev}-ec" class="form-input" value="0" readonly style="font-weight:700" /></div></div>
      <label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-size:12px"><input type="checkbox" id="z-${dev}-btgl" style="width:auto" /> Détailler le billetage ${dev}</label>
      <div id="z-${dev}-bill" class="hidden"></div></div></div>`;
  modal({
    title: "Clôture de caisse — comptage & rapport Z",
    body: `<div class="banner"><i class="ti ti-info-circle"></i> Comptez les espèces réellement présentes. L'écart entre le solde théorique et le physique sera enregistré. Une justification est exigée en cas d'écart.</div>
      ${devBloc("USD")}${devBloc("CDF")}
      <div class="form-group"><label class="form-label">Commentaire / justification de l'écart</label>
        <textarea id="z-comm" class="form-input" rows="2" placeholder="Obligatoire si un écart est constaté"></textarea></div>`,
    footer: `<button class="btn" onclick="closeModal()">Annuler</button>
      <button class="btn btn-primary" id="z-ok"><i class="ti ti-lock"></i> Clôturer &amp; imprimer le Z</button>`,
  });
  const grid = (dev) => `<table class="lignes-table"><thead><tr><th>Coupure</th><th>Nombre</th><th class="right">Sous-total</th></tr></thead><tbody>
      ${DENOM[dev].map((d) => `<tr><td>${fmtNum(d)} ${dev}</td><td><input class="form-input zbn" data-d="${d}" type="number" min="0" step="1" style="width:80px" value="0" /></td><td class="right zbst">0</td></tr>`).join("")}
    </tbody></table><div class="total-bar"><span class="lbl">Total compté</span><span class="val ztot">0</span></div>`;
  const majEcart = (dev) => {
    const ec = Math.round(((parseFloat($(`#z-${dev}-phys`).value || 0)) - th[dev]) * 100) / 100;
    const f = $(`#z-${dev}-ec`); f.value = fmtNum(ec);
    f.style.color = Math.abs(ec) < 0.01 ? "var(--g)" : "var(--r)";
  };
  ["USD", "CDF"].forEach((dev) => {
    $(`#z-${dev}-phys`).oninput = () => majEcart(dev);
    majEcart(dev);
    $(`#z-${dev}-btgl`).onchange = (e) => {
      bill[dev] = e.target.checked;
      const box = $(`#z-${dev}-bill`); box.classList.toggle("hidden", !bill[dev]);
      $(`#z-${dev}-phys`).readOnly = bill[dev];
      if (!bill[dev]) { box.innerHTML = ""; return; }
      box.innerHTML = grid(dev);
      box.querySelectorAll(".zbn").forEach((inp) => inp.oninput = () => {
        let t = 0; box.querySelectorAll(".zbn").forEach((x) => { const s = (parseFloat(x.dataset.d) || 0) * (parseInt(x.value || 0) || 0); x.closest("tr").querySelector(".zbst").textContent = fmtNum(s); t += s; });
        box.querySelector(".ztot").textContent = fmtNum(t); $(`#z-${dev}-phys`).value = t; majEcart(dev);
      });
    };
  });
  $("#z-ok").onclick = async () => {
    const collectBill = (dev) => {
      if (!bill[dev]) return null;
      const b = {}; $(`#z-${dev}-bill`).querySelectorAll(".zbn").forEach((x) => { const n = parseInt(x.value || 0); if (n > 0) b[x.dataset.d] = n; });
      return Object.keys(b).length ? b : null;
    };
    try {
      const r = await api(`/caisse/${caisseId}/cloturer`, { method: "POST", body: {
        physique_usd: parseFloat($("#z-USD-phys").value || 0),
        physique_cdf: parseFloat($("#z-CDF-phys").value || 0),
        billetage_usd: collectBill("USD"), billetage_cdf: collectBill("CDF"),
        commentaire: $("#z-comm").value || null } });
      closeModal();
      const em = (Math.abs(r.ecart.USD) > 0.01 || Math.abs(r.ecart.CDF) > 0.01);
      toast(`Caisse clôturée.${em ? " Écart constaté — voir rapport Z." : ""}${r.escalade_dfi ? " ⚠ À escalader au DFI." : ""}`, em ? "warn" : "ok");
      printRapportZ(r);
      onDone();
    } catch (e) { toast(e.message, "ko"); }
  };
}

function printRapportZ(d) {
  const dev = (o, k) => (o && o[k]) ? o[k] : 0;
  const totRow = (label, k) => `<div class="row"><span class="lbl">${label}</span><span>${fmtNum(dev(d.totaux[k], "entrees"))} entrées · ${fmtNum(dev(d.totaux[k], "sorties"))} sorties · ${dev(d.totaux[k], "nb")} op.</span></div>`;
  const soldeRow = (k) => {
    const ec = d.ecart[k] || 0;
    return `<div class="row"><span class="lbl">${k}</span><span>Théo. <b>${fmtNum(d.theorique[k] || 0)}</b> · Phys. <b>${fmtNum(d.physique[k] || 0)}</b> · Écart <b style="color:${Math.abs(ec) < 0.01 ? "#127f3d" : "#c0392b"}">${fmtNum(ec)}</b></span></div>`;
  };
  const w = Editions.fenetre();
  w.document.write(`<html><head><meta charset="utf-8"><title>Rapport Z — ${esc(d.caisse || "")}</title><style>
    body{font-family:Arial,sans-serif;padding:34px;color:#222}h1{font-size:18px;color:#3C3489;margin:0 0 2px}
    .sub{color:#666;margin-bottom:16px}h2{font-size:13px;color:#3C3489;margin:18px 0 6px;border-bottom:2px solid #3C3489;padding-bottom:3px}
    .row{display:flex;justify-content:space-between;margin:4px 0;border-bottom:1px solid #eee;padding-bottom:4px;font-size:13px}
    .lbl{color:#777}.warn{background:#fff4e5;border:1px solid #f0b775;color:#8a5300;padding:8px 12px;border-radius:6px;margin-top:12px;font-size:12px}
    .sign{margin-top:54px;display:flex;justify-content:space-between}.sign div{border-top:1px solid #999;width:42%;text-align:center;padding-top:6px;font-size:12px;color:#666}</style></head><body>
    <h1>RAPPORT DE CLÔTURE DE CAISSE (Z)</h1>
    <div class="sub">${esc(d.societe || "")} — ${esc(d.caisse || "")}</div>
    <div class="row"><span class="lbl">Ouverture</span><span>${d.date_ouverture ? new Date(d.date_ouverture).toLocaleString("fr-FR") : "—"} · ${esc(d.ouvert_par || "")}</span></div>
    <div class="row"><span class="lbl">Clôture</span><span>${d.date_cloture ? new Date(d.date_cloture).toLocaleString("fr-FR") : "—"} · ${esc(d.cloture_par || "")}</span></div>
    <h2>Fond initial</h2>
    <div class="row"><span class="lbl">USD</span><span>${fmtNum(d.fond_initial.USD || 0)}</span></div>
    <div class="row"><span class="lbl">CDF</span><span>${fmtNum(d.fond_initial.CDF || 0)}</span></div>
    <h2>Mouvements de la session</h2>
    ${totRow("USD", "USD")}${totRow("CDF", "CDF")}
    <h2>Comptage de clôture</h2>
    ${soldeRow("USD")}${soldeRow("CDF")}
    ${d.commentaire ? `<div class="row"><span class="lbl">Justification</span><span>${esc(d.commentaire)}</span></div>` : ""}
    ${d.escalade_dfi ? `<div class="warn">⚠ Écart supérieur au seuil autorisé (${fmtNum(d.seuil_ecart_usd || 0)} USD) — à transmettre au DFI pour validation.</div>` : ""}
    <div class="sign"><div>Caissier<br>${esc(d.cloture_par || "")}</div><div>Contrôle / DFI</div></div>
    </body></html>`);
  w.document.close(); w.focus(); setTimeout(() => w.print(), 350);
}
window.printRapportZ = printRapportZ;

// Caisse : décaissements à exécuter (ordres validés)
RENDER["caisse-exec"] = async () => {
  const el = $("#view-caisse-exec");
  el.innerHTML = `<div class="muted">Chargement…</div>`;
  const list = await api(`/ordres-depense?societe_id=${currentSocieteId}&statut=valide`);
  if (!list.length) { el.innerHTML = `<div class="empty"><i class="ti ti-checks"></i>Aucun ordre validé à exécuter.</div>`; return; }
  el.innerHTML = `<div class="banner"><i class="ti ti-info-circle"></i> Ordres validés (sortie de fonds autorisée). À l'exécution : un bon de sortie est généré et une pièce comptable part en attente chez le comptable. Caisse = caissier · Banque = comptable (OP/chèque).</div>` +
    list.map((o) => `<div class="item ordre"><div class="top"><div>
      <div class="num">${esc(o.numero)}</div><div class="titre">${esc(o.beneficiaire || "")} — ${esc(o.motif || "")}</div>
      <div class="meta"><span class="tag">${o.mode_paiement === "banque" ? "Banque" : "Caisse"}</span> palier ${esc(o.palier_applique || "")}
        ${o.montant_paye_usd > 0 ? `<span class="tag" style="background:var(--al);color:var(--a)">déjà payé ${fmtUSD(o.montant_paye_usd)}</span>` : ""}</div></div>
      <div class="montant">${o.montant_paye_usd > 0 ? `${fmtUSD(o.reste_usd)}<div class="meta" style="text-align:right">reste / ${fmtUSD(o.montant_autorise_usd)}</div>` : fmtUSD(o.montant_autorise_usd)}</div></div>
      <div class="actions"><button class="btn btn-primary btn-sm" data-exec="${o.id}" data-mode="${o.mode_paiement}" data-md="${o.mode_decaissement}" data-benef="${o.beneficiaire_tiers_id}" data-devise="${o.devise}" data-reste="${o.reste_usd}" data-req="${esc(o.requisition_numero || "")}" data-objet="${esc(o.requisition_objet || "")}">
        <i class="ti ti-cash"></i> ${o.mode_paiement === "banque" ? "Établir OP / chèque" : "Payer (caisse)"}</button></div></div>`).join("");
  el.querySelectorAll("[data-exec]").forEach((b) => b.onclick = () => executer(b.dataset.exec, b.dataset.mode, b.dataset.md, b.dataset.benef, b.dataset.devise, b.dataset.reste, b.dataset.req, b.dataset.objet));
};

// ── Transferts de fonds (#5) ─────────────────────────────────────────
RENDER.transferts = async () => {
  const el = $("#view-transferts");
  el.innerHTML = `<div class="muted">Chargement…</div>`;
  const list = await api(`/transferts?societe_id=${currentSocieteId}`);
  const aValider = list.filter((t) => t.peut_valider);
  const ep = (type, lbl) => `<span class="tag">${type === "banque" ? '<i class="ti ti-building-bank"></i>' : '<i class="ti ti-cash"></i>'} ${esc(lbl)}</span>`;
  let h = `<div class="section-hdr"><div class="section-title"><i class="ti ti-arrows-exchange"></i> Transferts de fonds</div>
    <button class="btn btn-primary" id="t-new" style="margin-left:auto"><i class="ti ti-plus"></i> Nouveau transfert</button></div>`;
  h += secHdr("ti-inbox", "À valider (réception à confirmer)");
  if (aValider.length) {
    h += aValider.map((t) => `<div class="item ordre"><div class="top"><div>
      <div class="num">${esc(t.numero)}</div>
      <div class="titre">${ep(t.source_type, t.source)} <i class="ti ti-arrow-right"></i> ${ep(t.dest_type, t.dest)}</div>
      <div class="meta">Initié par ${esc(t.initiateur || "")}${t.motif ? " · " + esc(t.motif) : ""}</div></div>
      <div class="montant">${fmtNum(t.montant)} ${t.devise}</div></div>
      <div class="actions"><button class="btn btn-success btn-sm" data-tval="${t.id}"><i class="ti ti-check"></i> Valider la réception</button>
      <button class="btn btn-danger btn-sm" data-trej="${t.id}"><i class="ti ti-x"></i> Rejeter</button></div></div>`).join("");
  } else h += `<div class="muted" style="margin-bottom:18px">Aucun transfert en attente de votre validation.</div>`;
  h += secHdr("ti-history", "Historique des transferts");
  h += `<div class="card"><div class="card-body">${list.length ? `<table><thead><tr><th>Numéro</th><th>De</th><th>Vers</th><th class="right">Montant</th><th>Statut</th></tr></thead><tbody>
    ${list.map((t) => `<tr><td class="num-cell">${esc(t.numero)}</td><td>${esc(t.source)}</td><td>${esc(t.dest)}</td>
      <td class="right">${fmtNum(t.montant)} ${t.devise}</td><td>${pill(t.statut)}</td></tr>`).join("")}
  </tbody></table>` : `<div class="muted">Aucun transfert.</div>`}</div></div>`;
  el.innerHTML = h;
  $("#t-new").onclick = () => transfertModal();
  el.querySelectorAll("[data-tval]").forEach((b) => b.onclick = async () => {
    const t = aValider.find((x) => x.id === b.dataset.tval);
    if (t && t.dest_type === "caisse") { validerTransfertModal(t); return; }   // écart possible à la réception physique
    try { const r = await api(`/transferts/${b.dataset.tval}/valider`, { method: "POST" }); toast(`Transfert validé — encaissement effectif (pièce ${r.ecriture}).`, "ok"); if (r.mouvement_id) printBonCaisse(r.mouvement_id); refreshComptaBadge(); RENDER.transferts(); }
    catch (e) { toast(e.message, "ko"); }
  });
  el.querySelectorAll("[data-trej]").forEach((b) => b.onclick = () => {
    const motif = prompt("Motif du rejet ?"); if (!motif) return;
    api(`/transferts/${b.dataset.trej}/rejeter`, { method: "POST", body: { motif } })
      .then(() => { toast("Transfert rejeté — fonds retournés à la source.", "ko"); RENDER.transferts(); })
      .catch((e) => toast(e.message, "ko"));
  });
};
function validerTransfertModal(t) {
  modal({
    title: `Valider la réception — ${esc(t.numero)}`,
    body: `<div class="banner"><i class="ti ti-cash"></i> Confirmez le montant <b>réellement reçu</b>. Tout écart avec le montant déclaré (${fmtNum(t.montant)} ${t.devise}) sera constaté automatiquement (manquant 658 / excédent 758).</div>
      <p class="muted" style="margin:6px 0">De <b>${esc(t.source)}</b> · déclaré <b>${fmtNum(t.montant)} ${t.devise}</b></p>
      <div class="form-group"><label class="form-label">Montant réellement reçu (${t.devise})</label><input id="tv-recu" class="form-input" type="number" step="any" value="${t.montant}" /></div>
      <p id="tv-ecart" style="font-size:13px;margin-top:6px"></p>`,
    footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-success" id="tv-ok"><i class="ti ti-check"></i> Valider la réception</button>`,
  });
  const upd = () => {
    const r = +$("#tv-recu").value || 0, e = Math.round((r - t.montant) * 100) / 100;
    $("#tv-ecart").innerHTML = e === 0 ? '<span class="muted">Aucun écart.</span>'
      : e > 0 ? `<span style="color:var(--g)">Excédent de ${fmtNum(e)} ${t.devise} → produit 758</span>`
              : `<span style="color:var(--r)">Manquant de ${fmtNum(-e)} ${t.devise} → charge 658</span>`;
  };
  $("#tv-recu").oninput = upd; upd();
  $("#tv-ok").onclick = async () => {
    try {
      const r = await api(`/transferts/${t.id}/valider`, { method: "POST", body: { montant_recu: +$("#tv-recu").value || 0 } });
      closeModal(); toast(`Transfert validé — encaissement effectif (pièce ${r.ecriture}).`, "ok");
      if (r.mouvement_id) printBonCaisse(r.mouvement_id); refreshComptaBadge(); RENDER.transferts();
    } catch (e) { toast(e.message, "ko"); }
  };
}

async function transfertModal(prefill) {
  const [caisses, banks] = await Promise.all([
    api(`/caisses?societe_id=${currentSocieteId}`), api(`/comptes-bancaires?societe_id=${currentSocieteId}`)]);
  const opts = caisses.map((c) => `<option value="caisse:${c.id}">🪙 ${esc(c.libelle)}</option>`).join("") +
    banks.map((b) => `<option value="banque:${b.id}">🏦 ${esc(b.libelle)}</option>`).join("");
  modal({
    title: "Nouveau transfert de fonds",
    body: `<div class="banner"><i class="ti ti-info-circle"></i> Les fonds quittent la source immédiatement ; la destination devra <b>valider la réception</b> pour rendre l'encaissement effectif.</div>
      <div class="form-group"><label class="form-label">Source (d'où partent les fonds)</label><select id="t-src" class="form-select">${opts}</select></div>
      <div class="form-group"><label class="form-label">Destination (où arrivent les fonds)</label><select id="t-dst" class="form-select">${opts}</select></div>
      <div class="form-row"><div class="form-group"><label class="form-label">Devise</label><select id="t-dev" class="form-select"><option>USD</option><option>CDF</option></select></div>
      <div class="form-group"><label class="form-label">Montant</label><input id="t-mt" class="form-input" type="number" step="any" /></div></div>
      <div class="form-group"><label class="form-label">Motif (optionnel)</label><input id="t-motif" class="form-input" /></div>`,
    footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="t-ok"><i class="ti ti-send"></i> Émettre le transfert</button>`,
  });
  if (prefill) {
    if (prefill.sourceId) $("#t-src").value = `caisse:${prefill.sourceId}`;
    if (prefill.destId) $("#t-dst").value = `caisse:${prefill.destId}`;
    if (prefill.motif) $("#t-motif").value = prefill.motif;
    if (prefill.devise) $("#t-dev").value = prefill.devise;
    if (prefill.montant) $("#t-mt").value = prefill.montant;
  }
  $("#t-ok").onclick = async () => {
    const [st, sid] = $("#t-src").value.split(":");
    const [dt, did] = $("#t-dst").value.split(":");
    const montant = parseFloat($("#t-mt").value || 0);
    if (!(montant > 0)) { toast("Montant requis.", "ko"); return; }
    try {
      const r = await api("/transferts", { method: "POST", body: {
        societe_id: currentSocieteId, source_type: st, source_id: sid, dest_type: dt, dest_id: did,
        devise: $("#t-dev").value, montant, motif: $("#t-motif").value || null } });
      closeModal(); toast(`Transfert ${r.numero} émis — en attente de validation à la destination.`, "ok");
      if (r.mouvement_id) printBonCaisse(r.mouvement_id);
      RENDER.transferts();
    } catch (e) { toast(e.message, "ko"); }
  };
}

// ── Comptabilité : socle grand livre ─────────────────────────────────
let balStatut = "", glCompte = "", glStatut = "", pcTab = "comptes", pcClasse = "", pcQuery = "";
const _planCache = {};
async function loadPlan(force) {
  if (force || !_planCache[currentSocieteId])
    _planCache[currentSocieteId] = await api(`/comptabilite/plan-comptable?societe_id=${currentSocieteId}`).catch(() => []);
  return _planCache[currentSocieteId];
}

RENDER.balance = async () => {
  const el = $("#view-balance");
  el.innerHTML = `<div class="muted">Chargement…</div>`;
  let d; try { d = await api(`/comptabilite/balance?societe_id=${currentSocieteId}${balStatut ? `&statut=${balStatut}` : ""}`); }
  catch (e) { el.innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }
  const toggle = `<div class="seg">
    <button data-bs="" class="${balStatut === "" ? "on" : ""}">Toutes</button>
    <button data-bs="valide" class="${balStatut === "valide" ? "on" : ""}">Validées</button></div>`;
  const head = `<div class="section-hdr"><div class="section-title"><i class="ti ti-scale"></i> Balance générale ${d.annee || ""}</div>
    <div style="margin-left:auto;display:flex;gap:10px;align-items:center">${toggle}
      <span class="pill ${d.equilibre ? "st-valide" : "st-rejete"}">${d.equilibre ? "Équilibrée" : "Déséquilibrée"}</span>
      <button class="btn btn-sm btn-primary" id="bal-od"><i class="ti ti-pencil-plus"></i> Saisir une écriture</button></div></div>`;
  if (!d.lignes.length) { el.innerHTML = head + `<div class="empty"><i class="ti ti-scale"></i>Aucun mouvement comptable.</div>`; }
  else el.innerHTML = head + `<div class="card"><div class="card-body"><table><thead><tr><th>Compte</th><th>Intitulé</th>
      <th class="right">Débit</th><th class="right">Crédit</th><th class="right">Solde débiteur</th><th class="right">Solde créditeur</th><th class="right">Solde N-1</th></tr></thead><tbody>
    ${d.lignes.map((l) => `<tr><td class="num-cell">${esc(l.compte)}</td><td>${esc(l.intitule)}</td>
      <td class="right">${l.debit ? fmtNum(l.debit) : "—"}</td><td class="right">${l.credit ? fmtNum(l.credit) : "—"}</td>
      <td class="right">${l.solde_debiteur ? fmtNum(l.solde_debiteur) : "—"}</td><td class="right">${l.solde_crediteur ? fmtNum(l.solde_crediteur) : "—"}</td>
      <td class="right muted">${l.solde_n1 ? fmtNum(l.solde_n1) : "—"}</td></tr>`).join("")}
    <tr style="font-weight:700;border-top:2px solid var(--bdr)"><td colspan="2">TOTAL</td><td class="right">${fmtNum(d.total_debit)}</td><td class="right">${fmtNum(d.total_credit)}</td><td colspan="3"></td></tr>
    </tbody></table></div></div>`;
  el.querySelectorAll("[data-bs]").forEach((b) => b.onclick = () => { balStatut = b.dataset.bs; RENDER.balance(); });
  if ($("#bal-od")) $("#bal-od").onclick = () => saisieODModal(() => { RENDER.balance(); });
};

RENDER["grand-livre"] = async () => {
  const el = $("#view-grand-livre");
  const params = `societe_id=${currentSocieteId}${glCompte ? `&compte=${encodeURIComponent(glCompte)}` : ""}${glStatut ? `&statut=${glStatut}` : ""}`;
  let d; try { d = await api(`/comptabilite/grand-livre?${params}`); }
  catch (e) { el.innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }
  const toggle = `<div class="seg">
    <button data-gs="" class="${glStatut === "" ? "on" : ""}">Toutes</button>
    <button data-gs="valide" class="${glStatut === "valide" ? "on" : ""}">Validées</button></div>`;
  const head = `<div class="section-hdr"><div class="section-title"><i class="ti ti-list-details"></i> Grand livre</div>
    <div style="margin-left:auto;display:flex;gap:10px;align-items:center">
      <input id="gl-compte" class="form-input" style="width:150px" placeholder="Filtrer un compte…" value="${esc(glCompte)}" />
      ${toggle}<button class="btn btn-sm btn-primary" id="gl-od"><i class="ti ti-pencil-plus"></i> Saisir</button></div></div>`;
  const body = !d.length ? `<div class="empty"><i class="ti ti-list-details"></i>Aucun mouvement.</div>`
    : d.map((c) => `<div class="card"><div class="card-hdr">
      <div class="card-hdr-title"><i class="ti ti-list-details"></i> ${esc(c.compte)} — ${esc(c.intitule || "")}</div>
      <span class="pill ${c.solde >= 0 ? "st-valide" : "st-a_justifier"}">Solde ${fmtUSD(c.solde)}</span></div>
      <div class="card-body"><table><thead><tr><th>Date</th><th>Journal</th><th>Pièce</th><th>Libellé</th><th>Tiers</th><th>Let.</th><th class="right">Débit</th><th class="right">Crédit</th><th class="right">Solde</th></tr></thead><tbody>
      ${c.mouvements.map((m) => `<tr><td>${m.date}</td><td class="num-cell">${esc(m.journal || "")}</td><td class="num-cell">${esc(m.piece)}</td>
        <td>${esc(m.libelle || "")} ${m.statut === "en_attente" ? '<span class="tag">en attente</span>' : ""}</td>
        <td>${esc(m.tiers || "—")}</td><td class="num-cell muted">${esc(m.lettrage || "—")}</td>
        <td class="right">${m.debit ? fmtNum(m.debit) : "—"}</td><td class="right">${m.credit ? fmtNum(m.credit) : "—"}</td>
        <td class="right">${fmtNum(m.solde)}</td></tr>`).join("")}
      </tbody></table></div></div>`).join("");
  el.innerHTML = head + body;
  const inp = $("#gl-compte");
  inp.oninput = (e) => {
    const v = e.target.value.trim();
    clearTimeout(window._glT);
    window._glT = setTimeout(() => { glCompte = v; RENDER["grand-livre"](); setTimeout(() => { const i = $("#gl-compte"); if (i) { i.focus(); i.setSelectionRange(i.value.length, i.value.length); } }, 0); }, 250);
  };
  el.querySelectorAll("[data-gs]").forEach((b) => b.onclick = () => { glStatut = b.dataset.gs; RENDER["grand-livre"](); });
  $("#gl-od").onclick = () => saisieODModal(() => { RENDER["grand-livre"](); });
};

// ── Comptabilité : saisie manuelle d'écriture (OD) ───────────────────
RENDER["saisie-od"] = async () => {
  const el = $("#view-saisie-od");
  el.innerHTML = `<div class="card"><div class="card-body" style="text-align:center;padding:34px">
    <i class="ti ti-pencil-plus" style="font-size:34px;color:var(--p)"></i>
    <p class="muted" style="margin:8px 0 16px">Saisie manuelle d'une écriture comptable équilibrée (opérations diverses) en USD.<br/>Chaque écriture doit avoir un total débit égal au total crédit.</p>
    <button class="btn btn-primary" id="od-new"><i class="ti ti-pencil-plus"></i> Nouvelle écriture</button></div></div>`;
  $("#od-new").onclick = () => saisieODModal(() => toast("Écriture enregistrée.", "ok"));
};

async function saisieODModal(onDone) {
  const [journaux, plan, tiers] = await Promise.all([
    api(`/comptabilite/journaux?societe_id=${currentSocieteId}`).catch(() => []),
    loadPlan(), api(`/tiers?societe_id=${currentSocieteId}`).catch(() => []),
  ]);
  const planOpts = plan.map((c) => `<option value="${esc(c.numero)}">${esc(c.numero)} — ${esc(c.intitule)}</option>`).join("");
  const tiersOpts = tiers.map((t) => `<option value="${esc(Catalogue.label(t))}" data-id="${t.id}">`).join("");
  const lineHTML = (i) => `<tr data-line="${i}">
    <td><select class="form-select od-sens"><option value="D">Débit</option><option value="C">Crédit</option></select></td>
    <td><input class="form-input od-compte" list="od-plan" placeholder="ex. 601" style="width:100px" /></td>
    <td><input class="form-input od-lib" placeholder="libellé ligne" /></td>
    <td><input class="form-input od-tiers" list="od-tiers" placeholder="(optionnel)" style="width:130px" /></td>
    <td><input class="form-input od-mt right" type="number" step="any" placeholder="0.00" style="width:110px" /></td>
    <td><button class="btn btn-sm od-del" title="Supprimer"><i class="ti ti-trash"></i></button></td></tr>`;
  modal({
    title: "Saisie d'écriture — opérations diverses",
    wide: true,
    body: `<datalist id="od-plan">${planOpts}</datalist><datalist id="od-tiers">${tiersOpts}</datalist>
      <div class="form-row">
        <div class="form-group"><label class="form-label">Journal</label>
          <select id="od-journal" class="form-select">${journaux.map((j) => `<option value="${esc(j.code)}" ${j.code === "OD" ? "selected" : ""}>${esc(j.code)} — ${esc(j.libelle)}</option>`).join("")}</select></div>
        <div class="form-group"><label class="form-label">Date</label><input id="od-date" class="form-input" type="date" value="${isoLocal(new Date())}" /></div></div>
      <div class="form-group"><label class="form-label">Libellé de l'écriture</label><input id="od-libelle" class="form-input" placeholder="ex. Facture n°… / régularisation" /></div>
      <table class="lignes-table"><thead><tr><th>Sens</th><th>Compte</th><th>Libellé</th><th>Tiers</th><th class="right">Montant USD</th><th></th></tr></thead>
        <tbody id="od-lines">${lineHTML(0)}${lineHTML(1)}</tbody></table>
      <button class="btn btn-sm" id="od-add" style="margin-top:8px"><i class="ti ti-plus"></i> Ajouter une ligne</button>
      <div class="total-bar" style="margin-top:12px"><span class="lbl">Débit <b id="od-td">0</b> · Crédit <b id="od-tc">0</b></span><span class="val" id="od-eq"></span></div>`,
    footer: `<button class="btn" onclick="closeModal()">Annuler</button>
      <button class="btn btn-primary" id="od-ok"><i class="ti ti-check"></i> Enregistrer</button>`,
  });
  let n = 2;
  const recompute = () => {
    let td = 0, tc = 0;
    $("#od-lines").querySelectorAll("tr").forEach((tr) => {
      const s = tr.querySelector(".od-sens").value, m = parseFloat(tr.querySelector(".od-mt").value || 0) || 0;
      if (s === "D") td += m; else tc += m;
    });
    $("#od-td").textContent = fmtNum(td); $("#od-tc").textContent = fmtNum(tc);
    const eq = Math.abs(td - tc) < 0.01 && td > 0;
    const f = $("#od-eq"); f.textContent = eq ? "équilibrée ✓" : `écart ${fmtNum(Math.abs(td - tc))}`;
    f.style.color = eq ? "var(--g)" : "var(--r)";
  };
  const wire = () => {
    $("#od-lines").querySelectorAll("tr").forEach((tr) => {
      tr.querySelector(".od-sens").onchange = recompute;
      tr.querySelector(".od-mt").oninput = recompute;
      tr.querySelector(".od-del").onclick = () => { if ($("#od-lines").children.length > 2) { tr.remove(); recompute(); } };
    });
  };
  wire(); recompute();
  $("#od-add").onclick = () => { $("#od-lines").insertAdjacentHTML("beforeend", lineHTML(n++)); wire(); };
  $("#od-ok").onclick = async () => {
    const lignes = [];
    for (const tr of $("#od-lines").querySelectorAll("tr")) {
      const compte = tr.querySelector(".od-compte").value.trim();
      const montant = parseFloat(tr.querySelector(".od-mt").value || 0) || 0;
      if (!compte || !(montant > 0)) continue;
      const tnom = tr.querySelector(".od-tiers").value.trim();
      const tiers_id = tnom ? (tiers.find((t) => t.nom === tnom) || {}).id || null : null;
      lignes.push({ sens: tr.querySelector(".od-sens").value, compte, montant,
        tiers_id, libelle: tr.querySelector(".od-lib").value.trim() || null });
    }
    if (lignes.length < 2) { toast("Au moins deux lignes valides.", "ko"); return; }
    if (!$("#od-libelle").value.trim()) { toast("Libellé requis.", "ko"); return; }
    try {
      await api(`/comptabilite/ecritures/saisie?societe_id=${currentSocieteId}`, { method: "POST", body: {
        journal_code: $("#od-journal").value, date_ecriture: $("#od-date").value || null,
        libelle: $("#od-libelle").value.trim(), lignes } });
      closeModal(); toast("Écriture enregistrée.", "ok"); if (onDone) onDone();
    } catch (e) { toast(e.message, "ko"); }
  };
}

// ── Comptabilité : plan comptable & journaux ─────────────────────────
RENDER["plan-comptable"] = async () => {
  const el = $("#view-plan-comptable");
  el.innerHTML = `<nav class="tabs" style="margin-bottom:16px">
      <button data-pc="comptes" class="${pcTab === "comptes" ? "active" : ""}">Comptes</button>
      <button data-pc="journaux" class="${pcTab === "journaux" ? "active" : ""}">Journaux</button>
      <button data-pc="config" class="${pcTab === "config" ? "active" : ""}">Comptes de config &amp; TVA</button></nav>
    <div id="pc-body"><div class="muted">Chargement…</div></div>`;
  el.querySelectorAll("[data-pc]").forEach((b) => b.onclick = () => { pcTab = b.dataset.pc; RENDER["plan-comptable"](); });
  if (pcTab === "comptes") return pcComptes();
  if (pcTab === "journaux") return pcJournaux();
  return pcConfigComptes();
};

async function pcConfigComptes() {
  const body = $("#pc-body");
  const [d, rev] = await Promise.all([
    api(`/comptabilite/comptes-config?societe_id=${currentSocieteId}`).catch(() => null),
    api(`/comptabilite/revue-config?societe_id=${currentSocieteId}`).catch(() => ({ revue_achats: true, revue_ventes: false })),
  ]);
  if (!d) { body.innerHTML = `<div class="empty">Configuration indisponible.</div>`; return; }
  d.revue_achats = rev.revue_achats; d.revue_ventes = rev.revue_ventes;
  body.innerHTML = `<div class="banner"><i class="ti ti-info-circle"></i> Ces comptes pilotent les écritures générées automatiquement (achats, ventes, caisse, avances, TVA…). Modifiez-les pour les adapter à votre plan comptable.</div>
    <div class="card"><div class="card-body"><table><thead><tr><th>Rôle</th><th style="width:150px">Compte</th><th>Intitulé actuel</th></tr></thead><tbody>
      ${d.comptes.map((c) => `<tr><td>${esc(c.libelle)}</td>
        <td><input class="form-input cfg-c num-cell" data-cle="${c.cle}" list="cfg-plan" value="${esc(c.valeur)}" style="width:130px" /></td>
        <td class="muted cfg-int" data-for="${c.cle}">${esc(c.intitule || "")}</td></tr>`).join("")}
    </tbody></table></div></div>
    <div class="card" style="margin-top:14px"><div class="card-body" style="display:flex;align-items:center;gap:14px">
      <label class="form-label" style="margin:0">Taux de TVA par défaut</label>
      <input id="cfg-tva" class="form-input" type="number" step="any" value="${d.tva_taux_defaut}" style="width:100px" /> <span class="muted">%</span>
      <span class="muted" style="font-size:12px">Utilisé quand aucun taux n'est précisé sur l'article ou la ligne.</span></div></div>
    <div class="card" style="margin-top:14px"><div class="card-body">
      <b style="font-size:13px"><i class="ti ti-user-check"></i> Revue comptable</b>
      <p class="muted" style="font-size:12px;margin:4px 0 10px">Quand une case est cochée, les pièces correspondantes sont créées « en attente » et le comptable les valide (Comptabilité → Pièces en attente) avant qu'elles ne deviennent définitives.</p>
      <label style="display:flex;align-items:center;gap:8px;margin-bottom:6px"><input type="checkbox" id="rev-achats" ${d.revue_achats ? "checked" : ""} /> Achats (factures fournisseurs, réceptions) passent par une validation</label>
      <label style="display:flex;align-items:center;gap:8px"><input type="checkbox" id="rev-ventes" ${d.revue_ventes ? "checked" : ""} /> Ventes à crédit passent par une validation <span class="muted" style="font-size:12px">(les ventes POS/comptant restent toujours directes)</span></label></div></div>
    <datalist id="cfg-plan"></datalist>
    <div style="margin-top:14px;display:flex;gap:10px"><button class="btn btn-primary" id="cfg-save"><i class="ti ti-device-floppy"></i> Enregistrer la configuration</button></div>`;
  // datalist du plan pour l'autocomplétion
  loadPlan().then((plan) => { $("#cfg-plan").innerHTML = plan.map((c) => `<option value="${esc(c.numero)}">${esc(c.numero)} — ${esc(c.intitule)}</option>`).join(""); });
  body.querySelectorAll(".cfg-c").forEach((inp) => inp.onblur = async () => {
    const plan = await loadPlan();
    const found = plan.find((c) => c.numero === inp.value.trim());
    const cell = body.querySelector(`.cfg-int[data-for="${inp.dataset.cle}"]`);
    if (cell) cell.textContent = found ? found.intitule : "⚠ compte absent du plan";
  });
  $("#cfg-save").onclick = async () => {
    const config = {};
    body.querySelectorAll(".cfg-c").forEach((inp) => { if (inp.value.trim()) config[inp.dataset.cle] = inp.value.trim(); });
    try {
      await api(`/comptabilite/comptes-config?societe_id=${currentSocieteId}`, { method: "POST", body: {
        config, tva_taux_defaut: +$("#cfg-tva").value || 0 } });
      await api(`/comptabilite/revue-config?societe_id=${currentSocieteId}`, { method: "POST", body: {
        revue_achats: $("#rev-achats").checked, revue_ventes: $("#rev-ventes").checked } });
      toast("Configuration enregistrée.", "ok");
    } catch (e) { toast(e.message, "ko"); }
  };
}

async function pcComptes() {
  const body = $("#pc-body");
  const plan = await loadPlan(true);
  const filtered = plan.filter((c) => (!pcClasse || c.classe === pcClasse) &&
    (!pcQuery || c.numero.toLowerCase().includes(pcQuery.toLowerCase()) || c.intitule.toLowerCase().includes(pcQuery.toLowerCase())));
  const classes = ["", "1", "2", "3", "4", "5", "6", "7", "8"];
  body.innerHTML = `<div class="section-hdr" style="margin-bottom:12px">
    <input id="pc-q" class="form-input" style="width:220px" placeholder="Rechercher n° ou intitulé…" value="${esc(pcQuery)}" />
    <select id="pc-classe" class="form-select" style="width:auto">${classes.map((c) => `<option value="${c}" ${c === pcClasse ? "selected" : ""}>${c ? "Classe " + c : "Toutes classes"}</option>`).join("")}</select>
    <span class="muted" style="margin-left:auto">${filtered.length} compte(s)</span>
    <button class="btn btn-sm btn-primary" id="pc-new"><i class="ti ti-plus"></i> Nouveau compte</button></div>
    <div class="card"><div class="card-body"><table><thead><tr><th>Compte</th><th>Intitulé</th><th>Classe</th><th>Auxiliaire</th><th>Actif</th><th></th></tr></thead><tbody>
    ${filtered.map((c) => `<tr${c.actif ? "" : ' style="opacity:.5"'}><td class="num-cell">${esc(c.numero)}</td><td>${esc(c.intitule)}</td>
      <td>${esc(c.classe || "")}</td><td>${c.auxiliaire ? '<i class="ti ti-users" title="grand livre auxiliaire"></i>' : "—"}</td>
      <td>${c.actif ? '<span class="pill st-valide">actif</span>' : '<span class="pill st-rejete">inactif</span>'}</td>
      <td class="right"><button class="btn btn-sm" data-edit="${c.id}" data-num="${esc(c.numero)}" data-int="${esc(c.intitule)}" data-act="${c.actif}"><i class="ti ti-pencil"></i></button></td></tr>`).join("")}
    </tbody></table></div></div>`;
  $("#pc-q").oninput = (e) => { pcQuery = e.target.value; clearTimeout(window._pcT); window._pcT = setTimeout(pcComptes, 200); };
  $("#pc-classe").onchange = (e) => { pcClasse = e.target.value; pcComptes(); };
  $("#pc-new").onclick = () => compteModal(null);
  body.querySelectorAll("[data-edit]").forEach((b) => b.onclick = () => compteModal(
    { id: b.dataset.edit, numero: b.dataset.num, intitule: b.dataset.int, actif: b.dataset.act === "true" }));
}

function compteModal(c) {
  const edit = !!c;
  modal({
    title: edit ? `Compte ${c.numero}` : "Nouveau compte",
    body: `${edit ? "" : `<div class="form-group"><label class="form-label">Numéro de compte</label><input id="cp-num" class="form-input" placeholder="ex. 6056" /></div>`}
      <div class="form-group"><label class="form-label">Intitulé</label><input id="cp-int" class="form-input" value="${edit ? esc(c.intitule) : ""}" /></div>
      ${edit ? "" : `<label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-size:13px"><input type="checkbox" id="cp-aux" style="width:auto" /> Compte auxiliaire (ventilé par tiers)</label>`}
      ${edit ? `<label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-size:13px"><input type="checkbox" id="cp-act" style="width:auto" ${c.actif ? "checked" : ""} /> Compte actif</label>` : ""}`,
    footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="cp-ok"><i class="ti ti-check"></i> ${edit ? "Enregistrer" : "Créer"}</button>`,
  });
  $("#cp-ok").onclick = async () => {
    try {
      if (edit) {
        await api(`/comptabilite/plan-comptable/${c.id}`, { method: "PATCH", body: {
          intitule: $("#cp-int").value.trim(), actif: $("#cp-act").checked } });
      } else {
        if (!$("#cp-num").value.trim()) { toast("Numéro requis.", "ko"); return; }
        await api(`/comptabilite/plan-comptable?societe_id=${currentSocieteId}`, { method: "POST", body: {
          numero: $("#cp-num").value.trim(), intitule: $("#cp-int").value.trim(), auxiliaire: $("#cp-aux").checked } });
      }
      closeModal(); toast("Compte enregistré.", "ok"); loadPlan(true); pcComptes();
    } catch (e) { toast(e.message, "ko"); }
  };
}

async function pcJournaux() {
  const body = $("#pc-body");
  const jx = await api(`/comptabilite/journaux?societe_id=${currentSocieteId}`).catch(() => []);
  body.innerHTML = `<div class="section-hdr" style="margin-bottom:12px"><div class="section-title">Journaux comptables</div>
    <button class="btn btn-sm btn-primary" id="jx-new" style="margin-left:auto"><i class="ti ti-plus"></i> Nouveau journal</button></div>
    <div class="card"><div class="card-body"><table><thead><tr><th>Code</th><th>Libellé</th><th>Type</th></tr></thead><tbody>
    ${jx.map((j) => `<tr><td class="num-cell">${esc(j.code)}</td><td>${esc(j.libelle)}</td><td>${esc(j.type)}</td></tr>`).join("")}
    </tbody></table></div></div>`;
  $("#jx-new").onclick = () => {
    modal({
      title: "Nouveau journal",
      body: `<div class="form-row"><div class="form-group"><label class="form-label">Code</label><input id="jx-code" class="form-input" placeholder="ex. BQ2" style="text-transform:uppercase" /></div>
        <div class="form-group"><label class="form-label">Type</label><select id="jx-type" class="form-select">${["od", "achat", "vente", "banque", "caisse", "ouverture"].map((t) => `<option>${t}</option>`).join("")}</select></div></div>
        <div class="form-group"><label class="form-label">Libellé</label><input id="jx-lib" class="form-input" /></div>`,
      footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="jx-ok">Créer</button>`,
    });
    $("#jx-ok").onclick = async () => {
      try {
        await api(`/comptabilite/journaux?societe_id=${currentSocieteId}`, { method: "POST", body: {
          code: $("#jx-code").value.trim(), libelle: $("#jx-lib").value.trim(), type: $("#jx-type").value } });
        closeModal(); toast("Journal créé.", "ok"); pcJournaux();
      } catch (e) { toast(e.message, "ko"); }
    };
  };
}

// ── Comptabilité : lettrage des comptes de tiers ─────────────────────
let letCompte = "421", letTiers = "", letNonLettres = false;
RENDER.lettrage = async () => {
  const el = $("#view-lettrage");
  el.innerHTML = `<div class="muted">Chargement…</div>`;
  const [plan, tiers] = await Promise.all([loadPlan(), api(`/tiers?societe_id=${currentSocieteId}`).catch(() => [])]);
  const params = `societe_id=${currentSocieteId}&compte=${encodeURIComponent(letCompte)}${letTiers ? `&tiers_id=${letTiers}` : ""}${letNonLettres ? "&non_lettres=true" : ""}`;
  let d; try { d = await api(`/comptabilite/lettrage?${params}`); }
  catch (e) { d = { lignes: [], solde: 0, solde_non_lettre: 0, intitule: "" }; }
  const planDL = `<datalist id="let-plan">${plan.map((c) => `<option value="${esc(c.numero)}">${esc(c.numero)} — ${esc(c.intitule)}</option>`).join("")}</datalist>`;
  const head = `${planDL}<div class="section-hdr">
    <div class="section-title"><i class="ti ti-link"></i> Lettrage — ${esc(letCompte)} ${esc(d.intitule || "")}</div>
    <div style="margin-left:auto;display:flex;gap:10px;align-items:center">
      <input id="let-compte" class="form-input" list="let-plan" style="width:110px" value="${esc(letCompte)}" placeholder="Compte" />
      <select id="let-tiers" class="form-select" style="width:auto"><option value="">Tous les tiers</option>
        ${tiers.map((t) => `<option value="${t.id}" ${t.id === letTiers ? "selected" : ""}>${esc(Catalogue.label(t))}</option>`).join("")}</select>
      <label style="display:flex;align-items:center;gap:6px;font-size:12px;cursor:pointer"><input type="checkbox" id="let-nl" style="width:auto" ${letNonLettres ? "checked" : ""} /> non lettrés</label>
    </div></div>
    <div class="kpi-row" style="margin-bottom:14px">
      <div class="kpi-card" style="--accent:var(--p);--kpi-color:var(--p)"><div class="kpi-label">Solde du compte</div><div class="kpi-val">${fmtNum(d.solde)}</div><div class="kpi-sub">USD</div></div>
      <div class="kpi-card" style="--accent:var(--a);--kpi-color:var(--a)"><div class="kpi-label">Solde non lettré (à justifier / récupérer)</div><div class="kpi-val">${fmtNum(d.solde_non_lettre)}</div><div class="kpi-sub">USD</div></div></div>`;

  const body = !d.lignes.length ? `<div class="empty"><i class="ti ti-link"></i>Aucune ligne sur ce compte.</div>`
    : `<div class="card"><div class="card-body"><table><thead><tr><th style="width:34px"></th><th>Date</th><th>Journal</th><th>Pièce</th><th>Libellé</th><th>Tiers</th><th class="right">Débit</th><th class="right">Crédit</th><th>Let.</th></tr></thead><tbody>
    ${d.lignes.map((l) => `<tr class="${l.lettrage ? "let-done" : ""}">
      <td>${l.lettrage ? "" : `<input type="checkbox" class="let-cb" data-id="${l.id}" data-d="${l.debit}" data-c="${l.credit}" />`}</td>
      <td>${l.date}</td><td class="num-cell">${esc(l.journal || "")}</td><td class="num-cell">${esc(l.piece)}</td>
      <td>${esc(l.libelle || "")} ${l.statut === "en_attente" ? '<span class="tag">en attente</span>' : ""}</td>
      <td>${esc(l.tiers || "—")}</td>
      <td class="right">${l.debit ? fmtNum(l.debit) : "—"}</td><td class="right">${l.credit ? fmtNum(l.credit) : "—"}</td>
      <td>${l.lettrage ? `<span class="pill st-valide let-code" data-code="${esc(l.lettrage)}" title="Cliquer pour délettrer" style="cursor:pointer">${esc(l.lettrage)}</span>` : ""}</td></tr>`).join("")}
    </tbody></table></div></div>
    <div class="let-bar"><span class="muted">Sélection — débit <b id="let-sd">0</b> · crédit <b id="let-sc">0</b> <span id="let-eq"></span></span>
      <button class="btn btn-primary" id="let-go" disabled><i class="ti ti-link"></i> Lettrer la sélection</button></div>`;

  el.innerHTML = head + body;
  const applyCompte = () => { const v = $("#let-compte").value.trim(); if (v && v !== letCompte) { letCompte = v; RENDER.lettrage(); } };
  $("#let-compte").onchange = applyCompte;
  $("#let-tiers").onchange = (e) => { letTiers = e.target.value; RENDER.lettrage(); };
  $("#let-nl").onchange = (e) => { letNonLettres = e.target.checked; RENDER.lettrage(); };
  const recompute = () => {
    let sd = 0, sc = 0, n = 0;
    el.querySelectorAll(".let-cb:checked").forEach((cb) => { sd += parseFloat(cb.dataset.d || 0); sc += parseFloat(cb.dataset.c || 0); n++; });
    if ($("#let-sd")) {
      $("#let-sd").textContent = fmtNum(sd); $("#let-sc").textContent = fmtNum(sc);
      const bal = Math.abs(sd - sc) < 0.01 && n >= 2;
      $("#let-eq").textContent = n ? (bal ? "— équilibré ✓" : `— écart ${fmtNum(Math.abs(sd - sc))}`) : "";
      $("#let-eq").style.color = bal ? "var(--g)" : "var(--r)";
      $("#let-go").disabled = !bal;
    }
  };
  el.querySelectorAll(".let-cb").forEach((cb) => cb.onchange = recompute);
  if ($("#let-go")) $("#let-go").onclick = async () => {
    const ligne_ids = [...el.querySelectorAll(".let-cb:checked")].map((cb) => cb.dataset.id);
    try {
      const r = await api(`/comptabilite/lettrage`, { method: "POST", body: { societe_id: currentSocieteId, ligne_ids } });
      toast(`Lettrage ${r.code} — ${r.lignes} lignes rapprochées.`, "ok"); RENDER.lettrage();
    } catch (e) { toast(e.message, "ko"); }
  };
  el.querySelectorAll(".let-code").forEach((b) => b.onclick = async () => {
    if (!confirm(`Annuler le lettrage ${b.dataset.code} ?`)) return;
    try {
      await api(`/comptabilite/delettrage`, { method: "POST", body: { societe_id: currentSocieteId, compte: letCompte, code: b.dataset.code } });
      toast(`Lettrage ${b.dataset.code} annulé.`, "ok"); RENDER.lettrage();
    } catch (e) { toast(e.message, "ko"); }
  });
};

// ── Comptabilité : rapprochement bancaire ────────────────────────────
let rapCompte = "521";
RENDER.rapprochement = async () => {
  const el = $("#view-rapprochement");
  el.innerHTML = `<div class="muted">Chargement…</div>`;
  const plan = await loadPlan();
  let d, hist;
  try {
    d = await api(`/comptabilite/rapprochement/a-pointer?societe_id=${currentSocieteId}&compte=${encodeURIComponent(rapCompte)}`);
    hist = await api(`/comptabilite/rapprochement?societe_id=${currentSocieteId}&compte=${encodeURIComponent(rapCompte)}`).catch(() => []);
  } catch (e) { el.innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }
  const planDL = `<datalist id="rap-plan">${plan.map((c) => `<option value="${esc(c.numero)}">${esc(c.numero)} — ${esc(c.intitule)}</option>`).join("")}</datalist>`;
  const reste = Math.round((d.solde_comptable - d.solde_rapproche) * 100) / 100;
  const head = `${planDL}<div class="section-hdr">
    <div class="section-title"><i class="ti ti-building-bank"></i> Rapprochement — ${esc(rapCompte)} ${esc(d.intitule || "")}</div>
    <input id="rap-compte" class="form-input" list="rap-plan" style="width:110px;margin-left:auto" value="${esc(rapCompte)}" placeholder="Compte banque" /></div>
    <div class="kpi-row" style="margin-bottom:14px">
      <div class="kpi-card" style="--accent:var(--p);--kpi-color:var(--p)"><div class="kpi-label">Solde comptable (livre)</div><div class="kpi-val">${fmtNum(d.solde_comptable)}</div><div class="kpi-sub">USD</div></div>
      <div class="kpi-card" style="--accent:var(--t);--kpi-color:var(--t)"><div class="kpi-label">Déjà rapproché</div><div class="kpi-val">${fmtNum(d.solde_rapproche)}</div><div class="kpi-sub">USD</div></div>
      <div class="kpi-card" style="--accent:var(--a);--kpi-color:var(--a)"><div class="kpi-label">Reste à pointer</div><div class="kpi-val">${fmtNum(reste)}</div><div class="kpi-sub">USD</div></div></div>
    <div class="card" style="margin-bottom:14px"><div class="card-body" style="display:flex;gap:16px;align-items:flex-end;flex-wrap:wrap">
      <div class="form-group" style="margin:0"><label class="form-label">Date du relevé</label><input id="rap-date" class="form-input" type="date" value="${isoLocal(new Date())}" /></div>
      <div class="form-group" style="margin:0"><label class="form-label">Solde du relevé bancaire (USD)</label><input id="rap-solde" class="form-input" type="number" step="any" placeholder="0.00" style="width:180px" /></div>
      <div style="margin-left:auto;text-align:right"><div class="muted" style="font-size:12px">Solde pointé <b id="rap-pointe">${fmtNum(d.solde_rapproche)}</b> · écart relevé <b id="rap-ecart">—</b></div>
        <button class="btn btn-primary" id="rap-go" style="margin-top:6px"><i class="ti ti-check"></i> Enregistrer le rapprochement</button></div>
    </div></div>`;

  const body = !d.lignes.length ? `<div class="empty"><i class="ti ti-building-bank"></i>Aucune ligne à pointer sur ce compte.</div>`
    : `<div class="card"><div class="card-body"><table><thead><tr><th style="width:34px"></th><th>Date</th><th>Journal</th><th>Pièce</th><th>Libellé</th><th class="right">Débit</th><th class="right">Crédit</th></tr></thead><tbody>
    ${d.lignes.map((l) => `<tr>
      <td><input type="checkbox" class="rap-cb" data-id="${l.id}" data-d="${l.debit}" data-c="${l.credit}" /></td>
      <td>${l.date}</td><td class="num-cell">${esc(l.journal || "")}</td><td class="num-cell">${esc(l.piece)}</td>
      <td>${esc(l.libelle || "")} ${l.statut === "en_attente" ? '<span class="tag">en attente</span>' : ""}</td>
      <td class="right">${l.debit ? fmtNum(l.debit) : "—"}</td><td class="right">${l.credit ? fmtNum(l.credit) : "—"}</td></tr>`).join("")}
    </tbody></table></div></div>`;

  const histHtml = !hist.length ? "" : `<h3 style="margin:22px 0 10px;font-size:14px;color:var(--p)">Historique des rapprochements</h3>
    <div class="card"><div class="card-body"><table><thead><tr><th>Date relevé</th><th class="right">Solde relevé</th><th class="right">Solde comptable</th><th class="right">Pointé</th><th class="right">Écart</th><th></th></tr></thead><tbody>
    ${hist.map((r) => `<tr><td>${r.date_releve}</td><td class="right">${fmtNum(r.solde_releve)}</td><td class="right">${fmtNum(r.solde_comptable)}</td>
      <td class="right">${fmtNum(r.solde_rapproche)}</td><td class="right ${Math.abs(r.ecart) < 0.01 ? "" : "danger"}">${fmtNum(r.ecart)}</td>
      <td class="right"><button class="btn btn-sm rap-annul" data-id="${r.id}" title="Annuler (dépointer)"><i class="ti ti-arrow-back-up"></i></button></td></tr>`).join("")}
    </tbody></table></div></div>`;

  el.innerHTML = head + body + histHtml;
  const applyCompte = () => { const v = $("#rap-compte").value.trim(); if (v && v !== rapCompte) { rapCompte = v; RENDER.rapprochement(); } };
  $("#rap-compte").onchange = applyCompte;
  const recompute = () => {
    let sel = 0, n = 0;
    el.querySelectorAll(".rap-cb:checked").forEach((cb) => { sel += parseFloat(cb.dataset.d || 0) - parseFloat(cb.dataset.c || 0); n++; });
    const pointe = Math.round((d.solde_rapproche + sel) * 100) / 100;
    $("#rap-pointe").textContent = fmtNum(pointe);
    const sr = parseFloat($("#rap-solde").value);
    const ec = isNaN(sr) ? null : Math.round((sr - pointe) * 100) / 100;
    const eEl = $("#rap-ecart");
    eEl.textContent = ec === null ? "—" : fmtNum(ec);
    eEl.style.color = ec === null ? "" : (Math.abs(ec) < 0.01 ? "var(--g)" : "var(--r)");
  };
  el.querySelectorAll(".rap-cb").forEach((cb) => cb.onchange = recompute);
  $("#rap-solde").oninput = recompute;
  $("#rap-go").onclick = async () => {
    const ligne_ids = [...el.querySelectorAll(".rap-cb:checked")].map((cb) => cb.dataset.id);
    const sr = parseFloat($("#rap-solde").value);
    if (isNaN(sr)) { toast("Saisissez le solde du relevé.", "ko"); return; }
    try {
      const r = await api(`/comptabilite/rapprochement`, { method: "POST", body: {
        societe_id: currentSocieteId, compte: rapCompte, date_releve: $("#rap-date").value,
        solde_releve: sr, ligne_ids } });
      toast(`Rapprochement enregistré — écart ${fmtNum(r.ecart)} USD.`, Math.abs(r.ecart) < 0.01 ? "ok" : "info");
      RENDER.rapprochement();
    } catch (e) { toast(e.message, "ko"); }
  };
  el.querySelectorAll(".rap-annul").forEach((b) => b.onclick = async () => {
    if (!confirm("Annuler ce rapprochement (dépointer ses lignes) ?")) return;
    try { await api(`/comptabilite/rapprochement/${b.dataset.id}/annuler`, { method: "POST" }); toast("Rapprochement annulé.", "ok"); RENDER.rapprochement(); }
    catch (e) { toast(e.message, "ko"); }
  });
};

// ── Comptabilité analytique ──────────────────────────────────────────
let anaTab = "ventilation", anaAxe = "", anaNonVent = false;
RENDER.analytique = async () => {
  const el = $("#view-analytique");
  el.innerHTML = `<div class="muted">Chargement…</div>`;
  const axes = await api(`/analytique/axes?societe_id=${currentSocieteId}`).catch(() => []);
  if ((!anaAxe || !axes.find((a) => a.id === anaAxe)) && axes.length) anaAxe = axes[0].id;
  el.innerHTML = `<nav class="tabs" style="margin-bottom:16px">
      <button data-at="ventilation" class="${anaTab === "ventilation" ? "active" : ""}">Ventilation</button>
      <button data-at="rapport" class="${anaTab === "rapport" ? "active" : ""}">Rapport</button>
      <button data-at="config" class="${anaTab === "config" ? "active" : ""}">Axes &amp; sections</button></nav>
    <div id="ana-body"><div class="muted">Chargement…</div></div>`;
  el.querySelectorAll("[data-at]").forEach((b) => b.onclick = () => { anaTab = b.dataset.at; RENDER.analytique(); });
  if (!axes.length && anaTab !== "config") {
    $("#ana-body").innerHTML = `<div class="empty"><i class="ti ti-chart-pie"></i>Aucun axe analytique. Créez-en un dans « Axes & sections ».</div>`;
    return;
  }
  if (anaTab === "ventilation") return anaVentilation(axes);
  if (anaTab === "rapport") return anaRapport(axes);
  return anaConfig(axes);
};

const axeSelector = (axes, id) => `<select id="ana-axe" class="form-select" style="width:auto">
  ${axes.map((a) => `<option value="${a.id}" ${a.id === anaAxe ? "selected" : ""}>${esc(a.code)} — ${esc(a.libelle)}</option>`).join("")}</select>`;

async function anaVentilation(axes) {
  const body = $("#ana-body");
  const axe = axes.find((a) => a.id === anaAxe);
  const lignes = await api(`/analytique/lignes?societe_id=${currentSocieteId}&axe_id=${anaAxe}${anaNonVent ? "&non_ventilees=true" : ""}`).catch(() => []);
  body.innerHTML = `<div class="section-hdr" style="margin-bottom:12px">
      ${axeSelector(axes)}
      <label style="display:flex;align-items:center;gap:6px;font-size:12px;cursor:pointer;margin-left:12px"><input type="checkbox" id="ana-nv" style="width:auto" ${anaNonVent ? "checked" : ""} /> à ventiler seulement</label>
      <span class="muted" style="margin-left:auto">${lignes.length} ligne(s)</span>
      <button class="btn btn-sm" id="ana-vcsv" style="margin-left:10px"><i class="ti ti-file-spreadsheet"></i> Exporter CSV</button></div>
    ${!lignes.length ? `<div class="empty"><i class="ti ti-checks"></i>Rien à ventiler sur cet axe.</div>` :
      `<div class="card"><div class="card-body"><table><thead><tr><th>Date</th><th>Pièce</th><th>Compte</th><th>Libellé</th><th>Type</th><th class="right">Montant</th><th class="right">Ventilé</th><th>Sections</th><th></th></tr></thead><tbody>
      ${lignes.map((l) => `<tr><td>${l.date}</td><td class="num-cell">${esc(l.piece)}</td><td class="num-cell">${esc(l.compte)}</td>
        <td>${esc(l.libelle || "")}</td><td><span class="pill ${l.type === "charge" ? "st-a_justifier" : "st-valide"}">${l.type}</span></td>
        <td class="right">${fmtNum(l.montant)}</td><td class="right ${l.reste > 0.01 ? "danger" : ""}">${fmtNum(l.ventile)}</td>
        <td class="muted" style="font-size:11px">${l.ventilation.map((v) => `${esc(v.section)} ${fmtNum(v.montant)}`).join(", ") || "—"}</td>
        <td class="right"><button class="btn btn-sm ana-vent" data-id="${l.id}"><i class="ti ti-chart-pie"></i> Ventiler</button></td></tr>`).join("")}
      </tbody></table></div></div>`}`;
  $("#ana-axe").onchange = (e) => { anaAxe = e.target.value; anaVentilation(axes); };
  $("#ana-nv").onchange = (e) => { anaNonVent = e.target.checked; anaVentilation(axes); };
  if ($("#ana-vcsv")) $("#ana-vcsv").onclick = () => exporterCSV(
    `ventilation-analytique-${isoLocal(new Date())}.csv`,
    ["Date", "Pièce", "Compte", "Libellé", "Type", "Montant USD", "Ventilé USD", "Sections"],
    lignes.map((l) => [l.date, l.piece, l.compte, l.libelle || "", l.type,
                       l.montant, l.ventile,
                       l.ventilation.map((v) => `${v.section} ${v.montant}`).join(", ")]));
  body.querySelectorAll(".ana-vent").forEach((b) => b.onclick = () => {
    const l = lignes.find((x) => x.id === b.dataset.id);
    ventilerModal(l, axe);
  });
}

function ventilerModal(ligne, axe) {
  const secOpts = axe.sections.filter((s) => s.actif).map((s) => `<option value="${s.id}">${esc(s.code)} — ${esc(s.libelle)}</option>`).join("");
  const existing = ligne.ventilation.length ? ligne.ventilation : [{ section_id: "", montant: ligne.montant }];
  const rowHTML = (v) => `<div class="split-line" style="display:flex;gap:8px;margin-bottom:6px">
    <select class="form-select vt-sec" style="width:220px"><option value="">— section —</option>${secOpts}</select>
    <input class="form-input vt-mt right" type="number" step="any" style="width:120px" value="${v.montant || ""}" />
    <button class="btn btn-sm vt-del"><i class="ti ti-trash"></i></button></div>`;
  modal({
    title: `Ventiler — ${esc(ligne.compte)} · ${fmtUSD(ligne.montant)}`,
    body: `<p class="muted" style="margin-bottom:10px">Axe <b>${esc(axe.libelle)}</b> · répartir le montant de la ligne sur une ou plusieurs sections.</p>
      <div id="vt-lines">${existing.map(rowHTML).join("")}</div>
      <button class="btn btn-sm" id="vt-add" style="margin-top:6px"><i class="ti ti-plus"></i> Ajouter une section</button>
      <div class="total-bar" style="margin-top:12px"><span class="lbl">Réparti <b id="vt-tot">0</b> / ${fmtNum(ligne.montant)}</span><span class="val" id="vt-reste"></span></div>`,
    footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="vt-ok"><i class="ti ti-check"></i> Enregistrer</button>`,
  });
  // pré-sélectionne les sections existantes
  const lineEls = $("#vt-lines").querySelectorAll(".split-line");
  existing.forEach((v, i) => { if (v.section_id) lineEls[i].querySelector(".vt-sec").value = v.section_id; });
  const recompute = () => {
    let t = 0; $("#vt-lines").querySelectorAll(".vt-mt").forEach((x) => t += parseFloat(x.value || 0) || 0);
    t = Math.round(t * 100) / 100;
    $("#vt-tot").textContent = fmtNum(t);
    const r = Math.round((ligne.montant - t) * 100) / 100;
    $("#vt-reste").textContent = Math.abs(r) < 0.01 ? "réparti ✓" : (r < 0 ? `dépasse de ${fmtNum(-r)}` : `reste ${fmtNum(r)}`);
    $("#vt-reste").style.color = r < -0.01 ? "var(--r)" : "var(--g)";
  };
  const wire = () => $("#vt-lines").querySelectorAll(".split-line").forEach((d) => {
    d.querySelector(".vt-mt").oninput = recompute;
    d.querySelector(".vt-del").onclick = () => { if ($("#vt-lines").children.length > 1) { d.remove(); recompute(); } };
  });
  wire(); recompute();
  $("#vt-add").onclick = () => { $("#vt-lines").insertAdjacentHTML("beforeend", rowHTML({ montant: "" })); wire(); };
  $("#vt-ok").onclick = async () => {
    const repartition = [];
    for (const d of $("#vt-lines").querySelectorAll(".split-line")) {
      const section_id = d.querySelector(".vt-sec").value;
      const montant = parseFloat(d.querySelector(".vt-mt").value || 0) || 0;
      if (section_id && montant > 0) repartition.push({ section_id, montant });
    }
    try {
      await api(`/analytique/ventiler`, { method: "POST", body: {
        societe_id: currentSocieteId, ligne_id: ligne.id, axe_id: anaAxe, repartition } });
      closeModal(); toast("Ventilation enregistrée.", "ok"); anaVentilation(await api(`/analytique/axes?societe_id=${currentSocieteId}`));
    } catch (e) { toast(e.message, "ko"); }
  };
}

async function anaRapport(axes) {
  const body = $("#ana-body");
  const d = await api(`/analytique/rapport?societe_id=${currentSocieteId}&axe_id=${anaAxe}`).catch(() => null);
  if (!d) { body.innerHTML = `<div class="empty">Rapport indisponible.</div>`; return; }
  body.innerHTML = `<div class="section-hdr" style="margin-bottom:12px">${axeSelector(axes)}
      <span class="muted" style="margin-left:auto">Résultat analytique par section — ${esc(d.axe)}</span>
      <button class="btn btn-sm" id="ana-csv" style="margin-left:10px"><i class="ti ti-file-spreadsheet"></i> Exporter CSV</button>
      <button class="btn btn-sm btn-primary" id="ana-print"><i class="ti ti-printer"></i> Imprimer</button></div>
    <div class="card"><div class="card-body"><table><thead><tr><th>Section</th><th class="right">Produits</th><th class="right">Charges</th><th class="right">Résultat</th></tr></thead><tbody>
    ${d.lignes.map((l) => `<tr><td>${esc(l.section)}</td><td class="right">${l.produits ? fmtNum(l.produits) : "—"}</td>
      <td class="right">${l.charges ? fmtNum(l.charges) : "—"}</td>
      <td class="right ${l.resultat >= 0 ? "" : "danger"}" style="font-weight:700">${fmtNum(l.resultat)}</td></tr>`).join("")}
    ${(d.non_ventile.charges || d.non_ventile.produits) ? `<tr class="muted"><td>Non ventilé</td><td class="right">${fmtNum(d.non_ventile.produits)}</td><td class="right">${fmtNum(d.non_ventile.charges)}</td><td></td></tr>` : ""}
    <tr style="font-weight:700;border-top:2px solid var(--bdr)"><td>TOTAL</td><td class="right">${fmtNum(d.total_produits)}</td><td class="right">${fmtNum(d.total_charges)}</td><td class="right ${d.resultat >= 0 ? "" : "danger"}">${fmtNum(d.resultat)}</td></tr>
    </tbody></table></div></div>`;
  $("#ana-axe").onchange = (e) => { anaAxe = e.target.value; anaRapport(axes); };
  const lignesExport = [
    ...d.lignes.map((l) => [l.section, l.produits || 0, l.charges || 0, l.resultat]),
    ...((d.non_ventile.charges || d.non_ventile.produits)
      ? [["Non ventilé", d.non_ventile.produits || 0, d.non_ventile.charges || 0, ""]] : []),
    ["TOTAL", d.total_produits, d.total_charges, d.resultat],
  ];
  $("#ana-csv").onclick = () => exporterCSV(
    `rapport-analytique-${(d.axe || "axe").replace(/[^A-Za-z0-9]+/g, "-")}-${isoLocal(new Date())}.csv`,
    ["Section", "Produits USD", "Charges USD", "Résultat USD"], lignesExport);
  $("#ana-print").onclick = () => _docA4({
    titre: "RAPPORT ANALYTIQUE",
    numero: `Axe : ${d.axe}`,
    client: (societes.find((s) => s.id === currentSocieteId) || {}).nom || "",
    clientLabel: "Société",
    meta: [["Date d'édition", new Date().toLocaleDateString("fr-FR")],
           ["Sections", String(d.lignes.length)]],
    colonnes: [{ t: "Section" }, { t: "Produits (USD)", r: 1 }, { t: "Charges (USD)", r: 1 }, { t: "Résultat (USD)", r: 1 }],
    lignes: [
      ...d.lignes.map((l) => [esc(l.section), l.produits ? fmtNum(l.produits) : "—",
                              l.charges ? fmtNum(l.charges) : "—", fmtNum(l.resultat)]),
      ...((d.non_ventile.charges || d.non_ventile.produits)
        ? [["Non ventilé", fmtNum(d.non_ventile.produits), fmtNum(d.non_ventile.charges), "—"]] : []),
    ],
    totaux: [{ l: "Total produits", v: fmtNum(d.total_produits) + " $" },
             { l: "Total charges", v: fmtNum(d.total_charges) + " $" },
             { l: "RÉSULTAT ANALYTIQUE", v: fmtNum(d.resultat) + " USD", grand: 1 }],
    mentions: "Résultat par section analytique — seules les écritures ventilées sur cet axe sont réparties ; le solde apparaît en « Non ventilé ».",
    signatures: ["Le comptable", "Le DFI"],
  });
}

async function anaConfig(axes) {
  const body = $("#ana-body");
  body.innerHTML = `<div class="section-hdr" style="margin-bottom:12px"><div class="section-title">Axes analytiques</div>
      <button class="btn btn-sm btn-primary" id="ax-new" style="margin-left:auto"><i class="ti ti-plus"></i> Nouvel axe</button></div>
    ${axes.map((a) => `<div class="card" style="margin-bottom:12px"><div class="card-hdr">
      <div class="card-hdr-title"><i class="ti ti-chart-pie"></i> ${esc(a.code)} — ${esc(a.libelle)}</div>
      <button class="btn btn-sm ax-sec" data-id="${a.id}"><i class="ti ti-plus"></i> Section</button></div>
      <div class="card-body"><div style="display:flex;flex-wrap:wrap;gap:8px">
        ${a.sections.map((s) => `<span class="tag" style="font-size:12px;padding:5px 12px">${esc(s.code)} · ${esc(s.libelle)}</span>`).join("") || '<span class="muted">Aucune section</span>'}
      </div></div></div>`).join("") || `<div class="empty">Aucun axe. Créez-en un.</div>`}`;
  $("#ax-new").onclick = () => {
    modal({ title: "Nouvel axe analytique",
      body: `<div class="form-row"><div class="form-group"><label class="form-label">Code</label><input id="ax-code" class="form-input" placeholder="ex. CENTRE" style="text-transform:uppercase" /></div>
        <div class="form-group"><label class="form-label">Libellé</label><input id="ax-lib" class="form-input" placeholder="ex. Centre de coût" /></div></div>`,
      footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="ax-ok">Créer</button>` });
    $("#ax-ok").onclick = async () => {
      try {
        await api(`/analytique/axes?societe_id=${currentSocieteId}`, { method: "POST", body: { code: $("#ax-code").value.trim(), libelle: $("#ax-lib").value.trim() } });
        closeModal(); toast("Axe créé.", "ok"); RENDER.analytique();
      } catch (e) { toast(e.message, "ko"); }
    };
  };
  body.querySelectorAll(".ax-sec").forEach((b) => b.onclick = () => {
    modal({ title: "Nouvelle section",
      body: `<div class="form-row"><div class="form-group"><label class="form-label">Code</label><input id="sc-code" class="form-input" style="text-transform:uppercase" /></div>
        <div class="form-group"><label class="form-label">Libellé</label><input id="sc-lib" class="form-input" /></div></div>`,
      footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="sc-ok">Créer</button>` });
    $("#sc-ok").onclick = async () => {
      try {
        await api(`/analytique/axes/${b.dataset.id}/sections`, { method: "POST", body: { code: $("#sc-code").value.trim(), libelle: $("#sc-lib").value.trim() } });
        closeModal(); toast("Section créée.", "ok"); RENDER.analytique();
      } catch (e) { toast(e.message, "ko"); }
    };
  });
}

// ── Comptabilité : cockpit financier du DAF ──────────────────────────
RENDER.cockpit = async () => {
  const el = $("#view-cockpit");
  el.innerHTML = `<div class="muted">Chargement…</div>`;
  let d; try { d = await api(`/comptabilite/cockpit?societe_id=${currentSocieteId}`); }
  catch (e) { el.innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }
  const kpi = (label, val, sub, accent, big) => `<div class="kpi-card" style="--accent:${accent};--kpi-color:${accent}">
    <div class="kpi-label">${label}</div><div class="kpi-val" ${big ? 'style="font-size:26px"' : ""}>${fmtNum(val)}<span style="font-size:13px;color:var(--text3);font-weight:600"> USD</span></div>
    ${sub ? `<div class="kpi-sub">${sub}</div>` : ""}</div>`;
  const resCol = d.resultat >= 0 ? "var(--g)" : "var(--r)";
  el.innerHTML = `
    <h3 style="font-size:13px;text-transform:uppercase;letter-spacing:.06em;color:var(--text3);margin:0 0 12px">Trésorerie & activité</h3>
    <div class="kpi-row">
      ${kpi("Trésorerie totale", d.tresorerie.total, `Caisse ${fmtNum(d.tresorerie.caisse)} · Banque ${fmtNum(d.tresorerie.banque)}`, "var(--t)", true)}
      ${kpi("Chiffre d'affaires", d.chiffre_affaires, "produits d'exploitation (70)", "var(--p)")}
      ${kpi("Charges", d.charges, "total classe 6", "var(--a)")}
      ${kpi("Résultat", d.resultat, d.resultat >= 0 ? "bénéfice" : "perte", resCol, true)}
    </div>
    <h3 style="font-size:13px;text-transform:uppercase;letter-spacing:.06em;color:var(--text3);margin:22px 0 12px">Tiers & obligations</h3>
    <div class="kpi-row">
      ${kpi("Créances clients", d.creances_clients, "à encaisser (411)", "var(--t)")}
      ${kpi("Dettes fournisseurs", d.dettes_fournisseurs, "à payer (401)", "var(--a)")}
      ${kpi("TVA à payer", d.tva_a_payer, "collectée − déductible", "var(--p)")}
      ${kpi("Avances en cours", d.avances_en_cours, "à justifier (421/409)", "var(--a)")}
    </div>
    <div class="banner" style="margin-top:20px"><i class="ti ti-file-invoice"></i> ${d.pieces_en_attente} pièce(s) comptable(s) en attente de validation.
      <button class="btn btn-sm" id="ck-go" style="margin-left:12px"><i class="ti ti-arrow-right"></i> Traiter</button></div>`;
  if ($("#ck-go")) $("#ck-go").onclick = () => go("compta");
};

// ── Comptabilité : états financiers OHADA ─────────────────────────────
let etatsTab = "resultat";
const _n = (v) => (v ? fmtNum(v) : "—");
RENDER.etats = async () => {
  const el = $("#view-etats");
  el.innerHTML = `<div class="section-hdr" style="margin-bottom:14px">
      <nav class="tabs">
        <button data-et="resultat" class="${etatsTab === "resultat" ? "active" : ""}">Compte de résultat</button>
        <button data-et="bilan" class="${etatsTab === "bilan" ? "active" : ""}">Bilan</button>
        <button data-et="tft" class="${etatsTab === "tft" ? "active" : ""}">Flux de trésorerie</button></nav>
      <div style="margin-left:auto;display:flex;gap:8px">
        <button class="btn btn-sm" id="et-print"><i class="ti ti-printer"></i> Imprimer / PDF</button>
        <button class="btn btn-sm" id="et-csv"><i class="ti ti-file-spreadsheet"></i> Exporter</button></div></div>
    <div id="et-body"><div class="muted">Chargement…</div></div>`;
  el.querySelectorAll("[data-et]").forEach((b) => b.onclick = () => { etatsTab = b.dataset.et; RENDER.etats(); });
  $("#et-print").onclick = printEtat;
  $("#et-csv").onclick = exportEtatCsv;
  if (etatsTab === "resultat") return etatsResultat();
  if (etatsTab === "bilan") return etatsBilan();
  return etatsTFT();
};

async function etatsResultat() {
  const body = $("#et-body");
  let d; try { d = await api(`/comptabilite/compte-resultat?societe_id=${currentSocieteId}`); }
  catch (e) { body.innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }
  const rows = d.sections.map((s) => {
    if (s.solde !== undefined) {
      return `<tr class="et-solde ${s.fort ? "fort" : ""}"><td>${esc(s.solde)}</td><td class="right">${_n(s.montant)}</td><td class="right">${_n(s.montant_n1)}</td></tr>`;
    }
    const head = `<tr class="et-sec"><td>${esc(s.titre)}</td><td class="right">${_n(s.total)}</td><td class="right">${_n(s.total_n1)}</td></tr>`;
    const lignes = s.lignes.map((l) => `<tr class="et-l"><td><span class="num-cell">${esc(l.poste)}</span> ${esc(l.intitule)}</td><td class="right">${_n(l.montant)}</td><td class="right">${_n(l.montant_n1)}</td></tr>`).join("");
    return head + lignes;
  }).join("");
  body.innerHTML = `<div class="card"><div class="card-body"><table class="et-table"><thead><tr><th>Compte de résultat</th><th class="right">${d.annee}</th><th class="right">${d.annee - 1}</th></tr></thead><tbody>
    ${rows}
    <tr class="et-net"><td>RÉSULTAT NET DE L'EXERCICE</td><td class="right">${fmtNum(d.resultat_net)}</td><td class="right">${_n(d.resultat_net_n1)}</td></tr>
    </tbody></table></div></div>
    <p class="muted" style="margin-top:10px;font-size:12px">Chiffre d'affaires ${d.annee} : ${fmtUSD(d.chiffre_affaires)} · SYSCOHADA révisé (Système Normal), montants en USD.</p>`;
}

async function etatsBilan() {
  const body = $("#et-body");
  let d; try { d = await api(`/comptabilite/bilan?societe_id=${currentSocieteId}`); }
  catch (e) { body.innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }
  const A = d.actif, P = d.passif, y = d.annee;
  const head = (t) => `<thead><tr><th>${t}</th><th class="right">${y}</th><th class="right">${y - 1}</th></tr></thead>`;
  const sec = (lbl, n, n1) => `<tr class="et-sec"><td>${lbl}</td><td class="right">${_n(n)}</td><td class="right">${_n(n1)}</td></tr>`;
  const sub = (lbl, n, n1) => `<tr class="et-l"><td style="padding-left:26px">${lbl}</td><td class="right">${_n(n)}</td><td class="right">${_n(n1)}</td></tr>`;
  const net = (lbl, n, n1) => `<tr class="et-net"><td>${lbl}</td><td class="right">${fmtNum(n)}</td><td class="right">${_n(n1)}</td></tr>`;
  const immoLignes = A.immobilise.lignes.map((l) => `<tr class="et-l"><td style="padding-left:26px"><span class="num-cell">${esc(l.poste)}</span> ${esc(l.intitule)}</td><td class="right">${_n(l.montant)}</td><td class="right">${_n(l.montant_n1)}</td></tr>`).join("");
  body.innerHTML = `<div class="bilan-grid">
    <div class="card"><div class="card-hdr"><div class="card-hdr-title"><i class="ti ti-arrow-down-left"></i> ACTIF</div></div>
      <div class="card-body"><table class="et-table">${head("Actif")}<tbody>
        ${sec("Actif immobilisé", A.immobilise.total, A.immobilise.total_n1)}${immoLignes}
        ${sec("Actif circulant", A.circulant.total, A.circulant.total_n1)}
        ${sub("Stocks", A.circulant.stocks, A.circulant.stocks_n1)}
        ${sub("Créances", A.circulant.creances, A.circulant.creances_n1)}
        ${sec("Trésorerie – actif", A.tresorerie, A.tresorerie_n1)}
        ${net("TOTAL ACTIF", A.total, A.total_n1)}
      </tbody></table></div></div>
    <div class="card"><div class="card-hdr"><div class="card-hdr-title"><i class="ti ti-arrow-up-right"></i> PASSIF</div></div>
      <div class="card-body"><table class="et-table">${head("Passif")}<tbody>
        ${sec("Capitaux propres", P.capitaux_propres.total, P.capitaux_propres.total_n1)}
        ${sub("Capital & réserves", P.capitaux_propres.capital_reserves, P.capitaux_propres.capital_reserves_n1)}
        ${sub("Résultat de l'exercice", P.capitaux_propres.resultat_net, P.capitaux_propres.resultat_net_n1)}
        ${sec("Dettes financières", P.dettes_financieres, P.dettes_financieres_n1)}
        ${sec("Passif circulant", P.passif_circulant, P.passif_circulant_n1)}
        ${sec("Trésorerie – passif", P.tresorerie, P.tresorerie_n1)}
        ${net("TOTAL PASSIF", P.total, P.total_n1)}
      </tbody></table></div></div>
  </div>
  <div style="margin-top:12px"><span class="pill ${d.equilibre ? "st-valide" : "st-rejete"}">${d.equilibre ? "Bilan équilibré ✓" : `Déséquilibre : ${fmtNum(d.ecart)}`}</span></div>`;
}

async function etatsTFT() {
  const body = $("#et-body");
  let d; try { d = await api(`/comptabilite/tft?societe_id=${currentSocieteId}`); }
  catch (e) { body.innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }
  const flux = d.flux.map((f) => {
    const head = `<tr class="et-sec"><td>${esc(f.titre)}</td><td class="right">${fmtNum(f.total)}</td></tr>`;
    const lignes = f.lignes.map((l) => `<tr class="et-l"><td>${esc(l.libelle)}</td><td class="right">${fmtNum(l.montant)}</td></tr>`).join("");
    return head + lignes;
  }).join("");
  body.innerHTML = `<div class="card"><div class="card-body"><table class="et-table"><thead><tr><th>Tableau des flux de trésorerie ${d.annee}</th><th class="right">Montant</th></tr></thead><tbody>
    <tr class="et-solde"><td>Trésorerie nette à l'ouverture</td><td class="right">${fmtNum(d.tresorerie_ouverture)}</td></tr>
    ${flux}
    <tr class="et-solde fort"><td>Variation de trésorerie de la période</td><td class="right">${fmtNum(d.variation)}</td></tr>
    <tr class="et-net"><td>TRÉSORERIE NETTE À LA CLÔTURE</td><td class="right">${fmtNum(d.tresorerie_cloture)}</td></tr>
    </tbody></table></div></div>
    <div style="margin-top:12px"><span class="pill ${d.controle ? "st-valide" : "st-rejete"}">${d.controle ? "Contrôle OK — ouverture + variation = clôture ✓" : "Contrôle en échec"}</span></div>`;
}

function printEtat() {
  const soc = (societes.find((s) => s.id === currentSocieteId) || {}).nom || "";
  const label = { resultat: "Compte de résultat", bilan: "Bilan", tft: "Tableau des flux de trésorerie" }[etatsTab];
  const content = $("#et-body").innerHTML;
  const w = Editions.fenetre(label);
  w.document.write(`<html><head><meta charset="utf-8"><title>${esc(label)} — ${esc(soc)}</title><style>
    body{font-family:Arial,sans-serif;padding:32px;color:#222}h1{font-size:18px;color:#3C3489;margin:0 0 2px}
    .sub{color:#666;margin-bottom:18px;font-size:13px}
    table{width:100%;border-collapse:collapse;font-size:12.5px;margin-bottom:14px}
    th{text-align:left;padding:6px 10px;font-size:11px;color:#777;border-bottom:1px solid #ccc}th.right,td.right{text-align:right}
    td{padding:6px 10px;border-bottom:1px solid #eee}
    .et-sec td{font-weight:700;color:#3C3489;background:#F1F0FB}
    .et-solde td{font-weight:700;background:#FAFAF7}.et-net td{font-weight:800;color:#fff;background:#3C3489}
    .bilan-grid{display:flex;gap:20px}.bilan-grid>*{flex:1}.card-hdr-title{font-weight:700;color:#3C3489;margin:6px 0}
    .num-cell{color:#3C3489;font-weight:700}.pill{font-size:11px;color:#1a7a4f}.muted{color:#888;font-size:11px}</style></head>
    <body><h1>${esc(soc)}</h1><div class="sub">${esc(label)} — imprimé le ${isoLocal(new Date())}</div>${content}</body></html>`);
  w.document.close(); w.focus(); setTimeout(() => w.print(), 350);
}

function exportEtatCsv() {
  const rows = [];
  $("#et-body").querySelectorAll("table").forEach((t) => {
    t.querySelectorAll("tr").forEach((tr) => {
      rows.push([...tr.children].map((td) => `"${td.textContent.trim().replace(/\s+/g, " ").replace(/"/g, '""')}"`).join(";"));
    });
    rows.push("");
  });
  const blob = new Blob(["﻿" + rows.join("\n")], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = `etats_${etatsTab}.csv`; a.click();
}

// ── Commercial : articles, achats, ventes, stock ─────────────────────
RENDER.articles = async () => {
  const el = $("#view-articles");
  el.innerHTML = `<div class="muted">Chargement…</div>`;
  const arts = await api(`/commercial/articles?societe_id=${currentSocieteId}`).catch(() => []);
  el.innerHTML = `<div class="section-hdr" style="margin-bottom:12px"><div class="section-title"><i class="ti ti-box"></i> Articles</div>
      <button class="btn btn-sm btn-primary" id="art-new" style="margin-left:auto"><i class="ti ti-plus"></i> Nouvel article</button></div>
    ${!arts.length ? `<div class="empty"><i class="ti ti-box"></i>Aucun article. Créez-en un.</div>` :
      `<div class="card"><div class="card-body"><table><thead><tr><th>Code</th><th>Désignation</th><th>Catégorie</th><th class="right">Prix achat</th><th class="right">Prix vente</th><th class="right">TVA</th><th class="right">Stock</th><th></th></tr></thead><tbody>
      ${arts.map((a) => `<tr><td class="num-cell">${esc(a.code)}</td><td>${esc(a.designation)}
          ${(a.nature || "marchandise") !== "marchandise" ? `<span class="tag">${a.nature === "matiere_premiere" ? "matière première" : "consommable"}</span>` : ""}</td><td>${esc(a.categorie || "—")}</td>
        <td class="right">${fmtNum(a.prix_achat)}</td><td class="right">${fmtNum(a.prix_vente)}</td>
        <td class="right">${a.assujetti_tva ? fmtNum(a.taux_tva) + "%" : '<span class="tag">exonéré</span>'}</td>
        <td class="right">${a.gere_stock ? `${fmtNum(a.stock_qte)} ${esc(a.unite)}` : "—"}</td>
        <td class="right"><button class="btn btn-sm" data-edit="${a.id}"><i class="ti ti-pencil"></i></button></td></tr>`).join("")}
      </tbody></table></div></div>`}`;
  $("#art-new").onclick = () => articleModal(null);
  el.querySelectorAll("[data-edit]").forEach((b) => b.onclick = () => articleModal(arts.find((a) => a.id === b.dataset.edit)));
};

async function articleModal(a) {
  const edit = !!a;
  let duplicateConfirmation = null;
  const defTva = edit ? a.taux_tva : await api(`/comptabilite/comptes-config?societe_id=${currentSocieteId}`).then((d) => d.tva_taux_defaut).catch(() => 16);
  const assuj = edit ? a.assujetti_tva : true;
  modal({
    title: edit ? `Article ${a.code}` : "Nouvel article",
    wide: true,
    body: `<div class="form-group"><label class="form-label">Nature de l'article</label>
        <select id="a-nature" class="form-select">
          <option value="marchandise" ${!edit || (a.nature || "marchandise") === "marchandise" ? "selected" : ""}>Marchandise / produit vendu (visible au point de vente)</option>
          <option value="matiere_premiere" ${edit && a.nature === "matiere_premiere" ? "selected" : ""}>Matière première (cuisine — jamais vendue telle quelle)</option>
          <option value="consommable" ${edit && a.nature === "consommable" ? "selected" : ""}>Consommable (entretien, fournitures — usage interne)</option>
        </select></div>
      <div class="form-row-3">
        ${edit ? "" : `<div class="form-group"><label class="form-label">Code</label><input id="a-code" class="form-input" placeholder="ex. CIM50" style="text-transform:uppercase" /></div>`}
        <div class="form-group"><label class="form-label">Unité</label><input id="a-unite" class="form-input" value="${edit ? esc(a.unite) : "unité"}" /></div>
        <div class="form-group"><label class="form-label">Catégorie</label><input id="a-cat" class="form-input" placeholder="ex. Ciment" value="${edit ? esc(a.categorie || "") : ""}" /></div></div>
      <div class="form-row"><div class="form-group"><label class="form-label">Désignation</label><input id="a-des" class="form-input" value="${edit ? esc(a.designation) : ""}" /></div>
        <div class="form-group"><label class="form-label">Code-barres</label><input id="a-cb" class="form-input" placeholder="(POS)" value="${edit ? esc(a.code_barres || "") : ""}" /></div></div>
      <div class="form-row-3">
        <div class="form-group"><label class="form-label">Prix d'achat</label><input id="a-pa" class="form-input" type="number" step="any" value="${edit ? a.prix_achat : 0}" /></div>
        <div class="form-group"><label class="form-label">Prix de vente</label><input id="a-pv" class="form-input" type="number" step="any" value="${edit ? a.prix_vente : 0}" /></div>
        <div class="form-group"><label class="form-label">TVA %</label><input id="a-tva" class="form-input" type="number" step="any" value="${assuj ? defTva : 0}" ${assuj ? "" : "disabled"} /></div></div>
      <label style="display:flex;align-items:center;gap:8px;font-size:13px;cursor:pointer;margin-bottom:12px"><input type="checkbox" id="a-assuj" style="width:auto" ${assuj ? "checked" : ""} /> Assujetti à la TVA</label>
      <div class="form-row"><div class="form-group"><label class="form-label">Commission vendeur %</label><input id="a-com" class="form-input" type="number" step="any" value="${edit ? a.taux_commission : 0}" /></div>
        <div class="form-group"><label class="form-label">Points de fidélité / unité</label><input id="a-fid" class="form-input" type="number" step="any" value="${edit ? a.points_fidelite : 0}" /></div></div>
      ${edit ? "" : `<div class="form-row-3">
        <div class="form-group"><label class="form-label">Compte achat</label><input id="a-ca" class="form-input" value="601" /></div>
        <div class="form-group"><label class="form-label">Compte vente</label><input id="a-cv" class="form-input" value="701" /></div>
        <div class="form-group"><label class="form-label">Compte stock</label><input id="a-cs" class="form-input" value="31" /></div></div>`}
      <label style="display:flex;align-items:center;gap:8px;font-size:13px;cursor:pointer"><input type="checkbox" id="a-stk" style="width:auto" ${edit ? (a.gere_stock ? "checked" : "") : "checked"} /> Article géré en stock</label>
      <div class="muted" style="font-size:11.5px;margin-top:4px"><i class="ti ti-bulb"></i> Décochez pour un <b>plat de cuisine</b> ou un <b>service</b> (nuitée, prestation…) : produits à la demande, ils se vendent sans stock — la cuisine consomme ses matières premières via la fiche technique. Cochez pour les boissons et marchandises revendues telles quelles.</div>`,
    footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="a-ok">${edit ? "Enregistrer" : "Créer"}</button>`,
  });
  $("#a-assuj").onchange = (e) => { const t = $("#a-tva"); t.disabled = !e.target.checked; if (!e.target.checked) t.value = 0; else if (+t.value === 0) t.value = defTva; };
  $("#a-ok").onclick = async () => {
    const fingerprint=JSON.stringify([$("#a-code")?.value,$("#a-des").value,$("#a-cb").value]);
    const common = {
      confirmer_homonyme:duplicateConfirmation===fingerprint,
      nature: $("#a-nature").value, gere_stock: $("#a-stk").checked,
      designation: $("#a-des").value.trim(), prix_achat: +$("#a-pa").value, prix_vente: +$("#a-pv").value,
      assujetti_tva: $("#a-assuj").checked, taux_tva: +$("#a-tva").value,
      categorie: $("#a-cat").value.trim() || null, code_barres: $("#a-cb").value.trim() || null,
      taux_commission: +$("#a-com").value, points_fidelite: +$("#a-fid").value };
    try {
      if (edit) {
        await api(`/commercial/articles/${a.id}`, { method: "PATCH", body: common });
      } else {
        await api(`/commercial/articles?societe_id=${currentSocieteId}`, { method: "POST", body: {
          ...common, code: $("#a-code").value.trim(), unite: $("#a-unite").value.trim() || "unité",
          compte_achat: $("#a-ca").value.trim(), compte_vente: $("#a-cv").value.trim(), compte_stock: $("#a-cs").value.trim(),
          gere_stock: $("#a-stk").checked } });
      }
      closeModal(); toast("Article enregistré.", "ok"); loadPlan(true); RENDER.articles();
    } catch (e) { if(Catalogue.confirmConflict(e,()=>{duplicateConfirmation=fingerprint;$("#a-ok").click();}))return; toast(e.message, "ko"); }
  };
}

RENDER.achats = () => facturesList("achat", "#view-achats");
RENDER.ventes = () => facturesList("vente", "#view-ventes");
async function facturesList(type, sel) {
  const el = $(sel);
  el.innerHTML = `<div class="muted">Chargement…</div>`;
  const facs = await api(`/commercial/factures?societe_id=${currentSocieteId}&type=${type}`).catch(() => []);
  const isA = type === "achat";
  el.innerHTML = `<div class="section-hdr" style="margin-bottom:12px"><div class="section-title"><i class="ti ${isA ? "ti-shopping-cart" : "ti-tag"}"></i> Factures ${isA ? "d'achat" : "de vente"}</div>
      <button class="btn btn-sm btn-primary" id="fac-new" style="margin-left:auto"><i class="ti ti-plus"></i> Nouvelle facture ${isA ? "d'achat" : "de vente"}</button></div>
    ${!facs.length ? `<div class="empty"><i class="ti ti-file-invoice"></i>Aucune facture.</div>` :
      `<div class="card"><div class="card-body"><table><thead><tr><th>N°</th><th>Date</th><th>${isA ? "Fournisseur" : "Client"}</th><th class="right">HT</th><th class="right">TVA</th><th class="right">TTC</th>${isA ? "<th>Statut</th>" : '<th class="right">Marge</th><th>Échéance</th><th>Règlement</th><th></th>'}<th></th></tr></thead><tbody>
      ${facs.map((f) => {
        const [rl, rc] = !isA && f.statut_reglement ? (REGL_ST[f.statut_reglement] || ["", ""]) : ["", ""];
        return `<tr style="cursor:pointer" data-det="${f.id}"><td class="num-cell">${esc(f.numero)}</td><td>${f.date}</td>
        <td>${esc(f.tiers || "")} ${f.intra_groupe ? '<span class="tag">groupe</span>' : ""}</td>
        <td class="right">${fmtNum(f.total_ht)}</td><td class="right">${fmtNum(f.total_tva)}</td><td class="right" style="font-weight:700">${fmtNum(f.total_ttc)}</td>
        ${isA ? `<td><span class="pill ${f.statut === "en_attente" ? "st-partielle" : "st-payee"}" title="${f.statut === "en_attente" ? "À valider/reclasser par le comptable dans Comptabilité › Pièces en attente" : ""}">${f.statut === "en_attente" ? "En attente" : "Validée"}</span></td>` : `<td class="right ${f.marge >= 0 ? "" : "danger"}">${f.marge != null ? fmtNum(f.marge) : "—"}</td>
        <td>${f.echeance || "—"}${f.en_retard ? ' <span class="tag urgent">retard</span>' : ""}</td>
        <td>${rl ? `<span class="pill ${rc}">${rl}</span>${f.statut_reglement !== "payee" ? `<div class="muted" style="font-size:11px">reste ${fmtNum(f.solde_du_usd)} $</div>` : ""}` : "—"}</td>
        <td class="right" style="white-space:nowrap">
          ${f.solde_du_usd > 0 ? `<button class="btn btn-sm btn-primary" data-reg="${f.id}" title="Encaisser"><i class="ti ti-cash"></i></button>` : ""}
          <button class="btn btn-sm" data-prt="${f.id}" title="Imprimer"><i class="ti ti-printer"></i></button></td>`}
        <td class="right"><i class="ti ti-chevron-right muted"></i></td></tr>`;
      }).join("")}
      </tbody></table></div></div>`}`;
  $("#fac-new").onclick = () => factureModal(type);
  el.querySelectorAll("[data-det]").forEach((r) => r.onclick = (e) => {
    if (e.target.closest("[data-reg],[data-prt]")) return;
    factureDetail(facs.find((f) => f.id === r.dataset.det));
  });
  el.querySelectorAll("[data-reg]").forEach((b) => b.onclick = () => reglementModal(facs.find((f) => f.id === b.dataset.reg), () => RENDER.ventes()));
  el.querySelectorAll("[data-prt]").forEach((b) => b.onclick = () => printFactureVente(facs.find((f) => f.id === b.dataset.prt)));
  filtreTable(el);
}

async function factureModal(type) {
  const isA = type === "achat";
  const [articles, tiers, banques, caisses] = await Promise.all([
    api(`/commercial/articles?societe_id=${currentSocieteId}`).catch(() => []),
    api(`/commercial/tiers?societe_id=${currentSocieteId}&type=${isA ? "fournisseur" : "client"}`).catch(() => []),
    isA ? api(`/comptes-bancaires?societe_id=${currentSocieteId}`).catch(() => []) : Promise.resolve([]),
    isA ? api(`/caisses?societe_id=${currentSocieteId}`).catch(() => []) : Promise.resolve([]),
  ]);
  const byId = Object.fromEntries(articles.map((a) => [a.id, a]));
  // vente : seuls les articles de vente ; achat : tout, avec la nature affichée
  const artsFact = isA ? articles
    : articles.filter((a) => (a.nature || "marchandise") === "marchandise");
  const tagNatureF = (a) => a.nature === "matiere_premiere" ? " · matière première"
    : a.nature === "consommable" ? " · consommable" : "";
  let artOpts = `<option value="">(ligne libre)</option>` + artsFact.map((a) => `<option value="${a.id}">${esc(a.code)} — ${esc(a.designation)}${isA ? tagNatureF(a) : ""}</option>`).join("");
  const lineHTML = () => `<tr class="fl-row">
    <td><div style="display:flex;gap:4px"><select class="form-select fl-art" style="min-width:130px">${artOpts}</select><button class="btn btn-sm fl-anew" title="Nouvel article"><i class="ti ti-plus"></i></button></div></td>
    <td><input class="form-input fl-des" placeholder="désignation" /></td>
    <td><input class="form-input fl-qte right" type="number" step="any" value="1" style="width:66px" /></td>
    <td><input class="form-input fl-pu right" type="number" step="any" value="0" style="width:84px" /></td>
    <td><input class="form-input fl-tva right" type="number" step="any" value="16" style="width:54px" /></td>
    <td class="right fl-ht" style="white-space:nowrap">0,00</td>
    ${isA ? '<td class="right fl-ce num-cell" style="white-space:nowrap">—</td>' : ""}
    <td><button class="btn btn-sm fl-del"><i class="ti ti-trash"></i></button></td></tr>`;
  const fournOpts = tiers.map((t) => `<option value="${t.id}">${esc(Catalogue.label(t))}</option>`).join("");
  const banqueOpts = banques.map((b) => `<option value="${b.id}">${esc(b.libelle)}</option>`).join("");
  const caisseOpts = caisses.map((c) => `<option value="${c.id}">${esc(c.libelle)}</option>`).join("");
  const cibleOpts = { credit: `<option value="">— même fournisseur —</option>` + fournOpts,
    banque: banqueOpts || `<option value="">(aucune banque)</option>`,
    caisse: caisseOpts || `<option value="">(aucune caisse)</option>` };
  const fillCible = (tr) => { tr.querySelector(".fr-cible").innerHTML = cibleOpts[tr.querySelector(".fr-mode").value]; };
  const fraisHTML = () => `<tr class="fr-row">
    <td><input class="form-input fr-lib" placeholder="ex. Transport, douane" /></td>
    <td><input class="form-input fr-cpt" value="6085" style="width:60px" /></td>
    <td><input class="form-input fr-mt right" type="number" step="any" value="0" style="width:90px" /></td>
    <td><input class="form-input fr-tva right" type="number" step="any" value="16" style="width:54px" /></td>
    <td><div style="display:flex;gap:4px">
      <select class="form-select fr-mode" style="width:auto;padding:3px 6px"><option value="credit">Crédit fourn.</option><option value="banque">Banque</option><option value="caisse">Caisse (comptant)</option></select>
      <select class="form-select fr-cible" style="width:auto;padding:3px 6px;min-width:120px"></select></div></td>
    <td><button class="btn btn-sm fr-del"><i class="ti ti-trash"></i></button></td></tr>`;
  const tiersOpts = tiers.map((t) => `<option value="${t.id}" data-intra="${t.intra_groupe}">${esc(Catalogue.label(t))}${t.intra_groupe ? " (groupe)" : ""}</option>`).join("");
  const fraisSection = !isA ? "" : `<div style="margin-top:16px">
      <div style="display:flex;align-items:center;gap:14px;margin-bottom:6px">
        <b style="font-size:13px">Frais annexes <span class="muted" style="font-weight:400">(intégrés au coût du stock)</span></b>
        <label style="font-size:12px;color:var(--text2)">Répartition <select id="f-rep" class="form-select" style="width:auto;display:inline-block;padding:4px 8px"><option value="quantite">par quantité</option><option value="valeur">par valeur</option></select></label></div>
      <table class="lignes-table"><thead><tr><th>Frais</th><th>Compte</th><th class="right">Montant HT</th><th class="right">TVA%</th><th>Réglé par</th><th></th></tr></thead><tbody id="f-frais"></tbody></table>
      <button class="btn btn-sm" id="f-fadd" style="margin-top:6px"><i class="ti ti-plus"></i> Ajouter un frais</button></div>`;
  modal({
    title: `Nouvelle facture ${isA ? "d'achat" : "de vente"}`,
    wide: true,
    body: `<div class="form-row">
        <div class="form-group"><label class="form-label">${isA ? "Fournisseur" : "Client"}</label>
          <div style="display:flex;gap:6px"><select id="f-tiers" class="form-select">${tiersOpts}</select>
            <button class="btn btn-sm" id="f-tnew" title="Nouveau ${isA ? "fournisseur" : "client"}"><i class="ti ti-plus"></i></button></div></div>
        <div class="form-group"><label class="form-label">Date</label><input id="f-date" class="form-input" type="date" value="${isoLocal(new Date())}" /></div></div>
      <table class="lignes-table"><thead><tr><th>Article</th><th>Désignation</th><th class="right">Qté</th><th class="right">P.U.</th><th class="right">TVA%</th><th class="right">HT</th>${isA ? '<th class="right">Coût entrée</th>' : ""}<th></th></tr></thead>
        <tbody id="f-lines">${lineHTML()}</tbody></table>
      <button class="btn btn-sm" id="f-add" style="margin-top:8px"><i class="ti ti-plus"></i> Ajouter une ligne</button>
      ${fraisSection}
      <div class="total-bar" style="margin-top:14px;gap:20px"><span class="lbl">HT <b id="f-ht">0</b>${isA ? " · Frais <b id=\"f-frais-tot\">0</b>" : ""} · TVA <b id="f-tva">0</b></span><span class="val">TTC <span id="f-ttc">0</span></span></div>`,
    footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="f-ok"><i class="ti ti-check"></i> Valider la facture</button>`,
  });
  const recompute = () => {
    let ht = 0, tvaA = 0;
    const stockLines = [];
    $("#f-lines").querySelectorAll(".fl-row").forEach((tr) => {
      const artId = tr.querySelector(".fl-art").value;
      const q = +tr.querySelector(".fl-qte").value || 0, pu = +tr.querySelector(".fl-pu").value || 0, tx = +tr.querySelector(".fl-tva").value || 0;
      const lht = Math.round(q * pu * 100) / 100;
      tr.querySelector(".fl-ht").textContent = fmtNum(lht);
      ht += lht; tvaA += Math.round(lht * tx) / 100;
      const a = byId[artId];
      if (isA && a && a.gere_stock) stockLines.push({ tr, ht: lht, qte: q });
      else if (isA && tr.querySelector(".fl-ce")) tr.querySelector(".fl-ce").textContent = "—";
    });
    let frais = 0, tvaF = 0;
    if (isA) $("#f-frais").querySelectorAll(".fr-row").forEach((tr) => {
      const mt = +tr.querySelector(".fr-mt").value || 0, tx = +tr.querySelector(".fr-tva").value || 0;
      frais += mt; tvaF += Math.round(mt * tx) / 100;
    });
    frais = Math.round(frais * 100) / 100;
    if (isA && stockLines.length) {
      const key = $("#f-rep") ? $("#f-rep").value : "quantite";
      const w = stockLines.map((s) => key === "valeur" ? s.ht : s.qte);
      const tw = w.reduce((x, y) => x + y, 0) || 1;
      let cumul = 0;
      stockLines.forEach((s, i) => {
        const part = i < stockLines.length - 1 ? Math.round(frais * w[i] / tw * 100) / 100 : Math.round((frais - cumul) * 100) / 100;
        cumul = Math.round((cumul + part) * 100) / 100;
        if (s.tr.querySelector(".fl-ce")) s.tr.querySelector(".fl-ce").textContent = fmtNum(Math.round((s.ht + part) * 100) / 100);
      });
    }
    const tva = Math.round((tvaA + tvaF) * 100) / 100;
    $("#f-ht").textContent = fmtNum(Math.round(ht * 100) / 100);
    if ($("#f-frais-tot")) $("#f-frais-tot").textContent = fmtNum(frais);
    $("#f-tva").textContent = fmtNum(tva);
    $("#f-ttc").textContent = fmtNum(Math.round((ht + frais + tva) * 100) / 100);
  };
  const wireLines = () => $("#f-lines").querySelectorAll(".fl-row").forEach((tr) => {
    tr.querySelector(".fl-art").onchange = (e) => {
      const a = byId[e.target.value];
      if (a) { tr.querySelector(".fl-des").value = a.designation; tr.querySelector(".fl-pu").value = isA ? a.prix_achat : a.prix_vente; tr.querySelector(".fl-tva").value = a.taux_tva; }
      recompute();
    };
    ["fl-qte", "fl-pu", "fl-tva"].forEach((c) => tr.querySelector("." + c).oninput = recompute);
    tr.querySelector(".fl-del").onclick = () => { if ($("#f-lines").children.length > 1) { tr.remove(); recompute(); } };
    tr.querySelector(".fl-anew").onclick = () => articleQuickModal((a) => {
      byId[a.id] = a;
      if(!artOpts.includes(`value="${a.id}"`))artOpts+=`<option value="${a.id}">${esc(a.code)} — ${esc(a.designation)}</option>`;
      document.querySelectorAll('.fl-art').forEach(sel=>Catalogue.addOption(sel,a,true));
      const sel = tr.querySelector(".fl-art"); sel.value = a.id; sel.dispatchEvent(new Event("change", { bubbles: true }));
    });
  });
  const wireFrais = () => $("#f-frais").querySelectorAll(".fr-row").forEach((tr) => {
    tr.querySelector(".fr-mt").oninput = recompute; tr.querySelector(".fr-tva").oninput = recompute;
    tr.querySelector(".fr-del").onclick = () => { tr.remove(); recompute(); };
    tr.querySelector(".fr-mode").onchange = () => fillCible(tr);
  });
  wireLines(); recompute();
  $("#f-add").onclick = () => { $("#f-lines").insertAdjacentHTML("beforeend", lineHTML()); wireLines(); };
  if (isA) {
    $("#f-fadd").onclick = () => { $("#f-frais").insertAdjacentHTML("beforeend", fraisHTML()); fillCible($("#f-frais").lastElementChild); wireFrais(); recompute(); };
    $("#f-rep").onchange = recompute;
  }
  $("#f-tnew").onclick = () => tiersQuickModal(isA ? "fournisseur" : "client", (t) => {
    const o = document.createElement("option"); o.value = t.id; o.dataset.intra = t.intra_groupe; o.textContent = t.nom + (t.intra_groupe ? " (groupe)" : "");
    $("#f-tiers").appendChild(o); $("#f-tiers").value = t.id;
  });
  $("#f-ok").onclick = async () => {
    const tsel = $("#f-tiers");
    if (!tsel.value) { toast(`Sélectionnez un ${isA ? "fournisseur" : "client"}.`, "ko"); return; }
    const lignes = [];
    for (const tr of $("#f-lines").querySelectorAll(".fl-row")) {
      const qte = +tr.querySelector(".fl-qte").value || 0, pu = +tr.querySelector(".fl-pu").value || 0;
      if (!(qte > 0)) continue;
      lignes.push({ article_id: tr.querySelector(".fl-art").value || null, designation: tr.querySelector(".fl-des").value.trim(),
        qte, prix_unitaire: pu, taux_tva: +tr.querySelector(".fl-tva").value || 0 });
    }
    if (!lignes.length) { toast("Au moins une ligne valide.", "ko"); return; }
    const frais = [];
    if (isA) for (const tr of $("#f-frais").querySelectorAll(".fr-row")) {
      const mt = +tr.querySelector(".fr-mt").value || 0;
      if (!(mt > 0)) continue;
      const mode = tr.querySelector(".fr-mode").value, cible = tr.querySelector(".fr-cible").value;
      const fr = { libelle: tr.querySelector(".fr-lib").value.trim() || "Frais", compte: tr.querySelector(".fr-cpt").value.trim() || "6085", montant_ht: mt, taux_tva: +tr.querySelector(".fr-tva").value || 0, mode };
      if (mode === "credit" && cible) fr.tiers_id = cible;
      else if (mode === "banque") fr.banque_id = cible || null;
      else if (mode === "caisse") fr.caisse_id = cible || null;
      frais.push(fr);
    }
    const intra = tsel.selectedOptions[0].dataset.intra === "true";
    try {
      const f = await api(`/commercial/factures?societe_id=${currentSocieteId}`, { method: "POST", body: {
        type, tiers_id: tsel.value, date_facture: $("#f-date").value || null, intra_groupe: intra, lignes,
        frais, repartition: isA ? $("#f-rep").value : "quantite" } });
      closeModal(); toast(`Facture ${f.numero} validée.`, "ok");
      if (type === "achat") RENDER.achats(); else RENDER.ventes();
    } catch (e) { toast(e.message, "ko"); }
  };
}

function tiersQuickModal(type, onDone) {
  return Catalogue.quick(type, onDone);
}

function articleQuickModal(onDone, settings = {}) {
  return Catalogue.quick('article', onDone, settings);
}

function factureDetail(f) {
  const isA = f.type === "achat", hasFrais = f.frais && f.frais.length;
  const lignes = f.lignes.map((l) => `<tr><td>${esc(l.designation)}${l.article ? ` <span class="tag">${esc(l.article)}</span>` : ""}</td>
    <td class="right">${fmtNum(l.qte)}</td><td class="right">${fmtNum(l.prix_unitaire)}</td><td class="right">${fmtNum(l.taux_tva)}%</td>
    <td class="right">${fmtNum(l.montant_ht)}</td>${isA ? `<td class="right num-cell">${l.cout_entree ? fmtNum(l.cout_entree) : "—"}</td>` : ""}</tr>`).join("");
  const fraisRows = !hasFrais ? "" : `<p class="muted" style="margin:12px 0 4px;font-size:12px">Frais annexes (répartis ${f.repartition === "valeur" ? "par valeur" : "par quantité"})</p>
    <table><thead><tr><th>Frais</th><th>Compte</th><th class="right">HT</th><th class="right">TVA</th><th>Réglé par</th></tr></thead><tbody>
    ${f.frais.map((x) => { const cp = x.mode === "credit" ? `Crédit ${x.contrepartie || "fournisseur"}` : x.mode === "banque" ? `Banque (${esc(x.contrepartie || "")})` : x.mode === "caisse" ? `Caisse comptant` : "—"; return `<tr><td>${esc(x.libelle)}</td><td class="num-cell">${esc(x.compte)}</td><td class="right">${fmtNum(x.montant_ht)}</td><td class="right">${fmtNum(x.montant_tva)}</td><td>${esc(cp)}</td></tr>`; }).join("")}</tbody></table>`;
  modal({
    title: `Facture ${f.numero}`,
    body: `<div style="margin-bottom:10px">${pill(f.statut)} <span class="tag">${isA ? "achat" : "vente"}</span>${f.intra_groupe ? '<span class="tag">intra-groupe</span>' : ""}</div>
      <p><b>${isA ? "Fournisseur" : "Client"} :</b> ${esc(f.tiers || "")}${f.reference ? ` · <span class="muted">facture n° ${esc(f.reference)}</span>` : ""}</p>
      <p class="muted">Date ${f.date}${f.echeance ? " · échéance " + f.echeance : ""}</p>
      <table style="margin-top:8px"><thead><tr><th>Désignation</th><th class="right">Qté</th><th class="right">P.U.</th><th class="right">TVA</th><th class="right">HT</th>${isA ? '<th class="right">Coût entrée</th>' : ""}</tr></thead><tbody>${lignes}</tbody></table>
      ${fraisRows}
      <div class="total-bar" style="margin-top:10px;gap:20px"><span class="lbl">HT ${fmtNum(f.total_ht)}${f.total_frais ? " · Frais " + fmtNum(f.total_frais) : ""} · TVA ${fmtNum(f.total_tva)}</span><span class="val">${fmtUSD(f.total_ttc)}</span></div>
      ${f.marge != null ? `<p class="muted" style="margin-top:8px">Coût des ventes ${fmtUSD(f.cout_ventes)} · <b style="color:${f.marge >= 0 ? "var(--g)" : "var(--r)"}">Marge ${fmtUSD(f.marge)}</b></p>` : ""}`,
    footer: `<button class="btn" onclick="closeModal()">Fermer</button><button class="btn btn-primary" id="f-print"><i class="ti ti-printer"></i> Imprimer</button>`,
  });
  $("#f-print").onclick = () => printFacture(f);
}

function printFacture(f) {
  const soc = (societes.find((s) => s.id === currentSocieteId) || {}).nom || "";
  const lignes = f.lignes.map((l) => `<tr><td>${esc(l.designation)}</td><td class="r">${fmtNum(l.qte)}</td><td class="r">${fmtNum(l.prix_unitaire)}</td><td class="r">${fmtNum(l.taux_tva)}%</td><td class="r">${fmtNum(l.montant_ht)}</td></tr>`).join("");
  const w = Editions.fenetre(`Facture · ${f.numero}`);
  w.document.write(`<html><head><meta charset="utf-8"><title>${esc(f.numero)}</title><style>
    body{font-family:Arial,sans-serif;padding:34px;color:#222}h1{font-size:18px;color:#3C3489;margin:0 0 2px}
    .sub{color:#666;margin-bottom:16px;font-size:13px}table{width:100%;border-collapse:collapse;font-size:12.5px;margin:14px 0}
    th{text-align:left;padding:7px 10px;background:#F1F0FB;color:#3C3489;font-size:11px}td{padding:7px 10px;border-bottom:1px solid #eee}.r{text-align:right}
    .tot{margin-top:16px;text-align:right}.tot .g{font-size:20px;font-weight:800;color:#3C3489}</style></head><body>
    <h1>${esc(soc)}</h1><p>Statut : ${esc(f.statut || "Non renseigné")}</p><div class="sub">Facture ${f.type === "achat" ? "d'achat" : "de vente"} ${esc(f.numero)} · ${f.date}</div>
    <p><b>${f.type === "achat" ? "Fournisseur" : "Client"} :</b> ${esc(f.tiers || "")}</p>
    <table><thead><tr><th>Désignation</th><th class="r">Qté</th><th class="r">P.U.</th><th class="r">TVA</th><th class="r">HT</th></tr></thead><tbody>${lignes}</tbody></table>
    <div class="tot">HT : ${fmtNum(f.total_ht)} USD<br/>TVA : ${fmtNum(f.total_tva)} USD<br/><span class="g">TTC : ${fmtNum(f.total_ttc)} USD</span></div>
    </body></html>`);
  w.document.close(); w.focus(); setTimeout(() => w.print(), 300);
}

RENDER.stock = async () => {
  const el = $("#view-stock");
  el.innerHTML = `<div class="muted">Chargement…</div>`;
  const [d, mvts] = await Promise.all([
    api(`/commercial/stock?societe_id=${currentSocieteId}`).catch(() => ({ lignes: [], valeur_totale: 0 })),
    api(`/commercial/stock/mouvements?societe_id=${currentSocieteId}`).catch(() => []),
  ]);
  el.innerHTML = `<div class="kpi-row" style="margin-bottom:16px">
      <div class="kpi-card" style="--accent:var(--p)"><div class="kpi-label">Valeur totale du stock</div><div class="kpi-val">${fmtNum(d.valeur_totale)}<span style="font-size:13px;color:var(--text3)"> USD</span></div><div class="kpi-sub">au coût moyen pondéré</div></div>
      <div class="kpi-card" style="--accent:var(--t)"><div class="kpi-label">Articles en stock</div><div class="kpi-val">${d.lignes.filter((l) => l.stock_qte > 0).length}</div><div class="kpi-sub">références</div></div></div>
    <div class="card" style="margin-bottom:16px"><div class="card-hdr"><div class="card-hdr-title"><i class="ti ti-packages"></i> État du stock</div></div>
      <div class="card-body"><table><thead><tr><th>Code</th><th>Désignation</th><th class="right">Quantité</th><th class="right">CUMP</th><th class="right">Valeur</th></tr></thead><tbody>
      ${d.lignes.map((l) => `<tr><td class="num-cell">${esc(l.code)}</td><td>${esc(l.designation)}</td><td class="right">${fmtNum(l.stock_qte)} ${esc(l.unite)}</td><td class="right">${fmtNum(l.cump)}</td><td class="right" style="font-weight:700">${fmtNum(l.stock_valeur)}</td></tr>`).join("") || '<tr><td colspan="5" class="muted">Aucun article en stock.</td></tr>'}
      </tbody></table></div></div>
    <div class="card"><div class="card-hdr"><div class="card-hdr-title"><i class="ti ti-arrows-exchange"></i> Derniers mouvements</div></div>
      <div class="card-body"><table><thead><tr><th>Date</th><th>Article</th><th>Sens</th><th>Réf.</th><th class="right">Qté</th><th class="right">Coût unit.</th><th class="right">Valeur</th></tr></thead><tbody>
      ${mvts.slice(0, 40).map((m) => `<tr><td>${m.date}</td><td class="num-cell">${esc(m.article)}</td>
        <td><span class="pill ${m.sens === "entree" ? "st-valide" : "st-a_justifier"}">${m.sens === "entree" ? "entrée" : "sortie"}</span></td>
        <td class="num-cell">${esc(m.reference || "")}</td><td class="right">${fmtNum(m.qte)}</td><td class="right">${fmtNum(m.cout_unitaire)}</td><td class="right">${fmtNum(m.valeur)}</td></tr>`).join("") || '<tr><td colspan="7" class="muted">Aucun mouvement.</td></tr>'}
      </tbody></table></div></div>`;
};

// ── Commercial : commandes (circuit 2) ───────────────────────────────
const CMD_STATUT = { envoyee: "st-a_valider", receptionnee: "st-a_justifier", soldee: "st-valide", annulee: "st-rejete" };
RENDER.commandes = async () => {
  const el = $("#view-commandes");
  el.innerHTML = `<div class="muted">Chargement…</div>`;
  const list = await api(`/commercial/commandes?societe_id=${currentSocieteId}`).catch(() => []);
  el.innerHTML = `<div class="section-hdr" style="margin-bottom:12px"><div class="section-title"><i class="ti ti-clipboard-list"></i> Bons de commande</div>
      <button class="btn btn-sm btn-primary" id="cmd-new" style="margin-left:auto"><i class="ti ti-plus"></i> Nouvelle commande</button></div>
    ${!list.length ? `<div class="empty"><i class="ti ti-clipboard-list"></i>Aucune commande.</div>` :
      `<div class="card"><div class="card-body"><table><thead><tr><th>N°</th><th>Date</th><th>Fournisseur</th><th class="right">Total HT</th><th>Statut</th><th></th></tr></thead><tbody>
      ${list.map((c) => `<tr style="cursor:pointer" data-c="${c.id}"><td class="num-cell">${esc(c.numero)}</td><td>${c.date}</td>
        <td>${esc(c.tiers || "")} ${c.intra_groupe ? '<span class="tag">groupe</span>' : ""}</td>
        <td class="right">${fmtNum(c.total_ht)}</td><td><span class="pill ${CMD_STATUT[c.statut] || ""}">${esc(c.statut)}</span></td>
        <td class="right"><i class="ti ti-chevron-right muted"></i></td></tr>`).join("")}
      </tbody></table></div></div>`}`;
  $("#cmd-new").onclick = () => commandeModal();
  el.querySelectorAll("[data-c]").forEach((r) => r.onclick = () => commandeDetail(list.find((c) => c.id === r.dataset.c)));
  filtreTable(el);
};

async function commandeModal(existing) {
  const isEdit = !!existing;
  const [articles, tiers, full] = await Promise.all([
    api(`/commercial/articles?societe_id=${currentSocieteId}`).catch(() => []),
    api(`/commercial/tiers?societe_id=${currentSocieteId}&type=fournisseur`).catch(() => []),
    isEdit ? api(`/commercial/commandes/${existing.id}`).catch(() => existing) : Promise.resolve(null),
  ]);
  const byId = Object.fromEntries(articles.map((a) => [a.id, a]));
  const tagNatureC = (a) => a.nature === "matiere_premiere" ? " · matière première"
    : a.nature === "consommable" ? " · consommable" : "";
  let artOpts = `<option value="">(ligne libre)</option>` + articles.map((a) => `<option value="${a.id}">${esc(a.code)} — ${esc(a.designation)}${tagNatureC(a)}</option>`).join("");
  const lineHTML = (l) => `<tr class="cl-row">
    <td><div style="display:flex;gap:4px"><select class="form-select cl-art" style="min-width:130px">${artOpts}</select><button class="btn btn-sm cl-anew" title="Nouvel article"><i class="ti ti-plus"></i></button></div></td>
    <td><input class="form-input cl-des" placeholder="désignation" value="${l ? esc(l.designation || "") : ""}" /></td>
    <td><input class="form-input cl-qte right" type="number" step="any" value="${l ? l.qte : 1}" style="width:66px" /></td>
    <td><input class="form-input cl-pu right" type="number" step="any" value="${l ? l.prix_unitaire : 0}" style="width:84px" /></td>
    <td><input class="form-input cl-tva right" type="number" step="any" value="${l ? l.taux_tva : 16}" style="width:54px" /></td>
    <td class="right cl-ht">0,00</td><td><button class="btn btn-sm cl-del"><i class="ti ti-trash"></i></button></td></tr>`;
  const initialRows = (isEdit && full.lignes && full.lignes.length) ? full.lignes.map(lineHTML).join("") : lineHTML();
  modal({
    title: isEdit ? `Modifier la commande ${esc(full.numero)}` : "Nouvelle commande",
    wide: true,
    body: `<div class="form-row"><div class="form-group"><label class="form-label">Fournisseur</label>
        <div style="display:flex;gap:6px"><select id="cmd-tiers" class="form-select">${tiers.map((t) => `<option value="${t.id}" data-intra="${t.intra_groupe}">${esc(Catalogue.label(t))}${t.intra_groupe ? " (groupe)" : ""}</option>`).join("")}</select>
          <button class="btn btn-sm" id="cmd-tnew" title="Nouveau fournisseur"><i class="ti ti-plus"></i></button></div></div>
      <div class="form-group"><label class="form-label">Date</label><input id="cmd-date" class="form-input" type="date" value="${isEdit ? full.date : isoLocal(new Date())}" /></div></div>
      <div class="form-row"><div class="form-group"><label class="form-label">Livraison prévue</label><input id="cmd-liv" class="form-input" type="date" value="${isEdit && full.date_livraison_prevue ? full.date_livraison_prevue : ""}" /></div>
        <div class="form-group"><label class="form-label">Référence fournisseur</label><input id="cmd-ref" class="form-input" placeholder="(devis, n° offre…)" value="${isEdit ? esc(full.reference_fournisseur || "") : ""}" /></div></div>
      <div class="form-row">
        <div class="form-group"><label class="form-label">Destination (lieu de livraison)</label><input id="cmd-dest" class="form-input" placeholder="ex. Dépôt KAKO Kolwezi" value="${isEdit ? esc(full.destination || "") : ""}" /></div>
        <div class="form-group"><label class="form-label">Transporteur (société du groupe)</label>
          <select id="cmd-transp" class="form-select"><option value="">— aucun / transporteur externe —</option>
            ${societes.filter((s) => s.id !== currentSocieteId).map((s) => `<option value="${s.id}">${esc(s.nom)}</option>`).join("")}</select>
          <div class="muted" style="font-size:11.5px;margin-top:4px">Si choisi, une demande de course apparaîtra chez lui, prenable en charge dès confirmation du fournisseur.</div></div></div>
      <table class="lignes-table"><thead><tr><th>Article</th><th>Désignation</th><th class="right">Qté</th><th class="right">P.U.</th><th class="right">TVA%</th><th class="right">HT</th><th></th></tr></thead><tbody id="cmd-lines">${initialRows}</tbody></table>
      <button class="btn btn-sm" id="cmd-add" style="margin-top:8px"><i class="ti ti-plus"></i> Ajouter une ligne</button>
      <div class="total-bar" style="margin-top:12px"><span class="lbl">Total HT</span><span class="val" id="cmd-total">0,00</span></div>`,
    footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="cmd-ok"><i class="ti ti-check"></i> ${isEdit ? "Enregistrer les modifications" : "Créer la commande"}</button>`,
  });
  if (isEdit) {
    $("#cmd-tiers").value = full.tiers_id;
    const rows = $("#cmd-lines").querySelectorAll(".cl-row");
    (full.lignes || []).forEach((l, i) => { if (l.article_id && rows[i]) rows[i].querySelector(".cl-art").value = l.article_id; });
  }
  const recompute = () => {
    let ht = 0;
    $("#cmd-lines").querySelectorAll(".cl-row").forEach((tr) => {
      const lht = Math.round((+tr.querySelector(".cl-qte").value || 0) * (+tr.querySelector(".cl-pu").value || 0) * 100) / 100;
      tr.querySelector(".cl-ht").textContent = fmtNum(lht); ht += lht;
    });
    $("#cmd-total").textContent = fmtNum(Math.round(ht * 100) / 100);
  };
  const wire = () => $("#cmd-lines").querySelectorAll(".cl-row").forEach((tr) => {
    tr.querySelector(".cl-art").onchange = (e) => { const a = byId[e.target.value]; if (a) { tr.querySelector(".cl-des").value = a.designation; tr.querySelector(".cl-pu").value = a.prix_achat; tr.querySelector(".cl-tva").value = a.taux_tva; } recompute(); };
    ["cl-qte", "cl-pu"].forEach((c) => tr.querySelector("." + c).oninput = recompute);
    tr.querySelector(".cl-del").onclick = () => { if ($("#cmd-lines").children.length > 1) { tr.remove(); recompute(); } };
    tr.querySelector(".cl-anew").onclick = () => articleQuickModal((a) => {
      byId[a.id] = a;
      if(!artOpts.includes(`value="${a.id}"`))artOpts+=`<option value="${a.id}">${esc(a.code)} — ${esc(a.designation)}</option>`;
      document.querySelectorAll('.cl-art').forEach(sel=>Catalogue.addOption(sel,a,true));
      const sel = tr.querySelector(".cl-art"); sel.value = a.id; sel.dispatchEvent(new Event("change", { bubbles: true }));
    });
  });
  wire(); recompute();
  $("#cmd-add").onclick = () => { $("#cmd-lines").insertAdjacentHTML("beforeend", lineHTML()); wire(); };
  $("#cmd-tnew").onclick = () => tiersQuickModal("fournisseur", (t) => { const o = document.createElement("option"); o.value = t.id; o.dataset.intra = t.intra_groupe; o.textContent = t.nom; $("#cmd-tiers").appendChild(o); $("#cmd-tiers").value = t.id; });
  $("#cmd-ok").onclick = async () => {
    const tsel = $("#cmd-tiers");
    if (!tsel.value) { toast("Sélectionnez un fournisseur.", "ko"); return; }
    const lignes = [];
    for (const tr of $("#cmd-lines").querySelectorAll(".cl-row")) {
      const qte = +tr.querySelector(".cl-qte").value || 0, pu = +tr.querySelector(".cl-pu").value || 0;
      if (!(qte > 0)) continue;
      lignes.push({ article_id: tr.querySelector(".cl-art").value || null, designation: tr.querySelector(".cl-des").value.trim(), qte, prix_unitaire: pu, taux_tva: +tr.querySelector(".cl-tva").value || 0 });
    }
    if (!lignes.length) { toast("Au moins une ligne.", "ko"); return; }
    const body = { tiers_id: tsel.value, date_commande: $("#cmd-date").value || null, date_livraison_prevue: $("#cmd-liv").value || null,
      reference_fournisseur: $("#cmd-ref").value.trim() || null,
      destination: $("#cmd-dest").value.trim() || null,
      transporteur_societe_id: $("#cmd-transp").value || null,
      intra_groupe: tsel.selectedOptions[0].dataset.intra === "true", lignes };
    try {
      const c = isEdit
        ? await api(`/commercial/commandes/${full.id}`, { method: "PUT", body })
        : await api(`/commercial/commandes?societe_id=${currentSocieteId}`, { method: "POST", body });
      closeModal();
      toast(isEdit ? `Commande ${c.numero} modifiée.`
        : `Commande ${c.numero} créée${c.intersociete ? ` — visible chez le fournisseur (${esc(c.intersociete.devis_numero)})${c.intersociete.course_numero ? " + demande de course " + esc(c.intersociete.course_numero) : ""}` : ""}.`, "ok");
      RENDER.commandes();
    } catch (e) { toast(e.message, "ko"); }
  };
}

async function commandeDetail(c) {
  const d = await api(`/commercial/commandes/${c.id}`).catch(() => c);
  const lignes = d.lignes.map((l) => `<tr><td>${esc(l.designation)}${l.article ? ` <span class="tag">${esc(l.article)}</span>` : ""}</td>
    <td class="right">${fmtNum(l.qte)}</td><td class="right">${fmtNum(l.qte_recue)}</td>
    <td class="right ${l.reste > 0 ? "danger" : ""}">${fmtNum(l.reste)}</td><td class="right">${fmtNum(l.prix_unitaire)}</td></tr>`).join("");
  const peutRecevoir = ["envoyee", "receptionnee"].includes(d.statut) && d.lignes.some((l) => l.reste > 0) && !d.intersociete;
  const INTER_ETATS = { en_attente: ["En attente de prise en charge par le fournisseur", "st-due"],
    prise_en_charge: ["Confirmée par le fournisseur — en exécution", "st-confirme"],
    facturee: ["Livrée & facturée", "st-payee"], annulee: ["Annulée par le fournisseur", "st-annule"] };
  const interHtml = d.intersociete ? (() => {
    const [il, ic] = INTER_ETATS[d.intersociete.etat] || [d.intersociete.etat, ""];
    const rc = d.intersociete.reception || { lignes: [], totaux: {}, a_receptionner: false };
    const t = rc.totaux || {};
    const recTable = t.livre > 0 ? `
      <table style="margin-top:8px"><thead><tr><th>Article</th><th class="right">Chargé</th>
        <th class="right">Bon état</th><th class="right">Mauvais état</th><th class="right">Manquant</th><th class="right">À recevoir</th></tr></thead><tbody>
      ${rc.lignes.filter((l) => l.livre > 0 || l.bon + l.mauvais + l.manquant > 0).map((l) => `<tr>
        <td>${esc(l.designation)}</td><td class="right">${fmtNum(l.livre)}</td>
        <td class="right" style="color:var(--g)">${fmtNum(l.bon)}</td>
        <td class="right" style="color:var(--a)">${fmtNum(l.mauvais)}</td>
        <td class="right" style="color:var(--r)">${fmtNum(l.manquant)}</td>
        <td class="right"><b>${fmtNum(l.a_recevoir)}</b></td></tr>`).join("")}</tbody></table>
      ${rc.valeur_manquants_usd ? `<div class="muted" style="font-size:12px;margin-top:6px"><i class="ti ti-alert-triangle" style="color:var(--r)"></i>
        Manquants : <b>${fmtNum(rc.valeur_manquants_usd)} $</b> au prix d'achat — imputés au transporteur (règle du groupe).</div>` : ""}` : "";
    return `
    <div class="card" style="margin:10px 0"><div class="card-body">
      <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
        <i class="ti ti-affiliate" style="color:var(--p)"></i><b style="font-size:13px">Commande intersociété</b>
        <span class="pill ${ic}">${il}</span>
        ${rc.a_receptionner ? `<button class="btn btn-sm btn-primary" id="cmd-recinter" style="margin-left:auto"><i class="ti ti-package-import"></i> Réceptionner la marchandise</button>` : ""}</div>
      ${bandeauEtapesPO(d.intersociete.etapes)}
      <div class="muted" style="font-size:12.5px;margin-top:6px">
        Chez le fournisseur : commande client <b>${esc(d.intersociete.devis_numero || "—")}</b> (${esc(d.intersociete.devis_statut || "")})
        ${d.destination ? ` · livraison : ${esc(d.destination)}` : ""}
        ${d.intersociete.transporteur ? `<br/>Transporteur : <b>${esc(d.intersociete.transporteur)}</b> — course ${esc(d.intersociete.course_numero || "—")} <span class="pill ${(COURSE_ST[d.intersociete.course_statut] || ["", ""])[1]}">${esc((COURSE_ST[d.intersociete.course_statut] || [d.intersociete.course_statut || ""])[0])}</span>` : ""}
        <br/>À la réception, constatez le bon état / mauvais état / manquant : le stock entre pour le reçu,
        et le fournisseur comme le transporteur ne peuvent facturer qu'après votre réception.</div>
      ${recTable}</div></div>`; })() : "";
  const ctl = d.controle || {};
  const badge = (v) => Math.abs(v || 0) < 0.01 ? "st-valide" : "st-a_justifier";
  const troisVoies = d.controle ? `<div class="triple-match">
      <div><span class="tm-lbl">Commandé</span><span class="tm-val">${fmtNum(ctl.commande_ht)}</span></div>
      <div><span class="tm-lbl">Reçu</span><span class="tm-val">${fmtNum(ctl.recu_ht)}</span><span class="pill ${badge(ctl.ecart_recu)}">${ctl.ecart_recu >= 0 ? "" : ""}${fmtNum(ctl.ecart_recu)}</span></div>
      <div><span class="tm-lbl">Facturé</span><span class="tm-val">${fmtNum(ctl.facture_ht)}</span><span class="pill ${badge(ctl.ecart_facture)}">${fmtNum(ctl.ecart_facture)}</span></div>
    </div>` : "";
  const recsHtml = (d.receptions && d.receptions.length) ? `<p class="muted" style="margin:12px 0 4px;font-size:12px">Réceptions</p>
    <table><thead><tr><th>N°</th><th>Date</th><th class="right">Montant HT</th><th>Statut</th><th>Facture</th></tr></thead><tbody>
    ${d.receptions.map((r) => `<tr><td class="num-cell">${esc(r.numero)}</td><td>${r.date}</td><td class="right">${fmtNum(r.montant_ht)}</td>
      <td><span class="pill ${r.statut === "facturee" ? "st-valide" : "st-a_justifier"}">${r.statut}</span></td><td class="num-cell">${esc(r.facture || "—")}</td></tr>`).join("")}</tbody></table>` : "";
  modal({
    title: `Commande ${d.numero}`,
    wide: true,
    body: `<div style="margin-bottom:8px"><span class="pill ${CMD_STATUT[d.statut] || ""}">${esc(d.statut)}</span>${d.intra_groupe ? ' <span class="tag">intra-groupe</span>' : ""}</div>
      <p><b>Fournisseur :</b> ${esc(d.tiers || "")}${d.reference_fournisseur ? ` · <span class="muted">réf. ${esc(d.reference_fournisseur)}</span>` : ""}</p>
      <p class="muted">Commande du ${d.date}${d.date_livraison_prevue ? ` · livraison prévue le ${d.date_livraison_prevue}` : ""}</p>
      ${interHtml}
      ${troisVoies}
      <table style="margin-top:10px"><thead><tr><th>Désignation</th><th class="right">Commandé</th><th class="right">Reçu</th><th class="right">Reste</th><th class="right">P.U.</th></tr></thead><tbody>${lignes}</tbody></table>
      <div class="total-bar" style="margin-top:8px"><span class="lbl">Total HT</span><span class="val">${fmtUSD(d.total_ht)}</span></div>
      ${recsHtml}`,
    footer: `<button class="btn" onclick="closeModal()">Fermer</button>
      ${d.modifiable ? `<button class="btn" id="cmd-annuler"><i class="ti ti-x"></i> Annuler la commande</button>
        <button class="btn" id="cmd-edit"><i class="ti ti-edit"></i> Modifier</button>` : ""}
      <button class="btn" id="cmd-pj"><i class="ti ti-paperclip"></i> Pièces jointes</button>
      <button class="btn" id="cmd-print"><i class="ti ti-printer"></i> Imprimer</button>
      ${peutRecevoir ? `<button class="btn btn-primary" id="cmd-recept"><i class="ti ti-truck-delivery"></i> Réceptionner</button>` : ""}`,
  });
  $("#cmd-pj").onclick = () => piecesModal("commande", d.id, `Pièces jointes — ${d.numero}`);
  $("#cmd-print").onclick = () => printCommande(d);
  if ($("#cmd-recinter")) $("#cmd-recinter").onclick = () => receptionPOModal(d);
  if (peutRecevoir) $("#cmd-recept").onclick = () => { closeModal(); receptionModal(d); };
  if (d.modifiable) {
    $("#cmd-edit").onclick = () => { closeModal(); commandeModal(d); };
    $("#cmd-annuler").onclick = async () => {
      if (!confirm(`Annuler la commande ${d.numero} ? Cette action est définitive.`)) return;
      try { await api(`/commercial/commandes/${d.id}/annuler`, { method: "POST" }); closeModal(); toast(`Commande ${d.numero} annulée.`, "ok"); RENDER.commandes(); }
      catch (e) { toast(e.message, "ko"); }
    };
  }
}

function printCommande(d) {
  const soc = (societes.find((s) => s.id === currentSocieteId) || {}).nom || "";
  const lignes = d.lignes.map((l) => `<tr><td>${esc(l.designation)}</td><td class="r">${fmtNum(l.qte)}</td><td class="r">${fmtNum(l.prix_unitaire)}</td><td class="r">${fmtNum(Math.round(l.qte * l.prix_unitaire * 100) / 100)}</td></tr>`).join("");
  const w = Editions.fenetre(`Bon de commande · ${d.numero}`);
  w.document.write(`<html><head><meta charset="utf-8"><title>${esc(d.numero)}</title><style>
    body{font-family:Arial,sans-serif;padding:34px;color:#222}h1{font-size:18px;color:#3C3489;margin:0 0 2px}
    .sub{color:#666;margin-bottom:16px;font-size:13px}table{width:100%;border-collapse:collapse;font-size:12.5px;margin:14px 0}
    th{text-align:left;padding:7px 10px;background:#F1F0FB;color:#3C3489;font-size:11px}td{padding:7px 10px;border-bottom:1px solid #eee}.r{text-align:right}
    .tot{text-align:right;font-size:16px;font-weight:800;color:#3C3489;margin-top:12px}.sign{margin-top:60px;display:flex;justify-content:space-between}.sign div{border-top:1px solid #999;width:40%;text-align:center;padding-top:6px;font-size:12px;color:#666}</style></head><body>
    <h1>${esc(soc)}</h1><div class="sub">BON DE COMMANDE ${esc(d.numero)} · ${d.date}${d.date_livraison_prevue ? ` · livraison prévue ${d.date_livraison_prevue}` : ""}</div>
    <p><b>Fournisseur :</b> ${esc(d.tiers || "")}${d.reference_fournisseur ? ` — réf. ${esc(d.reference_fournisseur)}` : ""}</p>
    <table><thead><tr><th>Désignation</th><th class="r">Qté</th><th class="r">P.U.</th><th class="r">Montant HT</th></tr></thead><tbody>${lignes}</tbody></table>
    <div class="tot">Total HT : ${fmtNum(d.total_ht)} USD</div>
    <div class="sign"><div>Le demandeur</div><div>Approbation</div></div></body></html>`);
  w.document.close(); w.focus(); setTimeout(() => w.print(), 300);
}

async function receptionModal(c) {
  const restes = c.lignes.filter((l) => l.reste > 0);
  const [fourns, banques, caisses] = await Promise.all([
    api(`/commercial/tiers?societe_id=${currentSocieteId}&type=fournisseur`).catch(() => []),
    api(`/comptes-bancaires?societe_id=${currentSocieteId}`).catch(() => []),
    api(`/caisses?societe_id=${currentSocieteId}`).catch(() => []),
  ]);
  const fournOpts = fourns.map((t) => `<option value="${t.id}">${esc(Catalogue.label(t))}</option>`).join("");
  const banqueOpts = banques.map((b) => `<option value="${b.id}">${esc(b.libelle)}</option>`).join("");
  const caisseOpts = caisses.map((x) => `<option value="${x.id}">${esc(x.libelle)}</option>`).join("");
  const cibleOpts = { credit: `<option value="">— même fournisseur —</option>` + fournOpts,
    banque: banqueOpts || `<option value="">(aucune banque)</option>`,
    caisse: caisseOpts || `<option value="">(aucune caisse)</option>` };
  const fillCible = (tr) => { tr.querySelector(".rf-cible").innerHTML = cibleOpts[tr.querySelector(".rf-mode").value]; };
  const fHTML = () => `<tr class="rf-row"><td><input class="form-input rf-lib" placeholder="ex. Transport" /></td><td><input class="form-input rf-cpt" value="6085" style="width:60px" /></td>
    <td><input class="form-input rf-mt right" type="number" step="any" value="0" style="width:90px" /></td><td><input class="form-input rf-tva right" type="number" step="any" value="16" style="width:54px" /></td>
    <td><div style="display:flex;gap:4px">
      <select class="form-select rf-mode" style="width:auto;padding:3px 6px"><option value="credit">Crédit fourn.</option><option value="banque">Banque</option><option value="caisse">Caisse (comptant)</option></select>
      <select class="form-select rf-cible" style="width:auto;padding:3px 6px;min-width:120px"></select></div></td>
    <td><button class="btn btn-sm rf-del"><i class="ti ti-trash"></i></button></td></tr>`;
  modal({
    title: `Réceptionner — ${c.numero}`,
    wide: true,
    body: `<div class="banner"><i class="ti ti-truck-delivery"></i> Saisissez les quantités reçues. Chaque frais accessoire indique sa <b>contrepartie réelle</b> (dette d'un fournisseur, banque ou caisse) — il est intégré au coût du stock.</div>
      <table class="lignes-table"><thead><tr><th>Article</th><th class="right">Restant</th><th class="right">Reçu</th><th class="right">P.U.</th><th class="right">Valeur</th></tr></thead><tbody>
        ${restes.map((l) => `<tr class="rl-row" data-lc="${l.id}" data-pu="${l.prix_unitaire}"><td>${esc(l.designation)}</td><td class="right">${fmtNum(l.reste)}</td>
          <td><input class="form-input rl-qte right" type="number" step="any" value="${l.reste}" max="${l.reste}" style="width:80px" /></td>
          <td class="right">${fmtNum(l.prix_unitaire)}</td><td class="right rl-val">${fmtNum(l.reste * l.prix_unitaire)}</td></tr>`).join("")}
      </tbody></table>
      <div style="display:flex;align-items:center;gap:14px;margin:14px 0 4px"><b style="font-size:13px">Frais accessoires</b>
        <label style="font-size:12px;color:var(--text2)">Répartition <select id="r-rep" class="form-select" style="width:auto;display:inline-block;padding:4px 8px"><option value="quantite">par quantité</option><option value="valeur">par valeur</option></select></label></div>
      <table class="lignes-table"><thead><tr><th>Frais</th><th>Compte</th><th class="right">Montant HT</th><th class="right">TVA%</th><th>Réglé par</th><th></th></tr></thead><tbody id="r-frais"></tbody></table>
      <button class="btn btn-sm" id="r-fadd" style="margin-top:4px"><i class="ti ti-plus"></i> Ajouter un frais</button>
      <div class="total-bar" style="margin-top:12px"><span class="lbl">Valeur reçue (HT + frais)</span><span class="val" id="r-total">0,00</span></div>`,
    footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="r-ok"><i class="ti ti-check"></i> Valider la réception</button>`,
  });
  const recompute = () => {
    const lines = [];
    document.querySelectorAll(".rl-row").forEach((tr) => {
      const q = +tr.querySelector(".rl-qte").value || 0, pu = +tr.dataset.pu;
      const v = Math.round(q * pu * 100) / 100; tr.querySelector(".rl-val").textContent = fmtNum(v);
      lines.push(v);
    });
    let frais = 0;
    $("#r-frais").querySelectorAll(".rf-row").forEach((tr) => frais += +tr.querySelector(".rf-mt").value || 0);
    $("#r-total").textContent = fmtNum(Math.round((lines.reduce((a, b) => a + b, 0) + frais) * 100) / 100);
  };
  const wireF = () => $("#r-frais").querySelectorAll(".rf-row").forEach((tr) => {
    tr.querySelector(".rf-mt").oninput = recompute;
    tr.querySelector(".rf-del").onclick = () => { tr.remove(); recompute(); };
    tr.querySelector(".rf-mode").onchange = () => fillCible(tr);
  });
  document.querySelectorAll(".rl-qte").forEach((i) => i.oninput = recompute);
  $("#r-fadd").onclick = () => { $("#r-frais").insertAdjacentHTML("beforeend", fHTML()); fillCible($("#r-frais").lastElementChild); wireF(); recompute(); };
  recompute();
  $("#r-ok").onclick = async () => {
    const lignes = [];
    for (const tr of document.querySelectorAll(".rl-row")) {
      const q = +tr.querySelector(".rl-qte").value || 0;
      if (q > 0) lignes.push({ ligne_commande_id: tr.dataset.lc, qte_recue: q });
    }
    if (!lignes.length) { toast("Aucune quantité reçue.", "ko"); return; }
    const frais = [];
    for (const tr of $("#r-frais").querySelectorAll(".rf-row")) {
      const mt = +tr.querySelector(".rf-mt").value || 0;
      if (!(mt > 0)) continue;
      const mode = tr.querySelector(".rf-mode").value, cible = tr.querySelector(".rf-cible").value;
      const fr = { libelle: tr.querySelector(".rf-lib").value.trim() || "Frais", compte: tr.querySelector(".rf-cpt").value.trim() || "6085", montant_ht: mt, taux_tva: +tr.querySelector(".rf-tva").value || 0, mode };
      if (mode === "credit" && cible) fr.tiers_id = cible;
      else if (mode === "banque") fr.banque_id = cible || null;
      else if (mode === "caisse") fr.caisse_id = cible || null;
      frais.push(fr);
    }
    try {
      const r = await api(`/commercial/commandes/${c.id}/receptionner`, { method: "POST", body: { repartition: $("#r-rep").value, lignes, frais } });
      closeModal(); toast(`Réception ${r.numero} — stock mis à jour.`, "ok"); go("receptions");
    } catch (e) { toast(e.message, "ko"); }
  };
}

RENDER.receptions = async () => {
  const el = $("#view-receptions");
  el.innerHTML = `<div class="muted">Chargement…</div>`;
  const [list, inter] = await Promise.all([
    api(`/commercial/receptions?societe_id=${currentSocieteId}`).catch(() => []),
    api(`/intersociete/receptions?societe_id=${currentSocieteId}`).catch(() => ({ a_recevoir: [], historique: [] })),
  ]);
  const interHtml = (inter.a_recevoir || []).length || (inter.historique || []).length ? `
    <div class="card" style="margin-bottom:14px"><div class="card-hdr"><div class="card-hdr-title"><i class="ti ti-affiliate"></i> Marchandises du groupe (PO intersociétés)</div></div>
    <div class="card-body">
      ${(inter.a_recevoir || []).length ? `<table><thead><tr><th>Commande</th><th>Réf. producteur</th><th>Fournisseur</th><th>Destination</th>
          <th>Course</th><th class="right">En attente</th><th></th></tr></thead><tbody>
        ${inter.a_recevoir.map((x) => { const [cl] = COURSE_ST[x.course_statut] || [x.course_statut || "—"]; return `<tr>
          <td class="num-cell">${esc(x.numero)}</td>
          <td class="num-cell">${esc(x.reference_producteur || "—")}</td>
          <td>${esc(x.fournisseur)}</td><td>${esc(x.destination || "—")}</td>
          <td>${x.course ? `${esc(x.course)} <span class="tag">${esc(cl)}</span>` : "—"}</td>
          <td class="right"><b>${x.receptionnable ? fmtNum(x.en_attente) : "—"}</b></td>
          <td class="right">${x.receptionnable
            ? `<button class="btn btn-sm btn-primary" data-recpo="${x.commande_id}"><i class="ti ti-package-import"></i> Réceptionner</button>`
            : `<button class="btn btn-sm" disabled title="Le vendeur n'a pas encore déclaré le chargement (bon de livraison)"><i class="ti ti-hourglass"></i> Attente chargement vendeur</button>`}</td></tr>`; }).join("")}
        </tbody></table>` : `<div class="muted">Aucune marchandise du groupe en attente de réception.</div>`}
      ${(inter.historique || []).length ? `<div class="muted" style="font-size:12px;margin:12px 0 4px">Réceptions effectuées</div>
        <table><tbody>${inter.historique.map((x) => `<tr ${x.statut === "annulee" ? 'style="opacity:.5;text-decoration:line-through"' : ""}><td class="num-cell">${esc(x.numero)}</td><td>${x.date}</td>
          <td class="num-cell">${esc(x.commande)}</td><td>${esc(x.fournisseur)}</td>
          <td><span class="pill ${x.statut === "confirmee" ? "st-payee" : (x.statut === "annulee" ? "st-annule" : "st-partielle")}">${x.statut === "confirmee" ? "Confirmée" : (x.statut === "annulee" ? "Annulée" : `À confirmer par ${esc(x.transporteur || "le transporteur")}`)}</span></td>
          <td class="right" style="white-space:nowrap">${x.statut !== "annulee" ? `<button class="btn btn-sm" data-recprt="${x.id}" title="Imprimer le bon de réception"><i class="ti ti-printer"></i></button>` : ""}
            ${x.statut === "a_confirmer" ? `<button class="btn btn-sm" data-recmod="${x.id}" title="Annuler ce constat pour le ressaisir (possible tant que le transporteur n'a pas confirmé)"><i class="ti ti-pencil"></i> Modifier</button>` : ""}</td></tr>`).join("")}</tbody></table>` : ""}
    </div></div>` : "";
  el.innerHTML = `<div class="section-hdr" style="margin-bottom:12px"><div class="section-title"><i class="ti ti-truck-delivery"></i> Réceptions</div>
      <span class="muted" style="margin-left:auto">La réception fait entrer le stock ; la facture solde ensuite le fournisseur.</span></div>
    ${interHtml}
    ${!list.length ? `<div class="empty"><i class="ti ti-truck-delivery"></i>Aucune réception. Créez-en une depuis une commande.</div>` :
      `<div class="card"><div class="card-body"><table><thead><tr><th>N°</th><th>Date</th><th>Commande</th><th class="right">Valeur reçue</th><th>Statut</th><th></th></tr></thead><tbody>
      ${list.map((r) => `<tr><td class="num-cell">${esc(r.numero)}</td><td>${r.date}</td><td class="num-cell">${esc(r.commande || "")}</td>
        <td class="right">${fmtNum(r.total_valeur)}</td><td><span class="pill ${r.statut === "facturee" ? "st-valide" : "st-a_justifier"}">${r.statut === "facturee" ? "facturée" : "reçue (non facturée)"}</span></td>
        <td class="right" style="white-space:nowrap"><button class="btn btn-sm" data-det="${r.id}"><i class="ti ti-eye"></i></button>
          ${r.statut === "recue" ? `<button class="btn btn-sm btn-primary" data-fact="${r.id}"><i class="ti ti-file-invoice"></i> Facturer</button>` : ""}</td></tr>`).join("")}
      </tbody></table></div></div>`}`;
  el.querySelectorAll("[data-det]").forEach((b) => b.onclick = () => receptionDetail(list.find((r) => r.id === b.dataset.det)));
  el.querySelectorAll("[data-fact]").forEach((b) => b.onclick = () => facturerModal(list.find((r) => r.id === b.dataset.fact)));
  el.querySelectorAll("[data-recpo]").forEach((b) => b.onclick = async () => {
    try { const d = await api(`/commercial/commandes/${b.dataset.recpo}`); receptionPOModal(d); }
    catch (e) { toast(e.message, "ko"); }
  });
  el.querySelectorAll("[data-recmod]").forEach((b) => b.onclick = async () => {
    if (!confirm("Annuler ce constat de réception pour le ressaisir ? (stock et manquants contre-passés)")) return;
    try { await api(`/intersociete/receptions/${b.dataset.recmod}`, { method: "DELETE" });
      toast("Constat annulé — ressaisissez la réception corrigée.", "ok"); RENDER.receptions(); }
    catch (e) { toast(e.message, "ko"); }
  });
  el.querySelectorAll("[data-recprt]").forEach((b) => b.onclick = () => printBonReception(b.dataset.recprt));
  filtreTable(el);
};

// Aperçu éditable avant d'enregistrer la facture fournisseur (procure-to-pay)
function facturerModal(r) {
  const ht = Math.round((r.lignes || []).reduce((s, l) => s + (l.montant_ht || 0), 0) * 100) / 100;   // marchandises seules
  const tva = Math.round((r.lignes || []).reduce((s, l) => s + Math.round(l.montant_ht * (l.taux_tva || 0)) / 100, 0) * 100) / 100;
  const ttc = Math.round((ht + tva) * 100) / 100;
  const today = isoLocal(new Date());
  const lignes = (r.lignes || []).map((l) => `<tr><td>${esc(l.designation)}</td><td class="right">${fmtNum(l.qte)}</td><td class="right">${fmtNum(l.prix_unitaire)}</td>
      <td class="right">${fmtNum(l.taux_tva)}%</td><td class="right">${fmtNum(l.montant_ht)}</td></tr>`).join("");
  const frais = (r.frais && r.frais.length) ? `<p class="muted" style="margin:10px 0 4px;font-size:12px">Frais accessoires (déjà comptabilisés à la réception, avec leur propre contrepartie — hors facture fournisseur)</p>
    <table><tbody>${r.frais.map((f) => { const cp = f.mode === "credit" ? `Crédit ${f.contrepartie || "fournisseur"}` : f.mode === "banque" ? `Banque` : `Caisse comptant`; return `<tr><td>${esc(f.libelle)}</td><td class="num-cell">${esc(f.compte)}</td><td class="right">${fmtNum(f.montant_ht)}</td><td>${esc(cp)}</td></tr>`; }).join("")}</tbody></table>` : "";
  modal({
    title: `Facturer la réception ${r.numero}`,
    wide: true,
    body: `<div class="banner"><i class="ti ti-file-invoice"></i> Facture du fournisseur des <b>marchandises</b>. Elle solde le provisoire (408) et reconnaît sa dette (401) + la TVA. Les frais accessoires ont déjà leur propre contrepartie (saisie à la réception).</div>
      <div class="form-row-3" style="margin-top:12px">
        <div class="form-group"><label class="form-label">Fournisseur</label><input class="form-input" value="${esc(r.fournisseur || "")}" disabled /></div>
        <div class="form-group"><label class="form-label">N° facture fournisseur</label><input id="ff-ref" class="form-input" value="${esc(r.reference_fournisseur || "")}" placeholder="ex. FT-2026-0453" /></div>
        <div class="form-group"><label class="form-label">Commande</label><input class="form-input" value="${esc(r.commande || "")}" disabled /></div></div>
      <div class="form-row" style="margin-top:4px">
        <div class="form-group"><label class="form-label">Date de la facture</label><input id="ff-date" class="form-input" type="date" value="${today}" /></div>
        <div class="form-group"><label class="form-label">Échéance (optionnelle)</label><input id="ff-ech" class="form-input" type="date" /></div></div>
      <table style="margin-top:10px"><thead><tr><th>Désignation</th><th class="right">Qté reçue</th><th class="right">P.U.</th><th class="right">TVA%</th><th class="right">HT</th></tr></thead><tbody>${lignes}</tbody></table>
      ${frais}
      <div class="total-bar" style="margin-top:10px;gap:20px"><span class="lbl">HT <b>${fmtNum(ht)}</b> · TVA <b>${fmtNum(tva)}</b></span><span class="val">TTC ${fmtUSD(ttc)}</span></div>`,
    footer: `<button class="btn" onclick="closeModal()">Annuler</button>
      <button class="btn btn-primary" id="ff-ok"><i class="ti ti-check"></i> Enregistrer la facture</button>`,
  });
  $("#ff-ok").onclick = async () => {
    try {
      const f = await api(`/commercial/receptions/${r.id}/facturer`, { method: "POST", body: {
        reference: $("#ff-ref").value.trim() || null, date_facture: $("#ff-date").value || null, echeance: $("#ff-ech").value || null } });
      closeModal(); toast(`Facture ${f.numero} enregistrée.`, "ok"); RENDER.receptions();
    } catch (e) { toast(e.message, "ko"); }
  };
}

function receptionDetail(r) {
  const lignes = r.lignes.map((l) => `<tr><td>${esc(l.designation)}</td><td class="right">${fmtNum(l.qte)}</td><td class="right">${fmtNum(l.prix_unitaire)}</td>
    <td class="right">${fmtNum(l.montant_ht)}</td><td class="right">${l.frais_reparti ? fmtNum(l.frais_reparti) : "—"}</td><td class="right num-cell">${fmtNum(l.cout)}</td></tr>`).join("");
  const frais = (r.frais && r.frais.length) ? `<p class="muted" style="margin:10px 0 4px;font-size:12px">Frais accessoires (répartis ${r.repartition === "valeur" ? "par valeur" : "par quantité"})</p>
    <table><thead><tr><th>Frais</th><th>Compte</th><th class="right">HT</th><th>Réglé par</th></tr></thead><tbody>${r.frais.map((f) => { const cp = f.mode === "credit" ? `Crédit ${f.contrepartie || "fournisseur"}` : f.mode === "banque" ? "Banque" : f.mode === "caisse" ? "Caisse comptant" : "—"; return `<tr><td>${esc(f.libelle)}</td><td class="num-cell">${esc(f.compte)}</td><td class="right">${fmtNum(f.montant_ht)}</td><td>${esc(cp)}</td></tr>`; }).join("")}</tbody></table>` : "";
  modal({
    title: `Réception ${r.numero}`,
    wide: true,
    body: `<div style="margin-bottom:8px"><span class="pill ${r.statut === "facturee" ? "st-valide" : "st-a_justifier"}">${r.statut}</span></div>
      <p class="muted">Commande ${esc(r.commande || "")} · reçue le ${r.date}</p>
      <table style="margin-top:8px"><thead><tr><th>Désignation</th><th class="right">Qté reçue</th><th class="right">P.U.</th><th class="right">HT</th><th class="right">Frais</th><th class="right">Coût d'entrée</th></tr></thead><tbody>${lignes}</tbody></table>
      ${frais}
      <div class="total-bar" style="margin-top:8px"><span class="lbl">Valeur entrée en stock</span><span class="val">${fmtUSD(r.total_valeur)}</span></div>`,
    footer: `<button class="btn" onclick="closeModal()">Fermer</button>
      <button class="btn" id="rec-pj"><i class="ti ti-paperclip"></i> Pièces jointes (BL)</button>
      <button class="btn btn-primary" id="rec-print"><i class="ti ti-printer"></i> Imprimer le bon</button>`,
  });
  $("#rec-pj").onclick = () => piecesModal("reception", r.id, `Pièces jointes — ${r.numero}`);
  $("#rec-print").onclick = () => {
    const soc = (societes.find((s) => s.id === currentSocieteId) || {}).nom || "";
    const w = Editions.fenetre();
    w.document.write(`<html><head><meta charset="utf-8"><title>${esc(r.numero)}</title><style>
      body{font-family:Arial,sans-serif;padding:34px;color:#222}h1{font-size:18px;color:#3C3489;margin:0 0 2px}.sub{color:#666;margin-bottom:16px;font-size:13px}
      table{width:100%;border-collapse:collapse;font-size:12.5px;margin:14px 0}th{text-align:left;padding:7px 10px;background:#F1F0FB;color:#3C3489;font-size:11px}td{padding:7px 10px;border-bottom:1px solid #eee}.r{text-align:right}
      .tot{text-align:right;font-weight:800;color:#3C3489;margin-top:10px}.sign{margin-top:60px;display:flex;justify-content:space-between}.sign div{border-top:1px solid #999;width:40%;text-align:center;padding-top:6px;font-size:12px;color:#666}</style></head><body>
      <h1>${esc(soc)}</h1><div class="sub">BON DE RÉCEPTION ${esc(r.numero)} · ${r.date} · commande ${esc(r.commande || "")}</div>
      <table><thead><tr><th>Désignation</th><th class="r">Qté reçue</th><th class="r">P.U.</th><th class="r">Coût d'entrée</th></tr></thead>
      <tbody>${r.lignes.map((l) => `<tr><td>${esc(l.designation)}</td><td class="r">${fmtNum(l.qte)}</td><td class="r">${fmtNum(l.prix_unitaire)}</td><td class="r">${fmtNum(l.cout)}</td></tr>`).join("")}</tbody></table>
      <div class="tot">Valeur entrée en stock : ${fmtNum(r.total_valeur)} USD</div>
      <div class="sign"><div>Le magasinier</div><div>Le contrôleur</div></div></body></html>`);
    w.document.close(); w.focus(); setTimeout(() => w.print(), 300);
  };
}

// ── Commercial : rapports (historique achats + synthèse ventes) ──────
let comRapTab = "achats";
RENDER["rapports-commercial"] = async () => {
  const el = $("#view-rapports-commercial");
  el.innerHTML = `<nav class="tabs" style="margin-bottom:16px">
      <button data-cr="achats" class="${comRapTab === "achats" ? "active" : ""}">Historique des achats</button>
      <button data-cr="ventes" class="${comRapTab === "ventes" ? "active" : ""}">Synthèse des ventes</button></nav>
    <div id="cr-body"><div class="muted">Chargement…</div></div>`;
  el.querySelectorAll("[data-cr]").forEach((b) => b.onclick = () => { comRapTab = b.dataset.cr; RENDER["rapports-commercial"](); });
  if (comRapTab === "achats") return crAchats();
  return crVentes();
};

const ORIG_ICON = { "Facture d'achat": "ti-shopping-cart", "Réception (commande)": "ti-truck-delivery", "Avance à justifier": "ti-cash", "Achat": "ti-box" };
async function crAchats() {
  const body = $("#cr-body");
  const list = await api(`/commercial/achats-historique?societe_id=${currentSocieteId}`).catch(() => []);
  const total = list.reduce((s, a) => s + a.total_valeur, 0);
  body.innerHTML = `<div class="banner"><i class="ti ti-info-circle"></i> Tous les achats entrés en stock, quelle que soit leur origine (facture directe, réception de commande, ou avance à justifier).</div>
    ${!list.length ? `<div class="empty"><i class="ti ti-box"></i>Aucun achat enregistré.</div>` :
      `<div class="card"><div class="card-body"><table><thead><tr><th>Date</th><th>Origine</th><th>Référence</th><th>Fournisseur / Bénéficiaire</th><th>Articles</th><th class="right">Qté</th><th class="right">Valeur (coût)</th></tr></thead><tbody>
      ${list.map((a) => `<tr><td>${a.date}</td>
        <td><i class="ti ${ORIG_ICON[a.origine] || "ti-box"}"></i> ${esc(a.origine)}</td>
        <td class="num-cell">${esc(a.reference)}</td><td>${esc(a.tiers || "—")}</td>
        <td class="muted" style="font-size:12px">${a.articles.map((x) => `${esc(x.code || "?")} ×${fmtNum(x.qte)}`).join(", ")}</td>
        <td class="right">${fmtNum(a.total_qte)}</td><td class="right" style="font-weight:700">${fmtNum(a.total_valeur)}</td></tr>`).join("")}
      <tr style="font-weight:700;border-top:2px solid var(--bdr)"><td colspan="6">TOTAL DES ACHATS</td><td class="right">${fmtNum(total)}</td></tr>
      </tbody></table></div></div>`}`;
}

async function crVentes() {
  const body = $("#cr-body");
  const d = await api(`/commercial/ventes-synthese?societe_id=${currentSocieteId}`).catch(() => null);
  if (!d) { body.innerHTML = `<div class="empty">Synthèse indisponible.</div>`; return; }
  const kpi = (l, v, sub, accent) => `<div class="kpi-card" style="--accent:${accent}"><div class="kpi-label">${l}</div><div class="kpi-val">${v}</div>${sub ? `<div class="kpi-sub">${sub}</div>` : ""}</div>`;
  body.innerHTML = `<div class="kpi-row" style="margin-bottom:16px">
      ${kpi("Chiffre d'affaires", fmtNum(d.chiffre_affaires) + " <span style='font-size:13px;color:var(--text3)'>USD</span>", `${d.nb_factures} facture(s)`, "var(--p)")}
      ${kpi("Marge", fmtNum(d.marge) + " <span style='font-size:13px;color:var(--text3)'>USD</span>", "sur ventes", "var(--g)")}
      ${kpi("Taux de marge", d.taux_marge + " %", "marge / CA", "var(--t)")}
      ${kpi("TVA collectée", fmtNum(d.tva_collectee) + " <span style='font-size:13px;color:var(--text3)'>USD</span>", "à reverser", "var(--a)")}</div>
    <div class="card"><div class="card-hdr"><div class="card-hdr-title"><i class="ti ti-trophy"></i> Palmarès des articles vendus</div></div>
      <div class="card-body"><table><thead><tr><th>Article</th><th class="right">Quantité vendue</th><th class="right">Coût des ventes</th></tr></thead><tbody>
      ${d.palmares.map((p) => `<tr><td class="num-cell">${esc(p.code)}</td><td class="right">${fmtNum(p.qte)}</td><td class="right">${fmtNum(p.cout)}</td></tr>`).join("") || '<tr><td colspan="3" class="muted">Aucune vente.</td></tr>'}
      </tbody></table></div></div>`;
}

// ── Commercial : listes de prix & points de vente ───────────────────
let tpTab = "listes";
RENDER["tarifs-pos"] = async () => {
  const el = $("#view-tarifs-pos");
  el.innerHTML = `<nav class="tabs" style="margin-bottom:16px">
      <button data-tp="listes" class="${tpTab === "listes" ? "active" : ""}">Listes de prix</button>
      <button data-tp="points" class="${tpTab === "points" ? "active" : ""}">Points de vente</button></nav>
    <div id="tp-body"><div class="muted">Chargement…</div></div>`;
  el.querySelectorAll("[data-tp]").forEach((b) => b.onclick = () => { tpTab = b.dataset.tp; RENDER["tarifs-pos"](); });
  if (tpTab === "listes") return tpListes();
  return tpPoints();
};

async function tpListes() {
  const body = $("#tp-body");
  const list = await api(`/commercial/listes-prix?societe_id=${currentSocieteId}`).catch(() => []);
  body.innerHTML = `<div class="section-hdr" style="margin-bottom:12px"><div class="section-title">Listes de prix</div>
      <button class="btn btn-sm btn-primary" id="lp-new" style="margin-left:auto"><i class="ti ti-plus"></i> Nouvelle liste</button></div>
    ${!list.length ? `<div class="empty"><i class="ti ti-tags"></i>Aucune liste de prix.</div>` :
      `<div class="card"><div class="card-body"><table><thead><tr><th>Code</th><th>Libellé</th><th class="right">Tarifs définis</th><th></th></tr></thead><tbody>
      ${list.map((l) => `<tr><td class="num-cell">${esc(l.code)}</td><td>${esc(l.libelle)}</td><td class="right">${l.nb_tarifs}</td>
        <td class="right"><button class="btn btn-sm" data-edit="${l.id}"><i class="ti ti-currency-dollar"></i> Éditer les prix</button></td></tr>`).join("")}
      </tbody></table></div></div>`}`;
  $("#lp-new").onclick = () => modal({
    title: "Nouvelle liste de prix",
    body: `<div class="form-row"><div class="form-group"><label class="form-label">Code</label><input id="lp-code" class="form-input" placeholder="ex. VIP" style="text-transform:uppercase" /></div>
      <div class="form-group"><label class="form-label">Libellé</label><input id="lp-lib" class="form-input" placeholder="ex. Tarif VIP" /></div></div>`,
    footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="lp-ok">Créer</button>`,
  }) || ($("#lp-ok").onclick = async () => {
    try { await api(`/commercial/listes-prix?societe_id=${currentSocieteId}`, { method: "POST", body: { code: $("#lp-code").value.trim(), libelle: $("#lp-lib").value.trim() } });
      closeModal(); toast("Liste créée.", "ok"); tpListes(); } catch (e) { toast(e.message, "ko"); }
  });
  body.querySelectorAll("[data-edit]").forEach((b) => b.onclick = () => tarifsEditor(list.find((l) => l.id === b.dataset.edit)));
}

async function tarifsEditor(liste) {
  const d = await api(`/commercial/listes-prix/${liste.id}/tarifs`).catch(() => null);
  if (!d) { toast("Liste indisponible.", "ko"); return; }
  modal({
    title: `Prix — ${esc(liste.libelle)}`,
    wide: true,
    body: `<p class="muted" style="margin-bottom:10px">Laissez vide pour appliquer le prix de vente par défaut de l'article.</p>
      <table class="lignes-table"><thead><tr><th>Article</th><th class="right">Prix par défaut</th><th class="right">Prix dans cette liste</th></tr></thead><tbody>
      ${d.articles.map((a) => `<tr><td><span class="num-cell">${esc(a.code)}</span> ${esc(a.designation)}</td>
        <td class="right muted">${fmtNum(a.prix_defaut)}</td>
        <td><input class="form-input tp-prix right" data-art="${a.article_id}" data-orig="${a.prix != null ? a.prix : ""}" type="number" step="any" placeholder="${fmtNum(a.prix_defaut)}" value="${a.prix != null ? a.prix : ""}" style="width:110px" /></td></tr>`).join("")}
      </tbody></table>`,
    footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="tp-save"><i class="ti ti-device-floppy"></i> Enregistrer les prix</button>`,
  });
  $("#tp-save").onclick = async () => {
    const rows = [...document.querySelectorAll(".tp-prix")].filter((i) => i.value.trim() !== (i.dataset.orig || ""));
    try {
      for (const i of rows) {
        const prix = i.value.trim() === "" ? null : +i.value;
        await api(`/commercial/listes-prix/${liste.id}/tarifs`, { method: "POST", body: { article_id: i.dataset.art, prix } });
      }
      closeModal(); toast(`${rows.length} prix mis à jour.`, "ok"); tpListes();
    } catch (e) { toast(e.message, "ko"); }
  };
}

async function tpPoints() {
  const body = $("#tp-body");
  const [list, listes, caisses, depots] = await Promise.all([
    api(`/commercial/points-vente?societe_id=${currentSocieteId}`).catch(() => []),
    api(`/commercial/listes-prix?societe_id=${currentSocieteId}`).catch(() => []),
    api(`/caisses?societe_id=${currentSocieteId}`).catch(() => []),
    api(`/stock/depots?societe_id=${currentSocieteId}`).catch(() => []),
  ]);
  const optionsDepot = (sel) => `<option value="">(dépôt central)</option>` +
    depots.filter((d) => d.type !== "central").map((d) => `<option value="${d.id}" ${sel === d.id ? "selected" : ""}>${esc(d.libelle)}</option>`).join("");
  body.innerHTML = `<div class="section-hdr" style="margin-bottom:12px"><div class="section-title">Points de vente</div>
      <button class="btn btn-sm btn-primary" id="pv-new" style="margin-left:auto"><i class="ti ti-plus"></i> Nouveau point de vente</button></div>
    ${!list.length ? `<div class="empty"><i class="ti ti-building-store"></i>Aucun point de vente.</div>` :
      `<div class="card"><div class="card-body"><table><thead><tr><th>Code</th><th>Libellé</th><th>Liste de prix</th><th>Caisse</th><th>Dépôt</th><th>Statut</th><th></th></tr></thead><tbody>
      ${list.map((p) => `<tr${p.actif ? "" : ' style="opacity:.5"'}><td class="num-cell">${esc(p.code)}</td><td>${esc(p.libelle)}</td>
        <td>${esc(p.liste_prix || "—")}</td><td>${esc(p.caisse || "—")}</td>
        <td>${esc(p.depot || "central")}</td>
        <td>${p.actif ? '<span class="pill st-valide">actif</span>' : '<span class="pill st-rejete">inactif</span>'}</td>
        <td class="right"><button class="btn btn-sm" data-pvedit="${p.id}" title="Modifier (libellé, liste, caisse, dépôt)"><i class="ti ti-pencil"></i></button></td></tr>`).join("")}
      </tbody></table></div></div>`}`;
  body.querySelectorAll("[data-pvedit]").forEach((b) => b.onclick = () => {
    const p = list.find((x) => x.id === b.dataset.pvedit);
    modal({
      title: `Modifier — ${p.libelle}`,
      body: `<div class="form-group"><label class="form-label">Libellé</label><input id="pve-lib" class="form-input" value="${esc(p.libelle)}" /></div>
        <div class="form-row">
        <div class="form-group"><label class="form-label">Liste de prix</label><select id="pve-lp" class="form-select"><option value="">(aucune — prix par défaut des articles)</option>${listes.map((l) => `<option value="${l.id}" ${p.liste_prix_id === l.id ? "selected" : ""}>${esc(l.libelle)}</option>`).join("")}</select></div>
        <div class="form-group"><label class="form-label">Caisse</label><select id="pve-cs" class="form-select">${caisses.map((cc) => `<option value="${cc.id}" ${p.caisse_id === cc.id ? "selected" : ""}>${esc(cc.libelle)}</option>`).join("")}</select></div>
        <div class="form-group"><label class="form-label">Dépôt (stock du comptoir)</label><select id="pve-dp" class="form-select">${optionsDepot(p.depot_id)}</select></div></div>
        <label style="display:flex;align-items:center;gap:8px;font-size:13px"><input type="checkbox" id="pve-actif" ${p.actif ? "checked" : ""} style="width:auto" /> Point de vente actif</label>`,
      footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="pve-ok"><i class="ti ti-check"></i> Enregistrer</button>`,
    });
    $("#pve-ok").onclick = async () => {
      try {
        await api(`/commercial/points-vente/${p.id}?societe_id=${currentSocieteId}`, { method: "PATCH", body: {
          libelle: $("#pve-lib").value, liste_prix_id: $("#pve-lp").value,
          caisse_id: $("#pve-cs").value, depot_id: $("#pve-dp").value,
          actif: $("#pve-actif").checked } });
        closeModal(); toast("Point de vente modifié.", "ok"); tpPoints();
      } catch (e) { toast(e.message, "ko"); }
    };
  });
  $("#pv-new").onclick = () => {
    modal({
      title: "Nouveau point de vente",
      body: `<div class="form-row"><div class="form-group"><label class="form-label">Code</label><input id="pv-code" class="form-input" style="text-transform:uppercase" /></div>
        <div class="form-group"><label class="form-label">Libellé</label><input id="pv-lib" class="form-input" /></div></div>
        <div class="form-row"><div class="form-group"><label class="form-label">Liste de prix</label>
          <select id="pv-lp" class="form-select"><option value="">— prix par défaut —</option>${listes.map((l) => `<option value="${l.id}">${esc(l.libelle)}</option>`).join("")}</select></div>
        <div class="form-group"><label class="form-label">Caisse</label>
          <select id="pv-caisse" class="form-select"><option value="">—</option>${caisses.map((c) => `<option value="${c.id}">${esc(c.libelle)}</option>`).join("")}</select></div>
        <div class="form-group"><label class="form-label">Dépôt (stock du comptoir)</label>
          <select id="pv-depot" class="form-select">${optionsDepot(null)}</select></div></div>`,
      footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="pv-ok">Créer</button>`,
    });
    $("#pv-ok").onclick = async () => {
      try {
        await api(`/commercial/points-vente?societe_id=${currentSocieteId}`, { method: "POST", body: {
          code: $("#pv-code").value.trim(), libelle: $("#pv-lib").value.trim(),
          liste_prix_id: $("#pv-lp").value || null, caisse_id: $("#pv-caisse").value || null,
          depot_id: $("#pv-depot").value || null } });
        closeModal(); toast("Point de vente créé.", "ok"); tpPoints();
      } catch (e) { toast(e.message, "ko"); }
    };
  };
}

// ── Point de vente (POS) — inspiré d'Odoo ────────────────────────────
// Grille par catégorie, code-barres, remises, client & fidélité, paniers en
// attente, paiement fractionné bi-devise, tickets du jour, retours, rapport X.
let posPvId = null, posCart = [], posArts = [], posPrix = {}, posSearch = "", posCat = null;
let posClient = null, posNote = "", posRemiseGlobale = 0, posCtx = {}, posPvs = [];
const POS_MODES = { espece: "Espèces", mobile_money: "Mobile Money", banque: "Banque", credit: "Crédit client" };
const posParkKey = () => `kh_pos_parked_${currentSocieteId}_${posPvId}`;
const posParked = () => JSON.parse(localStorage.getItem(posParkKey()) || "[]");
const fmtCDF = (v) => (Math.round(+v || 0)).toLocaleString("fr-FR") + " FC";

RENDER.pos = async () => {
  const el = $("#view-pos");
  el.innerHTML = `<div class="muted">Chargement…</div>`;
  posPvs = (await api(`/commercial/points-vente?societe_id=${currentSocieteId}`).catch(() => []))
    .filter((p) => p.actif && p.caisse_id);
  if (!posPvs.length) { el.innerHTML = `<div class="empty"><i class="ti ti-building-store"></i>Aucun point de vente configuré (avec une caisse). Créez-en un dans « Tarifs & points de vente ».</div>`; return; }
  if (!posPvId || !posPvs.find((p) => p.id === posPvId)) { posPvId = posPvs[0].id; posCart = []; posClient = null; }
  await posLoad();
  posRender();
};

async function posLoad() {
  [posArts, posCtx] = await Promise.all([
    api(`/commercial/articles?societe_id=${currentSocieteId}`).catch(() => []),
    api(`/commercial/pos/contexte?societe_id=${currentSocieteId}&point_vente_id=${posPvId}`).catch(() => ({})),
  ]);
  // seuls les articles de vente apparaissent au POS (pas les matières
  // premières ni les consommables internes)
  posArts = posArts.filter((a) => a.actif && (a.nature || "marchandise") === "marchandise");
  posPrix = {};
  posArts.forEach((a) => (posPrix[a.id] = a.prix_vente));
  const pvObj = posPvs.find((p) => p.id === posPvId);
  if (pvObj && pvObj.liste_prix_id) {
    const tf = await api(`/commercial/listes-prix/${pvObj.liste_prix_id}/tarifs`).catch(() => null);
    if (tf) tf.articles.forEach((a) => { if (a.prix != null) posPrix[a.article_id] = a.prix; });
  }
}

function posTotaux() {
  let brut = 0, ht = 0, tva = 0;
  const g = Math.min(Math.max(+posRemiseGlobale || 0, 0), 100);
  posCart.forEach((l) => {
    const b = Math.round(l.qte * l.prix * 100) / 100;
    const eff = 1 - (1 - (l.remise || 0) / 100) * (1 - g / 100);
    const h = Math.round(b * (1 - eff) * 100) / 100;
    brut += b; ht += h; tva += Math.round(h * l.taux) / 100;
  });
  brut = Math.round(brut * 100) / 100; ht = Math.round(ht * 100) / 100; tva = Math.round(tva * 100) / 100;
  return { brut, ht, tva, remise: Math.round((brut - ht) * 100) / 100, ttc: Math.round((ht + tva) * 100) / 100 };
}

function posAddArticle(a) {
  const ex = posCart.find((l) => l.article_id === a.id);
  if (ex) ex.qte += 1;
  else posCart.push({ article_id: a.id, code: a.code, designation: a.designation, qte: 1,
                      prix: posPrix[a.id], remise: 0, taux: a.assujetti_tva ? a.taux_tva : 0,
                      gere_stock: a.gere_stock, stock: a.stock_qte });
  posRender();
}

function posRender() {
  const el = $("#view-pos");
  const t = posTotaux();
  const s = posSearch.toLowerCase();
  const filt = posArts.filter((a) => (!posCat || a.categorie === posCat)
    && (!s || a.code.toLowerCase().includes(s) || a.designation.toLowerCase().includes(s) || (a.code_barres || "").includes(posSearch)));
  const cats = posCtx.categories || [];
  const sessionKo = posCtx.caisse && !posCtx.caisse.session_ouverte;
  const parked = posParked();
  const peutModifierPrix = has("DFI", "COMPTABLE");

  el.innerHTML = `
    <div class="section-hdr" style="margin-bottom:12px;flex-wrap:wrap;gap:10px">
      <div style="display:flex;align-items:center;gap:10px">
        <select id="pos-pv" class="form-select" style="width:auto">${posPvs.map((p) => `<option value="${p.id}" ${p.id === posPvId ? "selected" : ""}>${esc(p.libelle)} · ${esc(p.caisse || "")}</option>`).join("")}</select>
        ${posCtx.taux_cdf ? `<span class="tag" title="Taux du jour">1 $ = ${fmtCDF(posCtx.taux_cdf)}</span>` : `<span class="tag urgent">Taux CDF non défini</span>`}
      </div>
      <div style="display:flex;gap:8px">
        <button class="btn btn-sm" id="pos-btn-parked"><i class="ti ti-player-pause"></i> En attente${parked.length ? ` (${parked.length})` : ""}</button>
        <button class="btn btn-sm" id="pos-btn-tickets"><i class="ti ti-receipt-2"></i> Tickets</button>
        <button class="btn btn-sm" id="pos-btn-rapport"><i class="ti ti-report"></i> Rapport du jour</button>
      </div>
    </div>
    ${posCtx.caisse ? (sessionKo
      ? `<div class="pos-session closed"><i class="ti ti-lock"></i>
          <span>Session <b>fermée</b> — caisse « ${esc(posCtx.caisse.libelle)} ». Ouvrez-la pour commencer à vendre.</span>
          <button class="btn btn-primary btn-sm" id="pos-open" style="margin-left:auto"><i class="ti ti-lock-open"></i> Ouvrir la session</button></div>`
      : `<div class="pos-session"><i class="ti ti-lock-open"></i>
          <span>Session <b>ouverte</b>${posCtx.caisse.ouverte_depuis ? ` depuis ${hhmm(posCtx.caisse.ouverte_depuis)}` : ""}
            · fond ${fmtNum(posCtx.caisse.fond_usd || 0)} $${posCtx.caisse.fond_cdf ? ` + ${fmtCDF(posCtx.caisse.fond_cdf)}` : ""}</span>
          <span class="pos-session-soldes">${fmtNum((posCtx.caisse.soldes || {}).USD || 0)} $
            <em>${fmtCDF((posCtx.caisse.soldes || {}).CDF || 0)}</em></span>
          <span style="display:flex;gap:6px;margin-left:auto">
            ${posCtx.caisse_principale && !posCtx.caisse.est_principale ? `<button class="btn btn-sm" id="pos-remise" title="Remettre la recette à la caisse principale"><i class="ti ti-arrows-transfer-up"></i> Remise en caisse</button>` : ""}
            <button class="btn btn-sm" id="pos-close"><i class="ti ti-lock"></i> Clôturer</button></span></div>`) : ""}
    <div class="pos-grid">
      <div class="card"><div class="card-hdr"><div class="card-hdr-title"><i class="ti ti-box"></i> Articles</div>
        <input id="pos-search" class="form-input" placeholder="Code, nom ou code-barres + Entrée…" value="${esc(posSearch)}" style="width:270px" /></div>
        <div class="card-body">
        ${cats.length ? `<div class="pos-cats">
          <button class="pos-cat ${!posCat ? "on" : ""}" data-cat="">Tous</button>
          ${cats.map((c) => `<button class="pos-cat ${posCat === c ? "on" : ""}" data-cat="${esc(c)}">${esc(c)}</button>`).join("")}</div>` : ""}
        <div class="pos-articles">
          ${filt.map((a) => `<button class="pos-art" data-add="${a.id}">
            <b>${esc(a.code)}</b><span>${esc(a.designation)}</span>
            <em>${fmtNum(posPrix[a.id])} $</em>
            ${a.gere_stock ? `<i class="pos-stock ${a.stock_qte <= 0 ? "ko" : a.stock_qte < 5 ? "warn" : ""}">${fmtNum(a.stock_qte)}</i>` : ""}
          </button>`).join("") || '<div class="muted">Aucun article.</div>'}
        </div></div></div>

      <div class="card"><div class="card-hdr"><div class="card-hdr-title"><i class="ti ti-shopping-cart"></i> Panier</div>
        <div style="display:flex;gap:6px">
          ${posCart.length ? `<button class="btn btn-sm" id="pos-park" title="Mettre en attente"><i class="ti ti-player-pause"></i></button>
          <button class="btn btn-sm" id="pos-clear" title="Vider"><i class="ti ti-trash"></i></button>` : ""}</div></div>
        <div class="card-body">
        <div class="pos-client" id="pos-client-row">
          <i class="ti ${posClient ? "ti-user-check" : "ti-user-plus"}"></i>
          ${posClient ? `<div><b>${esc(Catalogue.label(posClient))}</b>
            <div class="muted" style="font-size:11.5px">${esc(posClient.code)} · ${fmtNum(posClient.points_fidelite)} pts fidélité${posClient.limite_credit_usd != null ? ` · crédit max ${fmtNum(posClient.limite_credit_usd)} $` : ""}</div>${posClient.societe_id===null?'<div class="muted">Fiche partagée : fidélité et contrôle du plafond de crédit communs aux sociétés qui l’utilisent.</div>':''}</div>
            <button class="btn btn-sm" id="pos-client-x"><i class="ti ti-x"></i></button>`
          : `<span class="muted">Client comptant — cliquez pour choisir un client</span>`}
        </div>
        ${!posCart.length ? '<div class="muted" style="padding:14px 0">Panier vide — cliquez un article ou scannez un code-barres.</div>' :
          `<table class="pos-table"><thead><tr><th>Article</th><th class="right">Qté</th><th class="right">P.U. $</th><th class="right">Rem.%</th><th class="right">Total</th><th></th></tr></thead><tbody>
          ${posCart.map((l, i) => {
            const b = Math.round(l.qte * l.prix * 100) / 100;
            const net = Math.round(b * (1 - (l.remise || 0) / 100) * 100) / 100;
            return `<tr><td>${esc(l.designation)}${l.gere_stock && l.qte > l.stock ? ' <span class="tag urgent" title="Stock insuffisant">stock !</span>' : ""}</td>
            <td class="right"><div class="pos-stepper"><button data-step="-1" data-i="${i}">−</button>
              <input class="pos-qte" type="number" step="any" data-i="${i}" value="${l.qte}" />
              <button data-step="1" data-i="${i}">+</button></div></td>
            <td class="right">${peutModifierPrix ? `<input class="form-input pos-prix right" type="number" step="any" data-i="${i}" value="${l.prix}" style="width:70px" />` : fmtNum(l.prix)}</td>
            <td class="right"><input class="form-input pos-rem right" type="number" step="any" min="0" max="100" data-i="${i}" value="${l.remise || 0}" style="width:56px" /></td>
            <td class="right"><b>${fmtNum(net)}</b>${l.remise ? `<div class="muted" style="font-size:10.5px;text-decoration:line-through">${fmtNum(b)}</div>` : ""}</td>
            <td class="right"><button class="btn btn-sm pos-del" data-i="${i}"><i class="ti ti-x"></i></button></td></tr>`;
          }).join("")}
          </tbody></table>`}
        <div style="display:flex;gap:10px;margin-top:10px;align-items:center">
          <label class="form-label" style="margin:0;white-space:nowrap">Remise globale %</label>
          <input id="pos-remise-g" class="form-input right" type="number" step="any" min="0" max="100" value="${posRemiseGlobale || 0}" style="width:70px" />
          <input id="pos-note" class="form-input" placeholder="Note sur le ticket…" value="${esc(posNote)}" style="flex:1" />
        </div>
        ${t.remise ? `<div style="display:flex;justify-content:space-between;margin-top:8px;font-size:13px" class="muted"><span>Remises accordées</span><span>−${fmtNum(t.remise)} $</span></div>` : ""}
        <div class="total-bar" style="margin-top:10px"><span class="lbl">HT ${fmtNum(t.ht)} · TVA ${fmtNum(t.tva)}</span>
          <span class="val">${fmtNum(t.ttc)} $${posCtx.taux_cdf ? ` <small style="font-weight:400;font-size:12px">≈ ${fmtCDF(t.ttc * posCtx.taux_cdf)}</small>` : ""}</span></div>
        <button class="btn btn-primary" id="pos-pay" style="width:100%;justify-content:center;margin-top:10px;padding:12px" ${posCart.length && !sessionKo ? "" : "disabled"}><i class="ti ti-cash"></i> Paiement — ${fmtNum(t.ttc)} $</button>
        </div></div>
    </div>`;

  $("#pos-pv").onchange = async (e) => { posPvId = e.target.value; posCart = []; posClient = null; posCat = null; await posLoad(); posRender(); };
  const se = $("#pos-search");
  se.oninput = (e) => { posSearch = e.target.value; const f = document.activeElement === se; posRender(); if (f) { const n = $("#pos-search"); n.focus(); n.setSelectionRange(posSearch.length, posSearch.length); } };
  se.onkeydown = (e) => {   // scan code-barres : correspondance exacte + Entrée
    if (e.key !== "Enter" || !posSearch.trim()) return;
    const exact = posArts.find((a) => a.code_barres === posSearch.trim() || a.code.toLowerCase() === posSearch.trim().toLowerCase());
    if (exact) { posSearch = ""; posAddArticle(exact); $("#pos-search").focus(); }
  };
  el.querySelectorAll("[data-cat]").forEach((b) => b.onclick = () => { posCat = b.dataset.cat || null; posRender(); });
  el.querySelectorAll("[data-add]").forEach((b) => b.onclick = () => posAddArticle(posArts.find((x) => x.id === b.dataset.add)));
  el.querySelectorAll("[data-step]").forEach((b) => b.onclick = () => {
    const l = posCart[+b.dataset.i]; l.qte = Math.max(0, Math.round((l.qte + +b.dataset.step) * 1000) / 1000);
    if (!l.qte) posCart.splice(+b.dataset.i, 1); posRender();
  });
  el.querySelectorAll(".pos-qte").forEach((i) => i.onchange = (e) => { const l = posCart[+e.target.dataset.i]; l.qte = Math.max(0, +e.target.value || 0); if (!l.qte) posCart.splice(+e.target.dataset.i, 1); posRender(); });
  el.querySelectorAll(".pos-prix").forEach((i) => i.onchange = (e) => { posCart[+e.target.dataset.i].prix = Math.max(0, +e.target.value || 0); posRender(); });
  el.querySelectorAll(".pos-rem").forEach((i) => i.onchange = (e) => { posCart[+e.target.dataset.i].remise = Math.min(100, Math.max(0, +e.target.value || 0)); posRender(); });
  el.querySelectorAll(".pos-del").forEach((b) => b.onclick = () => { posCart.splice(+b.dataset.i, 1); posRender(); });
  $("#pos-remise-g").onchange = (e) => { posRemiseGlobale = Math.min(100, Math.max(0, +e.target.value || 0)); posRender(); };
  $("#pos-note").onchange = (e) => { posNote = e.target.value; };
  $("#pos-client-row").onclick = (e) => { if (!e.target.closest("#pos-client-x")) posChoisirClient(); };
  if ($("#pos-client-x")) $("#pos-client-x").onclick = (e) => { e.stopPropagation(); posClient = null; posRender(); };
  if ($("#pos-clear")) $("#pos-clear").onclick = () => { posCart = []; posRender(); };
  if ($("#pos-park")) $("#pos-park").onclick = posParker;
  $("#pos-btn-parked").onclick = posListeParked;
  $("#pos-btn-tickets").onclick = posListeTickets;
  $("#pos-btn-rapport").onclick = posRapport;
  if ($("#pos-pay")) $("#pos-pay").onclick = posEncaisser;
  // Session de caisse gérée directement depuis le POS (comme l'app Point de Vente d'Odoo)
  const posReload = async () => { await posLoad(); posRender(); };
  if ($("#pos-open")) $("#pos-open").onclick = () => ouvrirCaisseModal(posCtx.caisse.id, posReload);
  if ($("#pos-close")) $("#pos-close").onclick = () => clotureModal(posCtx.caisse.soldes || {}, posCtx.caisse.id, posReload);
  if ($("#pos-remise")) $("#pos-remise").onclick = () => transfertModal({
    sourceId: posCtx.caisse.id, destId: posCtx.caisse_principale.id,
    motif: "Remise recette POS", devise: "USD", montant: (posCtx.caisse.soldes || {}).USD || 0 });
}

// ── Client ───────────────────────────────────────────────────────────
async function posChoisirClient() {
  const clients = (await api(`/commercial/tiers?societe_id=${currentSocieteId}&type=client`).catch(() => []))
    .filter((c) => c.code !== "COMPTANT");
  modal({
    title: "Choisir un client",
    body: `<input id="pc-q" class="form-input" placeholder="Rechercher…" style="margin-bottom:10px" />
      <div id="pc-list" style="max-height:300px;overflow-y:auto"></div>
      <div style="border-top:1px solid var(--bdr);margin-top:12px;padding-top:12px">
        <div class="muted" style="font-size:12px;margin-bottom:8px">Nouveau client (création rapide)</div>
        <button class="btn btn-primary" id="pc-add">Créer un client…</button></div>`,
    footer: `<button class="btn" onclick="closeModal()">Fermer</button>`,
  });
  const renderList = () => {
    const q = ($("#pc-q").value || "").toLowerCase();
    $("#pc-list").innerHTML = clients.filter((c) => !q || c.nom.toLowerCase().includes(q) || c.code.toLowerCase().includes(q))
      .map((c) => `<button class="pos-client-item" data-id="${c.id}"><b>${esc(Catalogue.label(c))}</b>
        <span class="muted">${esc(c.code)} · ${fmtNum(c.points_fidelite)} pts${c.limite_credit_usd != null ? ` · crédit ${fmtNum(c.limite_credit_usd)} $` : ""}</span></button>`).join("")
      || '<div class="muted" style="padding:10px 0">Aucun client.</div>';
    $("#pc-list").querySelectorAll("[data-id]").forEach((b) => b.onclick = () => {
      posClient = clients.find((c) => c.id === b.dataset.id); closeModal(); posRender();
    });
  };
  $("#pc-q").oninput = renderList; renderList(); $("#pc-q").focus();
  $('#pc-add').onclick = () => tiersQuickModal('client', c=>{posClient=c;closeModal();posRender();});

}

// ── Paniers en attente ───────────────────────────────────────────────
function posParker() {
  const parked = posParked();
  parked.push({ id: Date.now(), heure: new Date().toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" }),
                client: posClient, note: posNote, remiseGlobale: posRemiseGlobale, cart: posCart });
  localStorage.setItem(posParkKey(), JSON.stringify(parked));
  posCart = []; posClient = null; posNote = ""; posRemiseGlobale = 0;
  toast("Panier mis en attente.", "ok"); posRender();
}

function posListeParked() {
  const parked = posParked();
  modal({
    title: "Paniers en attente",
    body: !parked.length ? '<div class="muted">Aucun panier en attente.</div>'
      : parked.map((p, i) => `<div class="pos-parked-item">
          <div><b>${p.heure}</b> — ${p.cart.length} article(s) · ${fmtNum(p.cart.reduce((s, l) => s + l.qte * l.prix, 0))} $
          ${p.client ? `<div class="muted" style="font-size:12px">${esc(p.client.nom)}</div>` : ""}</div>
          <div style="display:flex;gap:6px">
            <button class="btn btn-sm btn-primary" data-resume="${i}"><i class="ti ti-player-play"></i> Reprendre</button>
            <button class="btn btn-sm" data-drop="${i}"><i class="ti ti-trash"></i></button></div></div>`).join(""),
    footer: `<button class="btn" onclick="closeModal()">Fermer</button>`,
  });
  document.querySelectorAll("[data-resume]").forEach((b) => b.onclick = () => {
    const parked2 = posParked();
    const p = parked2.splice(+b.dataset.resume, 1)[0];
    if (posCart.length) { parked2.push({ id: Date.now(), heure: new Date().toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" }), client: posClient, note: posNote, remiseGlobale: posRemiseGlobale, cart: posCart }); toast("Panier courant mis en attente.", ""); }
    localStorage.setItem(posParkKey(), JSON.stringify(parked2));
    posCart = p.cart; posClient = p.client; posNote = p.note || ""; posRemiseGlobale = p.remiseGlobale || 0;
    closeModal(); posRender();
  });
  document.querySelectorAll("[data-drop]").forEach((b) => b.onclick = () => {
    const parked2 = posParked(); parked2.splice(+b.dataset.drop, 1);
    localStorage.setItem(posParkKey(), JSON.stringify(parked2));
    closeModal(); posListeParked(); posRender();
  });
}

// ── Paiement fractionné ──────────────────────────────────────────────
let posPaiements = [];
function posEncaisser() {
  const t = posTotaux();
  const taux = posCtx.taux_cdf;
  posPaiements = [{ mode: "espece", devise: "USD", montant: t.ttc, reference: "" }];
  const rerender = () => {
    const paye = posPaiements.reduce((s, p) => s + (p.devise === "CDF" && taux ? (+p.montant || 0) / taux : (+p.montant || 0)), 0);
    const cash = posPaiements.filter((p) => p.mode === "espece").reduce((s, p) => s + (p.devise === "CDF" && taux ? (+p.montant || 0) / taux : (+p.montant || 0)), 0);
    const noncash = paye - cash;
    const reste = Math.max(0, Math.round((t.ttc - paye) * 100) / 100);
    const monnaie = Math.max(0, Math.round((cash - Math.max(0, t.ttc - noncash)) * 100) / 100);
    $("#pp-rows").innerHTML = posPaiements.map((p, i) => p.mode === "chambre" ? `<div class="pp-row">
      <div class="form-input" style="flex:1;display:flex;align-items:center;gap:6px"><i class="ti ti-bed"></i> Sur la chambre — <b>${esc(p.sejour_libelle || "")}</b></div>
      <input class="form-input right pp-mnt" data-i="${i}" type="number" step="any" value="${p.montant}" disabled />
      <button class="btn btn-sm pp-del" data-i="${i}"><i class="ti ti-x"></i></button></div>` : `<div class="pp-row">
      <select class="form-select pp-mode" data-i="${i}">${Object.entries(POS_MODES).map(([k, v]) => `<option value="${k}" ${p.mode === k ? "selected" : ""} ${k === "credit" && !posClient ? "disabled" : ""}>${v}${k === "credit" && !posClient ? " (choisir un client)" : ""}</option>`).join("")}</select>
      <select class="form-select pp-dev" data-i="${i}" ${p.mode !== "espece" && p.mode !== "mobile_money" ? "" : ""}><option value="USD" ${p.devise === "USD" ? "selected" : ""}>USD</option><option value="CDF" ${p.devise === "CDF" ? "selected" : ""} ${!taux ? "disabled" : ""}>CDF</option></select>
      <input class="form-input right pp-mnt" data-i="${i}" type="number" step="any" value="${p.montant}" />
      ${p.mode === "mobile_money" || p.mode === "banque" ? `<input class="form-input pp-ref" data-i="${i}" placeholder="Réf. transaction" value="${esc(p.reference || "")}" style="width:120px" />` : ""}
      <button class="btn btn-sm pp-del" data-i="${i}"><i class="ti ti-x"></i></button></div>`).join("");
    $("#pp-recap").innerHTML = `
      <div class="pp-line"><span>Total à payer</span><b>${fmtNum(t.ttc)} $${taux ? ` <small>≈ ${fmtCDF(t.ttc * taux)}</small>` : ""}</b></div>
      <div class="pp-line"><span>Payé</span><b>${fmtNum(Math.round(paye * 100) / 100)} $</b></div>
      ${reste > 0 ? `<div class="pp-line ko"><span>Reste à payer</span><b>${fmtNum(reste)} $${taux ? ` <small>≈ ${fmtCDF(reste * taux)}</small>` : ""}</b></div>`
        : `<div class="pp-line ok"><span>Monnaie à rendre</span><b>${fmtNum(monnaie)} $${taux && monnaie ? ` <small>≈ ${fmtCDF(monnaie * taux)}</small>` : ""}</b></div>`}`;
    $("#pp-ok").disabled = reste > 0.009;
    $("#pp-rows").querySelectorAll(".pp-mode").forEach((sel) => sel.onchange = (e) => { const p = posPaiements[+e.target.dataset.i]; p.mode = e.target.value; if (p.mode === "credit") p.devise = "USD"; rerender(); });
    $("#pp-rows").querySelectorAll(".pp-dev").forEach((sel) => sel.onchange = (e) => { posPaiements[+e.target.dataset.i].devise = e.target.value; rerender(); });
    $("#pp-rows").querySelectorAll(".pp-mnt").forEach((inp) => inp.onchange = (e) => { posPaiements[+e.target.dataset.i].montant = Math.max(0, +e.target.value || 0); rerender(); });
    $("#pp-rows").querySelectorAll(".pp-ref").forEach((inp) => inp.onchange = (e) => { posPaiements[+e.target.dataset.i].reference = e.target.value; });
    $("#pp-rows").querySelectorAll(".pp-del").forEach((b) => b.onclick = () => { posPaiements.splice(+b.dataset.i, 1); rerender(); });
  };
  modal({
    title: `Paiement — ${fmtNum(t.ttc)} $`,
    body: `<div id="pp-rows"></div>
      <div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:8px">
        <button class="btn btn-sm" id="pp-add-usd"><i class="ti ti-cash"></i> + Espèces $</button>
        <button class="btn btn-sm" id="pp-add-cdf" ${taux ? "" : "disabled"}><i class="ti ti-cash"></i> + Espèces FC</button>
        <button class="btn btn-sm" id="pp-add-mm"><i class="ti ti-device-mobile"></i> + Mobile Money</button>
        <button class="btn btn-sm" id="pp-add-bq"><i class="ti ti-building-bank"></i> + Banque</button>
        <button class="btn btn-sm" id="pp-add-cr" ${posClient ? "" : "disabled"} title="${posClient ? "" : "Choisissez d'abord un client"}"><i class="ti ti-user-dollar"></i> + Crédit</button>
        <button class="btn btn-sm" id="pp-add-ch" title="Envoyer le ticket sur la note d'un séjour en cours (hôtel)"><i class="ti ti-bed"></i> Sur la chambre</button>
      </div>
      <div id="pp-recap" style="margin-top:12px"></div>`,
    footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="pp-ok"><i class="ti ti-check"></i> Valider la vente</button>`,
  });
  const addP = (mode, devise) => { const t2 = posTotaux(); const paye = posPaiements.reduce((s, p) => s + (p.devise === "CDF" && taux ? (+p.montant || 0) / taux : (+p.montant || 0)), 0); const reste = Math.max(0, Math.round((t2.ttc - paye) * 100) / 100); posPaiements.push({ mode, devise, montant: devise === "CDF" ? Math.round(reste * taux) : reste, reference: "" }); rerender(); };
  $("#pp-add-usd").onclick = () => addP("espece", "USD");
  $("#pp-add-cdf").onclick = () => addP("espece", "CDF");
  $("#pp-add-mm").onclick = () => addP("mobile_money", "USD");
  $("#pp-add-bq").onclick = () => addP("banque", "USD");
  $("#pp-add-cr").onclick = () => addP("credit", "USD");
  $("#pp-add-ch").onclick = async () => {
    const sejours = await api(`/hotel/sejours?societe_id=${currentSocieteId}&statut=arrivee`).catch(() => []);
    if (!sejours.length) { toast("Aucun séjour en cours à l'hôtel.", "ko"); return; }
    modal({ title: "Sur quelle chambre ?",
      body: `<div class="form-group"><label class="form-label">Séjour en cours</label>
        <select id="ppch-sej" class="form-select">${sejours.map((s) => `<option value="${s.id}">Ch. ${esc(s.chambre)} — ${esc(s.client_nom)} (${esc(s.numero)})</option>`).join("")}</select></div>
        <div class="banner"><i class="ti ti-info-circle"></i> Le ticket entier va sur la note du séjour et sera encaissé au check-out.</div>`,
      footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="ppch-ok"><i class="ti ti-check"></i> Sur la chambre</button>` });
    $("#ppch-ok").onclick = () => {
      const opt = $("#ppch-sej").selectedOptions[0];
      posPaiements = [{ mode: "chambre", devise: "USD", montant: posTotaux().ttc,
        sejour_id: opt.value, sejour_libelle: opt.text, reference: "" }];
      closeModal(); rerender();
    };
  };
  rerender();
  $("#pp-ok").onclick = async () => {
    try {
      const tk = await api(`/commercial/pos/vente?societe_id=${currentSocieteId}`, { method: "POST", body: {
        point_vente_id: posPvId, client_id: posClient ? posClient.id : null,
        remise_globale_pct: posRemiseGlobale || 0, note: posNote || null,
        paiements: posPaiements.filter((p) => +p.montant > 0).map((p) => ({ mode: p.mode, devise: p.devise, montant: +p.montant, reference: p.reference || null, sejour_id: p.sejour_id || undefined })),
        lignes: posCart.map((l) => ({ article_id: l.article_id, qte: l.qte, prix: l.prix, remise_pct: l.remise || 0 })) } });
      closeModal();
      posCart = []; posClient = null; posNote = ""; posRemiseGlobale = 0;
      posTicket(tk); await posLoad(); posRender();
    } catch (e) { toast(e.message, "ko"); }
  };
}

// ── Ticket (affichage + impression 80 mm) ────────────────────────────
function posTicket(tk) {
  const pmt = (tk.paiements || []).map((p) => `<div style="display:flex;justify-content:space-between;font-size:12.5px">
    <span>${POS_MODES[p.mode] || p.mode}${p.devise === "CDF" ? " (FC)" : ""}${p.reference ? ` · ${esc(p.reference)}` : ""}</span>
    <span>${p.devise === "CDF" ? fmtCDF(p.montant) : fmtNum(p.montant) + " $"}</span></div>`).join("");
  modal({
    title: `${tk.est_avoir ? "Avoir" : "Ticket"} ${tk.numero}`,
    body: `<div style="text-align:center;margin-bottom:8px"><b>${esc(tk.point_vente || "")}</b>
      <div class="muted" style="font-size:12px">${tk.date} · ${esc(tk.caisse || "")}${tk.vendeur ? ` · ${esc(tk.vendeur)}` : ""}</div>
      ${tk.client && tk.client.code !== "COMPTANT" ? `<div class="tag" style="margin-top:4px">${esc(tk.client.nom)}</div>` : ""}
      ${tk.origine_numero ? `<div class="muted" style="font-size:12px">Retour sur ${esc(tk.origine_numero)}</div>` : ""}</div>
      <table><tbody>${tk.lignes.map((l) => `<tr><td>${esc(l.designation)}<div class="muted" style="font-size:11px">${fmtNum(l.qte)} × ${fmtNum(l.prix)}${l.remise_pct ? ` − ${fmtNum(l.remise_pct)} %` : ""}</div></td><td class="right">${fmtNum(l.ht)}</td></tr>`).join("")}</tbody></table>
      ${tk.remise_totale ? `<div style="display:flex;justify-content:space-between;font-size:13px" class="muted"><span>Remises</span><span>−${fmtNum(tk.remise_totale)} $</span></div>` : ""}
      <div class="total-bar" style="margin-top:8px"><span class="lbl">HT ${fmtNum(tk.total_ht)} · TVA ${fmtNum(tk.total_tva)}</span>
        <span class="val">${tk.est_avoir ? "−" : ""}${fmtNum(tk.total_ttc)} $${tk.total_ttc_cdf ? ` <small style="font-weight:400;font-size:11px">≈ ${fmtCDF(tk.total_ttc_cdf)}</small>` : ""}</span></div>
      ${pmt ? `<div style="margin-top:8px;border-top:1px dashed var(--bdr);padding-top:6px">${pmt}</div>` : ""}
      ${tk.monnaie ? `<div style="display:flex;justify-content:space-between;margin-top:4px;font-size:13px"><span>Monnaie rendue</span><b>${fmtNum(tk.monnaie)} $</b></div>` : ""}
      ${tk.note ? `<div class="muted" style="font-size:12px;margin-top:6px"><i class="ti ti-note"></i> ${esc(tk.note)}</div>` : ""}
      <div class="muted" style="font-size:12px;margin-top:8px">
        ${tk.client && tk.client.code !== "COMPTANT" ? `Fidélité : ${tk.est_avoir ? "−" : "+"}${fmtNum(tk.points_fidelite)} pts (cumul ${fmtNum(tk.client.points_fidelite)})` : `Points de fidélité : ${fmtNum(tk.points_fidelite)}`}
        ${tk.commission ? ` · Commission vendeur : ${fmtNum(tk.commission)} $` : ""}</div>`,
    footer: `<button class="btn" onclick="closeModal()">Fermer</button><button class="btn btn-primary" id="tk-print"><i class="ti ti-printer"></i> Imprimer</button>`,
  });
  $("#tk-print").onclick = () => {
    const w = window.open("", "_blank", "width=380,height=640");
    if(!w){toast("Autorisez la fenêtre d’impression du ticket puis réessayez.","ko");return;}
    w.document.write(`<html><head><meta charset="utf-8"><title>${esc(tk.numero)}</title><style>@page{size:80mm auto;margin:3mm}body{font-family:Arial,sans-serif;padding:8px;font-size:11px;line-height:1.4;color:#111;max-width:74mm;margin:0 auto}h3{text-align:center;margin:0}.c{text-align:center;color:#555}.r{text-align:right}table{width:100%;border-collapse:collapse;margin:8px 0}td{padding:2px 0}.tot{border-top:1px dashed #000;margin-top:6px;padding-top:6px;font-weight:bold}.sep{border-top:1px dashed #000;margin-top:6px;padding-top:6px}</style></head><body>
      <h3>${esc(tk.point_vente || "")}</h3><div class="c">${tk.date} · ${esc(tk.caisse || "")}${tk.vendeur ? ` · ${esc(tk.vendeur)}` : ""}</div>
      <div class="c">${tk.est_avoir ? "AVOIR" : "Ticket"} ${esc(tk.numero)}${tk.origine_numero ? ` (retour sur ${esc(tk.origine_numero)})` : ""}</div>
      ${tk.client && tk.client.code !== "COMPTANT" ? `<div class="c">Client : ${esc(tk.client.nom)}</div>` : ""}
      <table>${tk.lignes.map((l) => `<tr><td>${esc(l.designation)}<br/>${fmtNum(l.qte)} x ${fmtNum(l.prix)}${l.remise_pct ? ` -${fmtNum(l.remise_pct)}%` : ""}</td><td class="r">${fmtNum(l.ht)}</td></tr>`).join("")}</table>
      ${tk.remise_totale ? `<div>Remises : -${fmtNum(tk.remise_totale)} $</div>` : ""}
      <div class="tot">HT ${fmtNum(tk.total_ht)} — TVA ${fmtNum(tk.total_tva)}<br/>TOTAL ${tk.est_avoir ? "-" : ""}${fmtNum(tk.total_ttc)} USD${tk.total_ttc_cdf ? ` (≈ ${fmtCDF(tk.total_ttc_cdf)})` : ""}</div>
      ${(tk.paiements || []).length ? `<div class="sep">${tk.paiements.map((p) => `${POS_MODES[p.mode] || p.mode} : ${p.devise === "CDF" ? fmtCDF(p.montant) : fmtNum(p.montant) + " $"}${p.reference ? ` (${esc(p.reference)})` : ""}`).join("<br/>")}</div>` : ""}
      ${tk.monnaie ? `<div>Monnaie rendue : ${fmtNum(tk.monnaie)} $</div>` : ""}
      ${tk.client && tk.client.code !== "COMPTANT" ? `<div class="c" style="margin-top:8px">Fidélité : cumul ${fmtNum(tk.client.points_fidelite)} pts</div>` : ""}
      <div class="c" style="margin-top:10px">Merci de votre visite</div></body></html>`);
    w.document.close(); w.focus(); setTimeout(() => w.print(), 250);
  };
}

// ── Tickets du jour + retours ────────────────────────────────────────
async function posListeTickets() {
  let tks;
  try { tks = await api(`/commercial/pos/tickets?societe_id=${currentSocieteId}&point_vente_id=${posPvId}`); }
  catch (e) { toast(e.message, "ko"); return; }
  modal({
    title: "Tickets du jour",
    body: !tks.length ? '<div class="muted">Aucun ticket aujourd’hui.</div>'
      : `<table><thead><tr><th>Heure</th><th>N°</th><th>Client</th><th class="right">TTC $</th><th>Règlement</th><th></th></tr></thead><tbody>
        ${tks.map((t2) => `<tr ${t2.type === "avoir_vente" ? 'style="opacity:.75"' : ""}>
          <td>${t2.heure ? t2.heure.slice(11, 16) : ""}</td>
          <td>${esc(t2.numero)}${t2.type === "avoir_vente" ? ' <span class="tag">avoir</span>' : ""}${t2.avoirs.length ? ` <span class="tag urgent" title="${esc(t2.avoirs.join(", "))}">retour</span>` : ""}</td>
          <td>${esc(t2.client || "")}</td>
          <td class="right">${t2.type === "avoir_vente" ? "−" : ""}${fmtNum(t2.total_ttc)}</td>
          <td class="muted" style="font-size:12px">${t2.modes.map((m) => POS_MODES[m] || m).join(" + ")}</td>
          <td class="right" style="white-space:nowrap">
            <button class="btn btn-sm" data-reprint="${t2.id}" title="Réimprimer"><i class="ti ti-printer"></i></button>
            ${t2.type === "vente" ? `<button class="btn btn-sm" data-retour="${t2.id}" title="Retour / remboursement"><i class="ti ti-arrow-back-up"></i></button>` : ""}
          </td></tr>`).join("")}</tbody></table>`,
    footer: `<button class="btn" onclick="closeModal()">Fermer</button>`,
  });
  document.querySelectorAll("[data-reprint]").forEach((b) => b.onclick = async () => {
    try { const tk = await api(`/commercial/pos/ticket/${b.dataset.reprint}`); closeModal(); posTicket(tk); }
    catch (e) { toast(e.message, "ko"); }
  });
  document.querySelectorAll("[data-retour]").forEach((b) => b.onclick = async () => {
    try { const tk = await api(`/commercial/pos/ticket/${b.dataset.retour}`); closeModal(); posRetourModal(tk); }
    catch (e) { toast(e.message, "ko"); }
  });
}

function posRetourModal(tk) {
  const clientReel = tk.client && tk.client.code !== "COMPTANT";
  modal({
    title: `Retour sur ${tk.numero}`,
    body: `<table><thead><tr><th>Article</th><th class="right">Vendu</th><th class="right">Déjà retourné</th><th class="right">À retourner</th></tr></thead><tbody>
      ${tk.lignes.map((l) => { const max = Math.max(0, l.qte - (l.deja_retourne || 0));
        return `<tr><td>${esc(l.designation)}</td><td class="right">${fmtNum(l.qte)}</td>
        <td class="right">${fmtNum(l.deja_retourne || 0)}</td>
        <td class="right"><input class="form-input right pr-qte" data-l="${l.id}" type="number" step="any" min="0" max="${max}" value="0" style="width:70px" ${max ? "" : "disabled"} /></td></tr>`; }).join("")}
      </tbody></table>
      <div style="display:flex;gap:10px;margin-top:12px;align-items:center">
        <label class="form-label" style="margin:0">Remboursement</label>
        <select id="pr-mode" class="form-select" style="width:auto">
          <option value="espece">Espèces (sortie de caisse)</option>
          <option value="credit" ${clientReel ? "" : "disabled"}>Avoir sur compte client${clientReel ? "" : " (client comptant)"}</option></select>
        <input id="pr-motif" class="form-input" placeholder="Motif du retour…" style="flex:1" /></div>`,
    footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="pr-ok"><i class="ti ti-arrow-back-up"></i> Valider le retour</button>`,
  });
  $("#pr-ok").onclick = async () => {
    const lignes = [...document.querySelectorAll(".pr-qte")].map((i) => ({ ligne_id: i.dataset.l, qte: +i.value || 0 })).filter((l) => l.qte > 0);
    if (!lignes.length) { toast("Indiquez au moins une quantité à retourner.", "ko"); return; }
    try {
      const av = await api(`/commercial/pos/retour?societe_id=${currentSocieteId}`, { method: "POST", body: {
        facture_id: tk.id, mode: $("#pr-mode").value, motif: $("#pr-motif").value || null, lignes } });
      closeModal(); toast(`Avoir ${av.numero} créé.`, "ok"); posTicket(av); await posLoad(); posRender();
    } catch (e) { toast(e.message, "ko"); }
  };
}

// ── Rapport « X » du jour ────────────────────────────────────────────
async function posRapport() {
  let r;
  try { r = await api(`/commercial/pos/rapport?societe_id=${currentSocieteId}&point_vente_id=${posPvId}`); }
  catch (e) { toast(e.message, "ko"); return; }
  const pv = posPvs.find((p) => p.id === posPvId);
  const modes = Object.entries(r.par_mode).map(([m, v]) => `<tr><td>${POS_MODES[m] || m}</td>
    <td class="right">${v.nb}</td><td class="right">${fmtNum(v.usd)} $${v.cdf ? `<div class="muted" style="font-size:11px">dont ${fmtCDF(v.cdf)}</div>` : ""}</td></tr>`).join("");
  modal({
    title: `Rapport du jour — ${esc(pv ? pv.libelle : "")}`,
    body: `<div class="pos-kpis">
        <div><span>${r.nb_tickets}</span>tickets</div>
        <div><span>${fmtNum(r.net_ttc)} $</span>net encaissé${r.net_ttc_cdf ? `<small>≈ ${fmtCDF(r.net_ttc_cdf)}</small>` : ""}</div>
        <div><span>${fmtNum(r.panier_moyen)} $</span>panier moyen</div>
        <div><span>${fmtNum(r.marge)} $</span>marge</div></div>
      <table style="margin-top:10px"><tbody>
        <tr><td>Ventes TTC</td><td class="right">${fmtNum(r.ttc)} $</td></tr>
        ${r.remises ? `<tr><td>Remises accordées</td><td class="right">−${fmtNum(r.remises)} $</td></tr>` : ""}
        ${r.retours_ttc ? `<tr><td>Retours (${r.nb_retours})</td><td class="right">−${fmtNum(r.retours_ttc)} $</td></tr>` : ""}
        ${r.monnaie_rendue ? `<tr><td class="muted">Monnaie rendue</td><td class="right muted">${fmtNum(r.monnaie_rendue)} $</td></tr>` : ""}
        <tr><td>TVA collectée</td><td class="right">${fmtNum(r.tva)} $</td></tr></tbody></table>
      ${modes ? `<div class="muted" style="font-size:12px;margin-top:12px">Encaissements par mode</div>
        <table><thead><tr><th>Mode</th><th class="right">Nb</th><th class="right">Montant</th></tr></thead><tbody>${modes}</tbody></table>` : ""}
      ${r.palmares.length ? `<div class="muted" style="font-size:12px;margin-top:12px">Meilleures ventes</div>
        <table><tbody>${r.palmares.map((a) => `<tr><td>${esc(a.designation)}</td><td class="right">${fmtNum(a.qte)}</td><td class="right">${fmtNum(a.ht)} $</td></tr>`).join("")}</tbody></table>` : ""}
      ${r.par_vendeur.length > 1 ? `<div class="muted" style="font-size:12px;margin-top:12px">Par vendeur</div>
        <table><tbody>${r.par_vendeur.map((v) => `<tr><td>${esc(v.vendeur)}</td><td class="right">${v.nb} tickets</td><td class="right">${fmtNum(v.ttc)} $</td></tr>`).join("")}</tbody></table>` : ""}`,
    footer: `<button class="btn" onclick="closeModal()">Fermer</button><button class="btn btn-primary" id="rx-print"><i class="ti ti-printer"></i> Imprimer</button>`,
  });
  $("#rx-print").onclick = () => {
    const w = window.open("", "_blank", "width=380,height=640");
    if(!w){toast("Autorisez la fenêtre d’impression du ticket puis réessayez.","ko");return;}
    w.document.write(`<html><head><meta charset="utf-8"><title>Rapport ${r.jour}</title><style>@page{size:80mm auto;margin:3mm}body{font-family:Arial,sans-serif;padding:8px;font-size:11px;line-height:1.4;color:#111;max-width:74mm;margin:0 auto}h3{text-align:center;margin:0}.c{text-align:center;color:#555}table{width:100%;border-collapse:collapse;margin:6px 0}td{padding:2px 0}td:last-child{text-align:right}.tot{border-top:1px dashed #000;margin-top:6px;padding-top:6px;font-weight:bold}</style></head><body>
      <h3>${esc(pv ? pv.libelle : "")}</h3><div class="c">Rapport du ${r.jour}</div>
      <table><tr><td>Tickets</td><td>${r.nb_tickets}</td></tr>
      <tr><td>Ventes TTC</td><td>${fmtNum(r.ttc)} $</td></tr>
      ${r.remises ? `<tr><td>Remises</td><td>-${fmtNum(r.remises)} $</td></tr>` : ""}
      ${r.retours_ttc ? `<tr><td>Retours</td><td>-${fmtNum(r.retours_ttc)} $</td></tr>` : ""}
      <tr><td>TVA</td><td>${fmtNum(r.tva)} $</td></tr>
      <tr class="tot"><td>NET</td><td>${fmtNum(r.net_ttc)} $</td></tr></table>
      ${Object.keys(r.par_mode).length ? `<div class="c">— Par mode —</div><table>${Object.entries(r.par_mode).map(([m, v]) => `<tr><td>${POS_MODES[m] || m}</td><td>${fmtNum(v.usd)} $</td></tr>`).join("")}</table>` : ""}
      <div class="c" style="margin-top:8px">Marge : ${fmtNum(r.marge)} $ — Panier moyen : ${fmtNum(r.panier_moyen)} $</div></body></html>`);
    w.document.close(); w.focus(); setTimeout(() => w.print(), 250);
  };
}

// ── Détail d'une réquisition (depuis le Centre d'approbation) ─────────
async function detailsRequisition(id) {
  let d; try { d = await api(`/requisitions/${id}/detail`); } catch (e) { toast(e.message, "ko"); return; }
  const lignes = d.lignes.map((l) => `<tr><td>${esc(l.description)}</td><td class="right">${fmtNum(l.quantite)}</td>
    <td class="right">${fmtNum(l.prix_unitaire)}</td><td class="right">${fmtNum(l.montant)} ${esc(d.devise)}</td></tr>`).join("");
  modal({
    title: `Réquisition ${d.numero}`,
    body: `<div style="margin-bottom:10px">${pill(d.statut)}
      <span class="tag">${d.mode_decaissement === "paiement_direct" ? "paiement direct" : "avance à justifier"}</span>
      ${d.priorite !== "normal" ? `<span class="tag ${d.priorite}">${d.priorite.replace("_", " ")}</span>` : ""}</div>
      <p><b>Objet :</b> ${esc(d.objet)}</p>
      ${d.justification ? `<p><b>Motif :</b> ${esc(d.justification)}</p>` : ""}
      <p class="muted">Initié par ${esc(d.initiateur || "")} · ${d.date || ""}</p>
      <p class="muted">${esc(d.progression.label)}</p>
      <table><thead><tr><th>Description</th><th class="right">Qté</th><th class="right">P.U.</th><th class="right">Montant</th></tr></thead><tbody>${lignes}</tbody></table>
      <div class="total-bar"><span class="lbl">Total</span><span class="val">${fmtUSD(d.montant_total_usd)}</span></div>
      ${d.nb_pieces_jointes ? `<div class="meta" style="margin-top:8px"><i class="ti ti-paperclip"></i> ${d.nb_pieces_jointes} pièce(s) jointe(s)</div>` : ""}`,
    footer: `<button class="btn" onclick="closeModal()">Fermer</button><button class="btn" id="det-pj"><i class="ti ti-paperclip"></i> Pièces jointes</button>`,
  });
  $("#det-pj").onclick = () => piecesModal("requisition", id, `Pièces jointes — ${d.numero}`);
}
window.detailsRequisition = detailsRequisition;

// ── Bon de sortie de caisse / OP imprimable ──────────────────────────
async function printBonSortie(ordreId) {
  let d; try { d = await api(`/ordres-depense/${ordreId}/bon-sortie`); } catch (e) { toast(e.message, "ko"); return; }
  const w = Editions.fenetre(`Bon de sortie · ${d.bon_numero}`);
  w.document.write(`<html><head><meta charset="utf-8"><title>${esc(d.bon_numero)}</title><style>
    body{font-family:Arial,sans-serif;padding:34px;color:#222}h1{font-size:18px;color:#3C3489;margin:0 0 4px}
    .sub{color:#666;margin-bottom:18px}.row{display:flex;justify-content:space-between;margin:5px 0;border-bottom:1px solid #eee;padding-bottom:5px}
    .lbl{color:#777}.montant{font-size:22px;font-weight:800;margin:18px 0;color:#3C3489}
    .sign{margin-top:60px;display:flex;justify-content:space-between}.sign div{border-top:1px solid #999;width:42%;text-align:center;padding-top:6px;font-size:12px;color:#666}</style></head><body>
    <h1>${d.mode === "banque" ? "ORDRE DE PAIEMENT / CHÈQUE" : "BON DE SORTIE DE CAISSE"}</h1>
    <div class="sub">${esc(d.societe)}</div>
    <div class="row"><span class="lbl">N° du bon</span><span>${esc(d.bon_numero)}</span></div>
    <div class="row"><span class="lbl">Réf. ordre de dépense</span><span>${esc(d.ordre_numero)}</span></div>
    <div class="row"><span class="lbl">Date</span><span>${(d.date || "").slice(0, 10)}</span></div>
    <div class="row"><span class="lbl">Bénéficiaire</span><span>${esc(d.beneficiaire || "")}</span></div>
    <div class="row"><span class="lbl">Moyen</span><span>${d.mode === "banque" ? "Banque" : "Caisse"} — ${esc(d.moyen || "")}</span></div>
    ${d.reference_paiement ? `<div class="row"><span class="lbl">Réf. OP / chèque</span><span>${esc(d.reference_paiement)}</span></div>` : ""}
    <div class="row"><span class="lbl">Motif</span><span>${esc(d.motif || "")}</span></div>
    <div class="montant">Montant : ${fmtNum(d.montant)} ${esc(d.devise)} &nbsp;(${fmtUSD(d.montant_usd)})</div>
    <div class="sign"><div>Bénéficiaire</div><div>${d.mode === "banque" ? "Comptable" : "Caissier"}<br>${esc(d.executant || "")}</div></div>
    </body></html>`);
  w.document.close(); w.focus(); setTimeout(() => w.print(), 350);
}
window.printBonSortie = printBonSortie;

// Bon de caisse générique (tout mouvement : encaissement / sortie / transfert)
async function printBonCaisse(mvtId) {
  let d; try { d = await api(`/caisse/mouvement/${mvtId}/bon`); } catch (e) { toast(e.message, "ko"); return; }
  const legs = d.legs.map((l) => `<div class="row"><span class="lbl">Montant</span><span>${fmtNum(l.montant)} ${esc(l.devise)}${l.billetage ? " (billetage détaillé)" : ""}</span></div>`).join("");
  let lien = "";
  if (d.lien && d.lien.type === "decaissement")
    lien = `<div class="row"><span class="lbl">Réquisition</span><span>${esc(d.lien.requisition || "—")}${d.lien.objet ? " — " + esc(d.lien.objet) : ""}</span></div>
            <div class="row"><span class="lbl">Ordre de dépense</span><span>${esc(d.lien.ordre || "")}</span></div>`;
  else if (d.lien && d.lien.type === "transfert")
    lien = `<div class="row"><span class="lbl">Transfert</span><span>${esc(d.lien.transfert || "")}</span></div>`;
  else if (d.reference)
    lien = `<div class="row"><span class="lbl">Réf. réquisition</span><span>${esc(d.reference)}</span></div>`;
  const w = Editions.fenetre(`Pièce de caisse · ${d.numero || ""}`);
  w.document.write(`<html><head><meta charset="utf-8"><title>${esc(d.numero || "Bon de caisse")}</title><style>
    body{font-family:Arial,sans-serif;padding:34px;color:#222}h1{font-size:18px;color:#3C3489;margin:0 0 4px}
    .sub{color:#666;margin-bottom:18px}.row{display:flex;justify-content:space-between;margin:5px 0;border-bottom:1px solid #eee;padding-bottom:5px}
    .lbl{color:#777}.sign{margin-top:60px;display:flex;justify-content:space-between}.sign div{border-top:1px solid #999;width:42%;text-align:center;padding-top:6px;font-size:12px;color:#666}</style></head><body>
    <h1>${d.sens === "entree" ? "BON D'ENTRÉE DE CAISSE" : "BON DE SORTIE DE CAISSE"}</h1>
    <div class="sub">${esc(d.societe)} — ${esc(d.caisse)}</div>
    <div class="row"><span class="lbl">N° du bon</span><span>${esc(d.numero || "")}</span></div>
    <div class="row"><span class="lbl">Date</span><span>${d.date ? new Date(d.date).toLocaleString("fr-FR") : ""}</span></div>
    <div class="row"><span class="lbl">Nature</span><span>${esc(d.nature || "")}</span></div>
    <div class="row"><span class="lbl">${d.sens === "entree" ? "Provenance" : "Bénéficiaire"}</span><span>${esc(d.tiers || "—")}</span></div>
    ${lien}${legs}
    <div class="sign"><div>${d.sens === "entree" ? "Remettant" : "Bénéficiaire"}</div><div>Caissier<br>${esc(d.caissier || "")}</div></div>
    </body></html>`);
  w.document.close(); w.focus(); setTimeout(() => w.print(), 350);
}
window.printBonCaisse = printBonCaisse;

// ── Paramétrage (#6) ─────────────────────────────────────────────────
let cfgScope = "";        // "" = Groupe (societe_id null), sinon societe_id
let cfgTab = "grille";
let cfgSocietes = null, cfgRoles = null;
const fmtRange = (min, max) => max == null
  ? (min <= 0 ? "Tous montants" : `> ${fmtNum(min)}`)
  : (min <= 0 ? `≤ ${fmtNum(max)}` : `${fmtNum(min)} – ${fmtNum(max)}`);

RENDER.config = async () => {
  const el = $("#view-config");
  if (!cfgSocietes) cfgSocietes = await api("/config/societes");
  if (!cfgRoles) cfgRoles = await api("/config/roles");
  el.innerHTML = `
    <div class="section-hdr">
      <div class="section-title"><i class="ti ti-settings"></i> Configuration</div>
      <div style="margin-left:auto;display:flex;gap:8px;align-items:center">
        <span class="muted">Périmètre</span>
        <select id="cfg-scope" class="form-select" style="width:auto">
          ${cfgSocietes.map((s) => `<option value="${s.id || ""}">${esc(s.nom)}</option>`).join("")}
        </select>
      </div>
    </div>
    <nav class="tabs" style="margin-bottom:16px">
      <button data-ctab="grille">Grille de validation</button>
      <button data-ctab="seuils">Seuils &amp; délais</button>
      <button data-ctab="intervenants">Intervenants</button>
    </nav>
    <div id="cfg-body"></div>`;
  $("#cfg-scope").value = cfgScope;
  $("#cfg-scope").onchange = (e) => { cfgScope = e.target.value; cfgRender(); };
  el.querySelectorAll("[data-ctab]").forEach((b) => {
    b.classList.toggle("active", b.dataset.ctab === cfgTab);
    b.onclick = () => { cfgTab = b.dataset.ctab; el.querySelectorAll("[data-ctab]").forEach((x) => x.classList.toggle("active", x === b)); cfgRender(); };
  });
  cfgRender();
};
function cfgRender() {
  const body = $("#cfg-body");
  body.innerHTML = `<div class="muted">Chargement…</div>`;
  if (cfgTab === "grille") return cfgGrille(body);
  if (cfgTab === "seuils") return cfgSeuils(body);
  return cfgIntervenants(body);
}

// Grille de validation
async function cfgGrille(body) {
  const q = cfgScope ? `?societe_id=${cfgScope}` : "";
  const g = await api(`/config/paliers${q}`);
  const bloc = (titre, niveau, rows) => `
    <div class="card"><div class="card-hdr">
      <div class="card-hdr-title">${titre}</div>
      <button class="btn btn-sm btn-primary" data-add="${niveau}"><i class="ti ti-plus"></i> Ajouter un palier</button></div>
      <div class="card-body">${rows.length ? `<table><thead><tr><th>Montant (USD)</th><th>Validateurs requis</th><th></th></tr></thead><tbody>
        ${rows.map((p) => `<tr><td>${fmtRange(p.montant_min_usd, p.montant_max_usd)}</td>
          <td>${p.approbateurs.map((a) => `<span class="tag" style="background:var(--pl);color:var(--p)">${a.role_code}${a.mode === "seul" ? " (seul)" : ""}</span>`).join(" ") || '<span class="muted">aucun</span>'}</td>
          <td class="right" style="white-space:nowrap">
            <button class="btn btn-sm" data-edit='${esc(JSON.stringify({ id: p.id, niveau, min: p.montant_min_usd, max: p.montant_max_usd, libelle: p.libelle, approbateurs: p.approbateurs }))}'><i class="ti ti-pencil"></i></button>
            <button class="btn btn-sm btn-danger" data-del="${p.id}">×</button></td></tr>`).join("")}
      </tbody></table>` : `<div class="muted">Aucun palier${cfgScope ? " spécifique — la règle <b>Groupe</b> s'applique à cette société." : "."}</div>`}</div></div>`;
  body.innerHTML = bloc("Niveau 1 — Validation de la demande", "demande", g.demande) +
                   bloc("Niveau 2 — Validation de la sortie de fonds", "sortie_fonds", g.sortie_fonds);
  body.querySelectorAll("[data-add]").forEach((b) => b.onclick = () => palierModal(b.dataset.add, null));
  body.querySelectorAll("[data-edit]").forEach((b) => b.onclick = () => palierModal(JSON.parse(b.dataset.edit).niveau, JSON.parse(b.dataset.edit)));
  body.querySelectorAll("[data-del]").forEach((b) => b.onclick = async () => {
    if (!confirm("Supprimer ce palier ?")) return;
    try { await api(`/config/paliers/${b.dataset.del}`, { method: "DELETE" }); toast("Palier supprimé.", "ok"); cfgGrille($("#cfg-body")); }
    catch (e) { toast(e.message, "ko"); }
  });
}
let palAppros = [];
function palierModal(niveau, p) {
  palAppros = p ? p.approbateurs.map((a) => ({ ...a })) : [{ role_code: cfgRoles[0]?.code, mode: "conjoint" }];
  const lvl = niveau === "demande" ? "Niveau 1 — Demande" : "Niveau 2 — Sortie de fonds";
  modal({
    title: (p ? "Modifier" : "Ajouter") + ` un palier — ${lvl}`,
    body: `<div class="form-row"><div class="form-group"><label class="form-label">Montant min (USD)</label>
        <input id="pl-min" class="form-input" type="number" step="any" value="${p ? p.min : 0}" /></div>
      <div class="form-group"><label class="form-label">Montant max (USD) — vide = illimité</label>
        <input id="pl-max" class="form-input" type="number" step="any" value="${p && p.max != null ? p.max : ""}" /></div></div>
      <div class="form-group"><label class="form-label">Libellé (optionnel)</label><input id="pl-lib" class="form-input" value="${p ? esc(p.libelle || "") : ""}" /></div>
      <label class="form-label">Validateurs requis</label><div id="pl-appros"></div>
      <button class="btn btn-sm" id="pl-add-appro" style="margin-top:6px"><i class="ti ti-plus"></i> Ajouter un validateur</button>`,
    footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="pl-ok">Enregistrer</button>`,
  });
  const drawAppros = () => {
    $("#pl-appros").innerHTML = palAppros.map((a, i) => `<div style="display:flex;gap:8px;margin-bottom:6px">
      <select class="form-select" data-i="${i}" data-f="role_code">${cfgRoles.map((r) => `<option value="${r.code}" ${r.code === a.role_code ? "selected" : ""}>${esc(r.libelle)}</option>`).join("")}</select>
      <select class="form-select" data-i="${i}" data-f="mode" style="width:140px"><option value="conjoint" ${a.mode === "conjoint" ? "selected" : ""}>Conjoint</option><option value="seul" ${a.mode === "seul" ? "selected" : ""}>Seul</option></select>
      <button class="btn btn-sm" data-rm="${i}">×</button></div>`).join("");
    $("#pl-appros").querySelectorAll("select").forEach((s) => s.onchange = () => { palAppros[s.dataset.i][s.dataset.f] = s.value; });
    $("#pl-appros").querySelectorAll("[data-rm]").forEach((b) => b.onclick = () => { palAppros.splice(b.dataset.rm, 1); drawAppros(); });
  };
  drawAppros();
  $("#pl-add-appro").onclick = () => { palAppros.push({ role_code: cfgRoles[0]?.code, mode: "conjoint" }); drawAppros(); };
  $("#pl-ok").onclick = async () => {
    const payload = {
      societe_id: cfgScope || null, niveau,
      montant_min_usd: parseFloat($("#pl-min").value || 0),
      montant_max_usd: $("#pl-max").value === "" ? null : parseFloat($("#pl-max").value),
      libelle: $("#pl-lib").value || null, approbateurs: palAppros.filter((a) => a.role_code),
    };
    try {
      if (p) await api(`/config/paliers/${p.id}`, { method: "PUT", body: payload });
      else await api("/config/paliers", { method: "POST", body: payload });
      closeModal(); toast("Palier enregistré.", "ok"); cfgGrille($("#cfg-body"));
    } catch (e) { toast(e.message, "ko"); }
  };
}

// Seuils & délais
async function cfgSeuils(body) {
  const q = cfgScope ? `?societe_id=${cfgScope}` : "";
  const params = await api(`/config/parametres${q}`);
  if (!params.length) { body.innerHTML = `<div class="empty"><i class="ti ti-adjustments"></i>Les seuils sont définis au niveau <b>Groupe</b>. Choisissez « Groupe (par défaut) » dans le périmètre.</div>`; return; }
  body.innerHTML = `<div class="card"><table><thead><tr><th>Paramètre</th><th>Description</th><th style="width:160px">Valeur</th><th></th></tr></thead><tbody>
    ${params.map((p) => `<tr><td class="num-cell" style="color:var(--text)">${esc(p.cle)}</td><td class="muted">${esc(p.description || "")}</td>
      <td><input class="form-input" id="prm-${p.id}" value="${esc(p.valeur)}" /></td>
      <td><button class="btn btn-sm btn-primary" data-save="${p.id}">Enregistrer</button></td></tr>`).join("")}
  </tbody></table></div>`;
  body.querySelectorAll("[data-save]").forEach((b) => b.onclick = async () => {
    try { const r = await api(`/config/parametres/${b.dataset.save}`, { method: "PUT", body: { valeur: $("#prm-" + b.dataset.save).value } }); toast(`Enregistré (${r.valeur}).`, "ok"); }
    catch (e) { toast(e.message, "ko"); }
  });
}

// Intervenants
async function cfgIntervenants(body) {
  if (!cfgScope) { body.innerHTML = `<div class="empty"><i class="ti ti-users"></i>Choisissez une <b>société</b> dans le périmètre pour gérer ses intervenants.</div>`; return; }
  const list = await api(`/config/intervenants?societe_id=${cfgScope}`);
  body.innerHTML = `<div class="card"><div class="card-hdr"><div class="card-hdr-title">Intervenants de la société</div>
    <button class="btn btn-sm btn-primary" id="int-add"><i class="ti ti-user-plus"></i> Ajouter</button></div>
    <div class="card-body">${list.length ? `<table><thead><tr><th>Nom</th><th>Email</th><th>Rôle</th><th></th></tr></thead><tbody>
      ${list.map((i) => `<tr><td>${esc(i.nom)}</td><td class="muted">${esc(i.email)}</td><td><span class="tag" style="background:var(--pl);color:var(--p)">${esc(i.role_libelle)}</span></td>
        <td class="right"><button class="btn btn-sm btn-danger" data-rm='${esc(JSON.stringify({ u: i.utilisateur_id, r: i.role_code }))}'>Retirer</button></td></tr>`).join("")}
    </tbody></table>` : `<div class="muted">Aucun intervenant.</div>`}</div></div>`;
  $("#int-add").onclick = async () => {
    const users = await api("/config/utilisateurs");
    modal({
      title: "Ajouter un intervenant",
      body: `<div class="form-group"><label class="form-label">Utilisateur</label>
        <select id="int-u" class="form-select">${users.map((u) => `<option value="${u.id}">${esc(u.nom)} — ${esc(u.email)}</option>`).join("")}</select></div>
        <div class="form-group"><label class="form-label">Rôle</label>
        <select id="int-r" class="form-select">${cfgRoles.map((r) => `<option value="${r.code}">${esc(r.libelle)}</option>`).join("")}</select></div>`,
      footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="int-ok">Ajouter</button>`,
    });
    $("#int-ok").onclick = async () => {
      try {
        await api("/config/affectations", { method: "POST", body: { utilisateur_id: $("#int-u").value, societe_id: cfgScope, role_code: $("#int-r").value } });
        closeModal(); toast("Intervenant ajouté.", "ok"); cfgIntervenants($("#cfg-body"));
      } catch (e) { toast(e.message, "ko"); }
    };
  };
  body.querySelectorAll("[data-rm]").forEach((b) => b.onclick = async () => {
    const { u, r } = JSON.parse(b.dataset.rm);
    if (!confirm("Retirer cette affectation ?")) return;
    try { await api("/config/affectations", { method: "DELETE", body: { utilisateur_id: u, societe_id: cfgScope, role_code: r } }); toast("Retiré.", "ok"); cfgIntervenants($("#cfg-body")); }
    catch (e) { toast(e.message, "ko"); }
  });
}

// ── Démarrage ────────────────────────────────────────────────────────
// ═══ Module Ventes — devis → commande → livraison → facture → règlement ═══
const DEVIS_ST = {
  brouillon: ["Brouillon", "st-brouillon"], envoye: ["Envoyé", "st-envoye"],
  confirme: ["Commande", "st-confirme"], annule: ["Annulé", "st-annule"],
};
const REGL_ST = { payee: ["Payée", "st-payee"], partielle: ["Partielle", "st-partielle"], due: ["À encaisser", "st-due"] };
const LIVR_ST = { a_livrer: ["À livrer", "st-due"], partielle: ["Partiellement livrée", "st-partielle"],
                  livree: ["Livrée", "st-payee"], sans_objet: ["", ""] };
let devisFiltre = "";

RENDER.devis = async () => {
  const el = $("#view-devis");
  el.innerHTML = `<div class="muted">Chargement…</div>`;
  const ds = await api(`/ventes/devis?societe_id=${currentSocieteId}${devisFiltre ? `&statut=${devisFiltre}` : ""}`).catch(() => []);
  const seg = `<div class="seg">
    ${[["", "Tous"], ["brouillon", "Brouillons"], ["envoye", "Envoyés"], ["confirme", "Commandes"], ["annule", "Annulés"]]
      .map(([v, l]) => `<button data-df="${v}" class="${devisFiltre === v ? "on" : ""}">${l}</button>`).join("")}</div>`;
  el.innerHTML = `<div class="section-hdr" style="margin-bottom:12px">
      <div class="section-title"><i class="ti ti-file-description"></i> Devis & commandes clients</div>
      <div style="margin-left:auto;display:flex;gap:10px;align-items:center">${seg}
        <button class="btn btn-sm btn-primary" id="dv-new"><i class="ti ti-plus"></i> Nouveau devis</button></div></div>
    ${!ds.length ? `<div class="empty"><i class="ti ti-file-description"></i>Aucun devis${devisFiltre ? " dans ce filtre" : ""}. Créez votre premier devis client.</div>`
      : `<div class="card"><div class="card-body"><table><thead><tr>
          <th>N°</th><th>Client</th><th>Date</th><th>Validité</th><th class="right">Total TTC</th>
          <th>Statut</th><th>Livraison</th><th style="width:130px">Avancement</th><th></th></tr></thead><tbody>
        ${ds.map((d) => {
          const [sl, sc] = DEVIS_ST[d.statut] || [d.statut, ""];
          const [ll, lc] = d.statut === "confirme" ? (LIVR_ST[d.statut_livraison] || ["", ""]) : ["", ""];
          return `<tr style="cursor:pointer" data-dv="${d.id}">
            <td class="num-cell">${esc(d.numero)}${d.commande_origine ? ` <span class="tag" title="Commande intersociété ${esc(d.commande_origine)} reçue — à confirmer">PO reçue</span>` : ""}</td>
            <td>${esc(d.client || "")}</td><td>${d.date}</td>
            <td>${d.validite ? `${d.validite}${d.expire ? ' <span class="tag urgent">expiré</span>' : ""}` : "—"}</td>
            <td class="right" style="font-weight:700">${fmtNum(d.total_ttc)} $</td>
            <td><span class="pill ${sc}">${sl}</span></td>
            <td>${ll ? `<span class="pill ${lc}">${ll}</span>` : "—"}</td>
            <td>${d.statut === "confirme" ? `<div class="mini-prog" title="Livré ${d.pct_livre}% · Facturé ${d.pct_facture}%">
              <i style="width:${d.pct_livre}%"></i><em style="width:${d.pct_facture}%"></em></div>` : "—"}</td>
            <td class="right"><i class="ti ti-chevron-right muted"></i></td></tr>`;
        }).join("")}</tbody></table></div></div>`}`;
  el.querySelectorAll("[data-df]").forEach((b) => b.onclick = () => { devisFiltre = b.dataset.df; RENDER.devis(); });
  $("#dv-new").onclick = () => devisModal(null);
  el.querySelectorAll("[data-dv]").forEach((r) => r.onclick = () => devisDetail(r.dataset.dv));
  filtreTable(el);
};

// ── Formulaire devis (création / modification) ───────────────────────
async function devisModal(existant) {
  const [articles, clients] = await Promise.all([
    api(`/commercial/articles?societe_id=${currentSocieteId}`).catch(() => []),
    api(`/commercial/tiers?societe_id=${currentSocieteId}&type=client`).catch(() => []),
  ]);
  // devis client : seuls les articles de vente (pas les matières premières)
  const arts = articles.filter((a) => a.actif && (a.nature || "marchandise") === "marchandise");
  const byId = Object.fromEntries(arts.map((a) => [a.id, a]));
  let artOpts = `<option value="">(ligne libre)</option>` + arts.map((a) => `<option value="${a.id}">${esc(a.code)} — ${esc(a.designation)}</option>`).join("");
  const cliOpts = clients.filter((c) => c.code !== "COMPTANT")
    .map((c) => `<option value="${c.id}">${esc(Catalogue.label(c))}</option>`).join("");
  const ligneHTML = (l) => `<tr class="dl-row">
    <td><select class="form-select dl-art" style="min-width:140px">${artOpts}</select></td>
    <td><input class="form-input dl-des" placeholder="désignation" value="${l ? esc(l.designation) : ""}" /></td>
    <td><input class="form-input dl-qte right" type="number" step="any" value="${l ? l.qte : 1}" style="width:70px" /></td>
    <td><input class="form-input dl-pu right" type="number" step="any" value="${l ? l.prix_unitaire : 0}" style="width:88px" /></td>
    <td><input class="form-input dl-rem right" type="number" step="any" min="0" max="100" value="0" style="width:60px" /></td>
    <td><input class="form-input dl-tva right" type="number" step="any" value="${l ? l.taux_tva : 16}" style="width:56px" /></td>
    <td class="right dl-ht" style="white-space:nowrap;font-weight:600">0,00</td>
    <td><button class="btn btn-sm dl-del"><i class="ti ti-trash"></i></button></td></tr>`;
  modal({
    title: existant ? `Modifier ${existant.numero}` : "Nouveau devis client",
    wide: true,
    body: `<div class="form-row">
        <div class="form-group"><label class="form-label">Client</label><select id="dv-cli" class="form-select">${cliOpts || '<option value="">(aucun client — créez-en un)</option>'}</select></div>
        <div class="form-group"><label class="form-label">Date</label><input id="dv-date" class="form-input" type="date" value="${existant ? existant.date : isoLocal(new Date())}" /></div>
        <div class="form-group"><label class="form-label">Validité (offre valable jusqu'au)</label><input id="dv-val" class="form-input" type="date" value="${existant && existant.validite ? existant.validite : ""}" /></div></div>
      <table class="lignes-table"><thead><tr><th>Article</th><th>Désignation</th><th class="right">Qté</th><th class="right">P.U. $</th><th class="right">Rem.%</th><th class="right">TVA%</th><th class="right">HT net</th><th></th></tr></thead>
        <tbody id="dv-lignes"></tbody></table>
      <button class="btn btn-sm" id="dv-addl" style="margin-top:8px"><i class="ti ti-plus"></i> Ajouter une ligne</button>
      <div class="form-row" style="margin-top:12px">
        <div class="form-group"><label class="form-label">Remise globale %</label><input id="dv-remg" class="form-input right" type="number" step="any" min="0" max="100" value="${existant ? existant.remise_globale_pct : 0}" style="width:90px" /></div>
        <div class="form-group" style="flex:2"><label class="form-label">Conditions (paiement, livraison…)</label><input id="dv-cond" class="form-input" placeholder="ex. Paiement à 30 jours — livraison sous 5 jours" value="${existant && existant.conditions ? esc(existant.conditions) : ""}" /></div></div>
      <div class="form-group"><label class="form-label">Note interne</label><input id="dv-note" class="form-input" value="${existant && existant.note ? esc(existant.note) : ""}" /></div>
      <div class="total-bar"><span class="lbl" id="dv-tot-sub">HT 0,00 · TVA 0,00</span><span class="val" id="dv-tot">0,00 $</span></div>`,
    footer: `<button class="btn" onclick="closeModal()">Annuler</button>
      <button class="btn btn-primary" id="dv-ok"><i class="ti ti-check"></i> ${existant ? "Enregistrer" : "Créer le devis"}</button>`,
  });
  const tbody = $("#dv-lignes");
  const recalc = () => {
    const g = Math.min(Math.max(+$("#dv-remg").value || 0, 0), 100);
    let ht = 0, tva = 0, brut = 0;
    tbody.querySelectorAll(".dl-row").forEach((tr) => {
      const q = +tr.querySelector(".dl-qte").value || 0, pu = +tr.querySelector(".dl-pu").value || 0;
      const r = Math.min(Math.max(+tr.querySelector(".dl-rem").value || 0, 0), 100);
      const t = +tr.querySelector(".dl-tva").value || 0;
      const b = Math.round(q * pu * 100) / 100;
      const eff = 1 - (1 - r / 100) * (1 - g / 100);
      const h = Math.round(b * (1 - eff) * 100) / 100;
      tr.querySelector(".dl-ht").textContent = fmtNum(h);
      brut += b; ht += h; tva += Math.round(h * t) / 100;
    });
    ht = Math.round(ht * 100) / 100; tva = Math.round(tva * 100) / 100;
    $("#dv-tot-sub").textContent = `HT ${fmtNum(ht)} · TVA ${fmtNum(tva)}${brut - ht > 0.004 ? ` · remises −${fmtNum(Math.round((brut - ht) * 100) / 100)}` : ""}`;
    $("#dv-tot").textContent = fmtNum(Math.round((ht + tva) * 100) / 100) + " $";
  };
  const wireRow = (tr) => {
    tr.querySelector(".dl-art").onchange = (e) => {
      const a = byId[e.target.value];
      if (a) {
        tr.querySelector(".dl-des").value = a.designation;
        tr.querySelector(".dl-pu").value = a.prix_vente;
        tr.querySelector(".dl-tva").value = a.assujetti_tva ? a.taux_tva : 0;
      }
      recalc();
    };
    Catalogue.bind(tr.querySelector('.dl-art'), {kind:'article', nature:'marchandise', natureLocked:true,
      create:has('DFI','COMPTABLE'), accept:a=>{byId[a.id]=a;if(!arts.some(x=>x.id===a.id))arts.push(a);if(!artOpts.includes(`value="${a.id}"`))artOpts+=`<option value="${a.id}">${esc(a.code)} — ${esc(a.designation)}</option>`;}});
    tr.querySelectorAll("input").forEach((i) => i.oninput = recalc);
    tr.querySelector(".dl-del").onclick = () => { tr.remove(); recalc(); };
  };
  const addRow = (l) => { tbody.insertAdjacentHTML("beforeend", ligneHTML(l)); const tr = tbody.lastElementChild; wireRow(tr); if (l && l.article_id) tr.querySelector(".dl-art").value = l.article_id; if (l) tr.querySelector(".dl-rem").value = 0; return tr; };
  if (existant) {
    $("#dv-cli").value = existant.tiers_id;
    existant.lignes.forEach((l) => { const tr = addRow(l); tr.querySelector(".dl-rem").value = 0; tr.querySelector(".dl-pu").value = l.prix_unitaire; tr.querySelector(".dl-rem").value = l.remise_pct && existant.remise_globale_pct ? Math.round((1 - (1 - l.remise_pct / 100) / (1 - existant.remise_globale_pct / 100)) * 10000) / 100 : l.remise_pct; });
  } else addRow(null);
  $("#dv-addl").onclick = () => addRow(null);
  $("#dv-remg").oninput = recalc;
  recalc();
  $("#dv-ok").onclick = async () => {
    const lignes = [...tbody.querySelectorAll(".dl-row")].map((tr) => ({
      article_id: tr.querySelector(".dl-art").value || null,
      designation: tr.querySelector(".dl-des").value || null,
      qte: +tr.querySelector(".dl-qte").value || 0,
      prix_unitaire: +tr.querySelector(".dl-pu").value || 0,
      remise_pct: Math.min(Math.max(+tr.querySelector(".dl-rem").value || 0, 0), 100),
      taux_tva: +tr.querySelector(".dl-tva").value || 0,
    })).filter((l) => l.qte > 0 && (l.article_id || l.designation));
    if (!$("#dv-cli").value) { toast("Choisissez un client.", "ko"); return; }
    if (!lignes.length) { toast("Ajoutez au moins une ligne.", "ko"); return; }
    const body = { tiers_id: $("#dv-cli").value, date_devis: $("#dv-date").value || null,
      validite: $("#dv-val").value || null, remise_globale_pct: +$("#dv-remg").value || 0,
      conditions: $("#dv-cond").value || null, note: $("#dv-note").value || null, lignes };
    try {
      const d = existant
        ? await api(`/ventes/devis/${existant.id}`, { method: "PUT", body })
        : await api(`/ventes/devis?societe_id=${currentSocieteId}`, { method: "POST", body });
      closeModal(); toast(`Devis ${d.numero} ${existant ? "modifié" : "créé"}.`, "ok");
      RENDER.devis(); devisDetail(d.id);
    } catch (e) { toast(e.message, "ko"); }
  };
}

// ── Détail devis / commande + actions par état ───────────────────────
async function devisDetail(id) {
  let d; try { d = await api(`/ventes/devis/${id}`); } catch (e) { toast(e.message, "ko"); return; }
  const [sl, sc] = DEVIS_ST[d.statut] || [d.statut, ""];
  const act = (idb, icon, label, cls = "") => `<button class="btn btn-sm ${cls}" id="${idb}"><i class="ti ${icon}"></i> ${label}</button>`;
  const confLabel = d.commande_origine ? "Prendre en charge" : "Confirmer la commande";
  const actions = [];
  if (d.statut === "brouillon") actions.push(act("da-edit", "ti-pencil", "Modifier"), act("da-send", "ti-send", "Marquer envoyé"), act("da-conf", "ti-hand-grab", confLabel, "btn-primary"), act("da-cancel", "ti-x", "Annuler"));
  if (d.statut === "envoye") actions.push(...(d.commande_origine ? [] : [act("da-edit", "ti-pencil", "Modifier")]), act("da-conf", "ti-hand-grab", confLabel, "btn-primary"), act("da-cancel", "ti-x", "Annuler"));
  if (d.statut === "confirme" && d.commande_origine) actions.push(act("da-refprod", "ti-barcode", d.reference_producteur ? "N° producteur" : "Renseigner le n° producteur"));
  if (d.statut === "confirme") {
    if (d.lignes.some((l) => l.livrable > 0)) actions.push(act("da-liv", "ti-truck-delivery", "Livrer", "btn-primary"));
    if (d.facturable) actions.push(act("da-fac", "ti-file-invoice", "Facturer le livré", d.lignes.some((l) => l.livrable > 0) ? "" : "btn-primary"));
    actions.push(act("da-cancel", "ti-x", "Annuler"));
  }
  actions.push(act("da-print", "ti-printer", d.statut === "confirme" ? "Imprimer la commande" : "Imprimer le devis"));
  const prog = d.statut === "confirme"
    ? `<div class="muted" style="font-size:12px;margin:4px 0 10px">Livraison : ${(LIVR_ST[d.statut_livraison] || ["—"])[0] || "—"} (${d.pct_livre} %) · Facturé : ${d.pct_facture} %</div>` : "";
  modal({
    title: `${d.statut === "confirme" ? "Commande client" : "Devis"} ${d.numero}`,
    wide: true,
    body: `<div style="margin-bottom:6px"><span class="pill ${sc}">${sl}</span>
        ${d.commande_origine ? `<span class="tag">PO ${esc(d.commande_origine)}</span>` : ""}
        ${d.transport ? `<span class="tag" title="Transporteur : ${esc(d.transport.transporteur)}"><i class="ti ti-truck"></i> ${esc(d.transport.course)} — ${esc((COURSE_ST[d.transport.statut] || [d.transport.statut])[0])}</span>` : ""}
        ${d.reference_producteur ? `<span class="tag" title="N° de commande producteur (réconciliation)"><i class="ti ti-barcode"></i> ${esc(d.reference_producteur)}</span>` : ""}
        ${d.expire ? '<span class="tag urgent">validité dépassée</span>' : ""}
        <b style="margin-left:8px">${esc(d.client)}</b>
        <span class="muted" style="margin-left:8px">${d.date}${d.validite ? " · valable jusqu'au " + d.validite : ""}</span></div>
      ${d.etapes_po ? bandeauEtapesPO(d.etapes_po) : ""}
      ${prog}
      <table><thead><tr><th>Article</th><th class="right">Qté</th><th class="right">P.U.</th><th class="right">Rem.%</th>
        <th class="right">HT net</th><th class="right">Livré</th><th class="right">Facturé</th></tr></thead><tbody>
      ${d.lignes.map((l) => `<tr><td>${l.article ? `<span class="num-cell">${esc(l.article)}</span> ` : ""}${esc(l.designation)}</td>
        <td class="right">${fmtNum(l.qte)}</td><td class="right">${fmtNum(l.prix_unitaire)}</td>
        <td class="right">${l.remise_pct ? fmtNum(l.remise_pct) : "—"}</td>
        <td class="right">${fmtNum(l.montant_ht)}</td>
        <td class="right">${l.gere_stock ? `${fmtNum(l.qte_livree)}${l.livrable > 0 ? ` <span class="muted">/ ${fmtNum(l.qte)}</span>` : ' <i class="ti ti-check" style="color:var(--g)"></i>'}` : "—"}</td>
        <td class="right">${fmtNum(l.qte_facturee)}</td></tr>`).join("")}</tbody></table>
      ${d.remise_totale ? `<div class="muted right" style="font-size:12.5px;margin-top:6px">Remises accordées : −${fmtNum(d.remise_totale)} $</div>` : ""}
      <div class="total-bar"><span class="lbl">HT ${fmtNum(d.total_ht)} · TVA ${fmtNum(d.total_tva)}</span><span class="val">${fmtNum(d.total_ttc)} $</span></div>
      ${d.conditions ? `<div class="muted" style="font-size:12.5px;margin-top:6px"><i class="ti ti-file-text"></i> ${esc(d.conditions)}</div>` : ""}
      ${d.livraisons && d.livraisons.length ? `<div style="margin-top:14px"><b style="font-size:13px">Bons de livraison</b>
        <table>${d.livraisons.map((bl) => `<tr><td class="num-cell">${esc(bl.numero)}</td><td>${bl.date}</td>
          <td class="muted">${bl.lignes.map((x) => `${esc(x.designation)} × ${fmtNum(x.qte)}`).join(" · ")}</td>
          <td class="right"><button class="btn btn-sm" data-blp="${bl.id}"><i class="ti ti-printer"></i></button></td></tr>`).join("")}</table></div>` : ""}
      ${d.factures && d.factures.length ? `<div style="margin-top:14px"><b style="font-size:13px">Factures</b>
        <table>${d.factures.map((f) => { const [rl, rc] = REGL_ST[f.statut_reglement] || ["", ""]; return `<tr>
          <td class="num-cell">${esc(f.numero)}</td><td>${f.date}</td>
          <td class="right">${fmtNum(f.total_ttc)} $</td>
          <td><span class="pill ${rc}">${rl}</span>${f.en_retard ? ' <span class="tag urgent">retard</span>' : ""}</td>
          <td class="right" style="white-space:nowrap">
            ${f.solde_du_usd > 0 ? `<button class="btn btn-sm btn-primary" data-freg="${f.id}"><i class="ti ti-cash"></i> Encaisser</button>` : ""}
            <button class="btn btn-sm" data-fprint="${f.id}"><i class="ti ti-printer"></i></button></td></tr>`; }).join("")}</table></div>` : ""}`,
    footer: `<button class="btn" onclick="closeModal()">Fermer</button>${actions.join("")}`,
  });
  const refresh = () => { closeModal(); RENDER.devis(); devisDetail(d.id); };
  if ($("#da-edit")) $("#da-edit").onclick = () => { closeModal(); devisModal(d); };
  if ($("#da-send")) $("#da-send").onclick = async () => {
    try { await api(`/ventes/devis/${d.id}/envoyer`, { method: "POST" }); toast("Devis marqué envoyé.", "ok"); printDevis({ ...d, statut: "envoye" }); refresh(); }
    catch (e) { toast(e.message, "ko"); }
  };
  if ($("#da-conf")) $("#da-conf").onclick = async () => {
    if (d.commande_origine) {
      // PO du groupe : prise en charge = N° PRODUCTEUR + ASSOCIATION des articles.
      // TOUTES les lignes sont montrées — y compris celles associées automatiquement
      // par code identique, pour que le préposé vérifie et puisse corriger.
      const toutes = (d.lignes || []);
      const mesArticles = toutes.length
        ? (await api(`/commercial/articles?societe_id=${currentSocieteId}`).catch(() => [])).filter((a) => a.actif) : [];
      const assoHtml = toutes.length ? `
        <div class="muted" style="font-size:12px;margin:10px 0 4px">Correspondance avec VOTRE stock — vérifiez chaque ligne (règle : pas de chargement sans stock)</div>
        <table><thead><tr><th>Ligne de la commande</th><th>Votre article</th></tr></thead><tbody>
        ${toutes.map((l) => `<tr><td>${esc(l.designation)}${l.code_acheteur ? ` <span class="tag">code acheteur : ${esc(l.code_acheteur)}</span>` : ""}
            ${!l.a_associer && l.article ? ' <span class="tag" title="Associé automatiquement (même code) — modifiable ci-contre" style="background:var(--gl);color:var(--g)">auto</span>' : ""}</td>
          <td><select class="form-select pc2-asso" data-l="${l.id}" data-code="${esc(l.code_acheteur || "")}" data-des="${esc(l.designation)}" data-unite="${esc(l.unite_acheteur || "")}" data-prix="${l.prix_unitaire}">
            <option value="__new">➕ Créer l'article${l.code_acheteur ? ` (${esc(l.code_acheteur)})` : ""} dans mon stock</option>
            ${mesArticles.map((a) => `<option value="${a.id}" ${a.code === (l.article || l.code_acheteur) ? "selected" : ""}>${esc(a.code)} — ${esc(a.designation)} (stock ${fmtNum(a.stock_qte)})</option>`).join("")}
          </select></td></tr>`).join("")}</tbody></table>` : "";
      modal({
        title: `Prendre en charge — ${d.numero}`,
        wide: !!toutes.length,
        body: `<div class="banner"><i class="ti ti-hand-grab"></i> Commande <b>${esc(d.commande_origine)}</b> reçue du groupe.
            La prise en charge lance l'organisation : commande chez votre producteur, chargement, puis facturation.</div>
          <div class="form-group"><label class="form-label">N° de commande PRODUCTEUR (logiciel du fournisseur — clé de réconciliation)</label>
            <input id="pc2-ref" class="form-input" placeholder="ex. GCK-2026-08841" value="${esc(d.reference_producteur || "")}" />
            <div class="muted" style="font-size:12px;margin-top:4px">Ce numéro suivra tous les documents : commande, bon de chargement, factures, fiche de course.</div></div>
          ${assoHtml}`,
        footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="pc2-ok"><i class="ti ti-check"></i> Prendre en charge</button>`,
      });
      $("#pc2-ok").onclick = async () => {
        const associations = [...document.querySelectorAll(".pc2-asso")].map((s) => {
          if (s.value === "__new") {
            return { ligne_id: s.dataset.l, nouvel_article: {
              code: s.dataset.code || s.dataset.des.slice(0, 18).toUpperCase().replace(/\s+/g, "-"),
              designation: s.dataset.des, unite: s.dataset.unite || "unité",
              prix_vente: +s.dataset.prix || 0 } };
          }
          return { ligne_id: s.dataset.l, article_id: s.value };
        });
        try {
          await api(`/ventes/devis/${d.id}/confirmer`, { method: "POST", body: {
            reference_producteur: $("#pc2-ref").value || null, associations } });
          closeModal(); toast(`Commande ${d.numero} prise en charge${associations.length ? " — articles associés à votre stock" : ""}.`, "ok"); refresh();
        } catch (e) { toast(e.message, "ko"); }
      };
    } else {
      try { await api(`/ventes/devis/${d.id}/confirmer`, { method: "POST" }); toast(`Commande ${d.numero} confirmée.`, "ok"); refresh(); }
      catch (e) { toast(e.message, "ko"); }
    }
  };
  if ($("#da-refprod")) $("#da-refprod").onclick = () => {
    modal({ title: "N° producteur",
      body: `<div class="form-group"><label class="form-label">N° de commande chez le producteur</label>
        <input id="rp2-ref" class="form-input" value="${esc(d.reference_producteur || "")}" /></div>`,
      footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="rp2-ok"><i class="ti ti-check"></i> Enregistrer</button>` });
    $("#rp2-ok").onclick = async () => {
      try { await api(`/ventes/devis/${d.id}/reference-producteur`, { method: "POST", body: { reference_producteur: $("#rp2-ref").value } });
        closeModal(); toast("N° producteur enregistré.", "ok"); refresh(); } catch (e) { toast(e.message, "ko"); }
    };
  };
  if ($("#da-cancel")) $("#da-cancel").onclick = async () => {
    try { await api(`/ventes/devis/${d.id}/annuler`, { method: "POST" }); toast("Devis annulé.", "ok"); closeModal(); RENDER.devis(); }
    catch (e) { toast(e.message, "ko"); }
  };
  if ($("#da-liv")) $("#da-liv").onclick = () => livraisonModal(d);
  if ($("#da-fac")) $("#da-fac").onclick = () => facturerDevisModal(d);
  if ($("#da-print")) $("#da-print").onclick = () => printDevis(d);
  document.querySelectorAll("[data-blp]").forEach((b) => b.onclick = () => {
    const bl = d.livraisons.find((x) => x.id === b.dataset.blp);
    printBL(d, bl);
  });
  document.querySelectorAll("[data-fprint]").forEach((b) => b.onclick = async () => {
    try { printFactureVente(await api(`/commercial/factures/${b.dataset.fprint}`)); } catch (e) { toast(e.message, "ko"); }
  });
  document.querySelectorAll("[data-freg]").forEach((b) => b.onclick = async () => {
    try { const f = await api(`/commercial/factures/${b.dataset.freg}`); closeModal(); reglementModal(f, () => devisDetail(d.id)); }
    catch (e) { toast(e.message, "ko"); }
  });
}

// ── Livraison (BL) ───────────────────────────────────────────────────
function livraisonModal(d) {
  const livrables = d.lignes.filter((l) => l.livrable > 0);
  modal({
    title: `Livraison — ${d.numero}`,
    body: `<div class="banner"><i class="ti ti-truck-delivery"></i> Les quantités livrées sortent du stock au coût moyen pondéré. Les livraisons partielles sont possibles.</div>
      <table><thead><tr><th>Article</th><th class="right">Commandé</th><th class="right">Déjà livré</th><th class="right">Stock dispo</th><th class="right">À livrer</th></tr></thead><tbody>
      ${livrables.map((l) => `<tr><td>${esc(l.designation)}</td>
        <td class="right">${fmtNum(l.qte)}</td><td class="right">${fmtNum(l.qte_livree)}</td>
        <td class="right ${l.stock_dispo < l.livrable ? "danger" : ""}">${fmtNum(l.stock_dispo)}</td>
        <td class="right"><input class="form-input right lv-qte" data-l="${l.id}" type="number" step="any" min="0" max="${l.livrable}" value="${Math.min(l.livrable, l.stock_dispo)}" style="width:80px" /></td></tr>`).join("")}
      </tbody></table>
      <div class="form-group" style="margin-top:10px"><label class="form-label">Note (chauffeur, véhicule, référence…)</label><input id="lv-note" class="form-input" /></div>`,
    footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="lv-ok"><i class="ti ti-truck-delivery"></i> Valider la livraison</button>`,
  });
  $("#lv-ok").onclick = async () => {
    const lignes = [...document.querySelectorAll(".lv-qte")].map((i) => ({ ligne_id: i.dataset.l, qte: +i.value || 0 })).filter((l) => l.qte > 0);
    if (!lignes.length) { toast("Indiquez au moins une quantité.", "ko"); return; }
    try {
      const nd = await api(`/ventes/devis/${d.id}/livrer`, { method: "POST", body: { lignes, note: $("#lv-note").value || null } });
      closeModal(); closeModal();
      const bl = nd.livraisons[nd.livraisons.length - 1];
      toast(`Bon de livraison ${bl.numero} créé.`, "ok");
      printBL(nd, bl);
      RENDER.devis(); devisDetail(d.id);
    } catch (e) { toast(e.message, "ko"); }
  };
}

function facturerDevisModal(d) {
  modal({
    title: `Facturer — ${d.numero}`,
    body: `<div class="banner"><i class="ti ti-file-invoice"></i> La facture portera sur les quantités <b>livrées non encore facturées</b> (et les lignes de service). Le stock est déjà sorti à la livraison.</div>
      <div class="form-group"><label class="form-label">Échéance de paiement (optionnel)</label><input id="fc-ech" class="form-input" type="date" /></div>`,
    footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="fc-ok"><i class="ti ti-file-invoice"></i> Générer la facture</button>`,
  });
  $("#fc-ok").onclick = async () => {
    try {
      const r = await api(`/ventes/devis/${d.id}/facturer`, { method: "POST", body: { echeance: $("#fc-ech").value || null } });
      closeModal(); closeModal();
      toast(`Facture ${r.facture.numero} générée (${fmtNum(r.facture.total_ttc)} $).`, "ok");
      try { printFactureVente(await api(`/commercial/factures/${r.facture.id}`)); } catch {}
      RENDER.devis(); devisDetail(d.id);
    } catch (e) { toast(e.message, "ko"); }
  };
}

// ── Règlement client ─────────────────────────────────────────────────
async function reglementModal(f, onDone) {
  const caisses = (await api(`/caisses?societe_id=${currentSocieteId}`).catch(() => []));
  const solde = f.solde_du_usd != null ? f.solde_du_usd : f.total_ttc;
  modal({
    title: `Encaisser — ${f.numero}`,
    body: `<div class="total-bar" style="margin-top:0"><span class="lbl">Solde dû</span><span class="val">${fmtNum(solde)} $</span></div>
      <div class="form-row" style="margin-top:12px">
        <div class="form-group"><label class="form-label">Mode</label><select id="rg-mode" class="form-select">
          <option value="espece">Espèces (caisse)</option><option value="banque">Banque</option><option value="mobile_money">Mobile Money</option></select></div>
        <div class="form-group"><label class="form-label">Devise</label><select id="rg-dev" class="form-select"><option>USD</option><option>CDF</option></select></div>
        <div class="form-group"><label class="form-label">Montant</label><input id="rg-mnt" class="form-input right" type="number" step="any" value="${solde}" /></div></div>
      <div class="form-group" id="rg-caisse-wrap"><label class="form-label">Caisse qui encaisse</label>
        <select id="rg-caisse" class="form-select">${caisses.map((c) => `<option value="${c.id}" ${c.est_principale ? "selected" : ""}>${esc(c.libelle)}${c.session_ouverte ? "" : " (fermée)"}</option>`).join("")}</select></div>
      <div class="form-group"><label class="form-label">Référence (n° transaction, bordereau…)</label><input id="rg-ref" class="form-input" /></div>`,
    footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="rg-ok"><i class="ti ti-cash"></i> Encaisser</button>`,
  });
  $("#rg-mode").onchange = (e) => $("#rg-caisse-wrap").classList.toggle("hidden", e.target.value !== "espece");
  $("#rg-ok").onclick = async () => {
    try {
      const r = await api(`/ventes/factures/${f.id}/regler`, { method: "POST", body: {
        mode: $("#rg-mode").value, devise: $("#rg-dev").value, montant: +$("#rg-mnt").value || 0,
        caisse_id: $("#rg-mode").value === "espece" ? $("#rg-caisse").value : null,
        reference: $("#rg-ref").value || null } });
      closeModal();
      toast(r.statut_reglement === "payee" ? `Facture ${f.numero} soldée ✓` : `Règlement enregistré — reste ${fmtNum(r.solde_du_usd)} $.`, "ok");
      refreshComptaBadge && refreshComptaBadge();
      if (onDone) onDone(); else RENDER.ventes();
    } catch (e) { toast(e.message, "ko"); }
  };
}

// ── Documents A4 (devis / commande / BL / facture) ───────────────────
function _docA4(document) {
  return Editions.piece(document);
}

function printDevis(d) {
  const confirme = d.statut === "confirme";
  _docA4({
    titre: confirme ? "COMMANDE CLIENT" : "DEVIS",
    numero: d.numero,
    client: d.client,
    meta: [["Date", d.date], ...(d.validite && !confirme ? [["Valable jusqu'au", d.validite]] : []),
           ...(d.reference_producteur ? [["Réf. producteur", d.reference_producteur]] : []),
           ...(d.commande_origine ? [["Commande groupe", d.commande_origine]] : []),
           ...(confirme ? [["Statut", "Commande confirmée"]] : [])],
    colonnes: [{ t: "Désignation" }, { t: "Qté", r: 1 }, { t: "P.U. (USD)", r: 1 }, { t: "Remise", r: 1 }, { t: "TVA", r: 1 }, { t: "Montant HT", r: 1 }],
    lignes: d.lignes.map((l) => [esc(l.designation), fmtNum(l.qte), fmtNum(l.prix_unitaire),
      l.remise_pct ? fmtNum(l.remise_pct) + " %" : "—", fmtNum(l.taux_tva) + " %", fmtNum(l.montant_ht)]),
    totaux: [
      ...(d.remise_totale ? [{ l: "Remises", v: "−" + fmtNum(d.remise_totale) + " $" }] : []),
      { l: "Total HT", v: fmtNum(d.total_ht) + " $" }, { l: "TVA", v: fmtNum(d.total_tva) + " $" },
      { l: "TOTAL TTC", v: fmtNum(d.total_ttc) + " USD", grand: 1 }],
    mentions: [d.conditions ? `<b>Conditions :</b> ${esc(d.conditions)}` : "",
               !confirme ? "Ce devis vaut offre commerciale ; il devient commande ferme après acceptation écrite du client." : ""].filter(Boolean).join("<br/>"),
    signatures: confirme ? ["Le client", "Pour la société"] : ["Bon pour accord (le client)"],
  });
}

function printBL(d, bl) {
  _docA4({
    titre: "BON DE LIVRAISON",
    numero: bl.numero,
    client: d.client,
    meta: [["Date", bl.date], ["Commande", d.numero],
           ...(d.reference_producteur ? [["Réf. producteur", d.reference_producteur]] : []),
           ...(bl.note ? [["Référence", bl.note]] : [])],
    colonnes: [{ t: "Désignation" }, { t: "Quantité livrée", r: 1 }],
    lignes: bl.lignes.map((x) => [esc(x.designation), fmtNum(x.qte)]),
    totaux: null,
    mentions: "Marchandises reçues complètes et en bon état — les réserves éventuelles doivent être portées ci-dessous avant signature.",
    signatures: ["Le livreur", "Le client (réception)"],
  });
}

function printFactureVente(f) {
  _docA4({
    titre: "FACTURE",
    numero: f.numero,
    client: f.tiers,
    meta: [["Date", f.date], ...(f.echeance ? [["Échéance", f.echeance]] : []),
           ...(f.reference ? [["Réf. producteur", f.reference]] : []),
           ...(f.statut_reglement ? [["Règlement", (REGL_ST[f.statut_reglement] || [""])[0]]] : [])],
    colonnes: [{ t: "Désignation" }, { t: "Qté", r: 1 }, { t: "P.U. (USD)", r: 1 }, { t: "Remise", r: 1 }, { t: "TVA", r: 1 }, { t: "Montant HT", r: 1 }],
    lignes: f.lignes.map((l) => [esc(l.designation), fmtNum(l.qte), fmtNum(l.prix_unitaire),
      l.remise_pct ? fmtNum(l.remise_pct) + " %" : "—", fmtNum(l.taux_tva) + " %", fmtNum(l.montant_ht)]),
    totaux: [
      { l: "Total HT", v: fmtNum(f.total_ht) + " $" }, { l: "TVA (16 %)", v: fmtNum(f.total_tva) + " $" },
      ...(f.regle_usd ? [{ l: "Déjà réglé", v: "−" + fmtNum(f.regle_usd) + " $" }] : []),
      { l: f.regle_usd ? "NET À PAYER" : "TOTAL TTC", v: fmtNum(f.solde_du_usd != null ? f.solde_du_usd : f.total_ttc) + " USD", grand: 1 }],
    mentions: "Facture payable à réception sauf conditions particulières. Merci de rappeler le numéro de facture lors du règlement.",
    signatures: ["Pour la société"],
  });
}

// ═══ Module Transport — KAKO Logistique (flotte, courses, contrats) ═══
const COURSE_ST = {
  demande: ["Demande (PO)", "st-due"],
  brouillon: ["Brouillon", "st-brouillon"], validee: ["Validée", "st-envoye"],
  en_cours: ["En route", "st-confirme"], arrivee: ["En déchargement", "st-partielle"],
  receptionnee: ["Réceptionnée (à confirmer)", "st-partielle"],
  livree: ["Livrée", "st-partielle"],
  facturee: ["Facturée", "st-payee"], annulee: ["Annulée", "st-annule"],
};
const CAMION_ST = {
  disponible: ["Disponible", "st-payee"], en_course: ["En course", "st-confirme"],
  immobilise: ["Immobilisé", "st-annule"],
};
let coursesFiltre = "";

// ── Flotte & maintenance ─────────────────────────────────────────────
// ── Maintenance mutualisée (camions + engins de location) ────────────
const INTER_ST = { planifiee: ["Planifiée", "st-envoye"], en_cours: ["En cours", "st-partielle"], terminee: ["Terminée", "st-payee"] };

function maintenanceTableHTML(inters) {
  if (!inters.length) return '<div class="muted">Aucune intervention.</div>';
  return `<table><thead><tr><th>N°</th><th>Véhicule</th><th>Type</th><th>Description</th><th>Prestataire</th>
      <th>Prévue le</th><th class="right">Coût est.</th><th class="right">Coût réel</th><th>Statut</th><th></th></tr></thead><tbody>
    ${inters.map((i) => { const [sl, sc] = INTER_ST[i.statut] || [i.statut, "st-partielle"]; return `<tr ${i.statut === "terminee" ? 'style="opacity:.65"' : ""}>
      <td class="num-cell">${esc(i.numero)}</td><td><b>${esc(i.vehicule || "—")}</b></td>
      <td>${esc(i.type)}${i.immobilise ? ' <i class="ti ti-lock" title="véhicule immobilisé pendant l’intervention"></i>' : ""}</td>
      <td>${esc(i.description)}${i.requisition ? `<div class="muted" style="font-size:11px">Réq. ${esc(i.requisition)}</div>` : ""}</td>
      <td>${esc(i.prestataire || "—")}</td>
      <td>${i.date_prevue || "—"}</td>
      <td class="right">${i.cout_estime != null ? fmtNum(i.cout_estime) : "—"}</td>
      <td class="right">${i.cout_reel != null ? "<b>" + fmtNum(i.cout_reel) + "</b>" : "—"}</td>
      <td><span class="pill ${sc}">${sl}</span></td>
      <td class="right" style="white-space:nowrap">${i.statut === "planifiee" ? `<button class="btn btn-sm" data-idem="${i.id}"><i class="ti ti-player-play"></i> Démarrer</button> ` : ""}${i.statut !== "terminee" ? `<button class="btn btn-sm btn-primary" data-ifin="${i.id}"><i class="ti ti-check"></i> Terminer</button>` : (i.date_fin || "")}</td></tr>`; }).join("")}
    </tbody></table>`;
}

function bindMaintenance(el, refresh) {
  el.querySelectorAll("[data-idem]").forEach((b) => b.onclick = async () => {
    try { await api(`/transport/interventions/${b.dataset.idem}/demarrer`, { method: "POST", body: {} });
      toast("Intervention démarrée — véhicule immobilisé si demandé.", "ok"); refresh(); } catch (e) { toast(e.message, "ko"); }
  });
  el.querySelectorAll("[data-ifin]").forEach((b) => b.onclick = () => {
    modal({ title: "Terminer l'intervention",
      body: `<div class="form-group"><label class="form-label">Coût réel USD (vide = repris de la justification liée)</label>
        <input id="if-cout" class="form-input" type="number" step="any" /></div>
        <div class="banner"><i class="ti ti-info-circle"></i> Le véhicule redevient disponible si aucune autre intervention ne l'immobilise.</div>`,
      footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="if-ok"><i class="ti ti-check"></i> Remettre en service</button>` });
    $("#if-ok").onclick = async () => {
      try { await api(`/transport/interventions/${b.dataset.ifin}/terminer`, { method: "POST", body: { cout_reel: +$("#if-cout").value || null } });
        closeModal(); toast("Intervention terminée.", "ok"); refresh(); } catch (e) { toast(e.message, "ko"); }
    };
  });
}

RENDER.flotte = async () => {
  const el = $("#view-flotte");
  el.innerHTML = `<div class="muted">Chargement…</div>`;
  const [camions, inters] = await Promise.all([
    api(`/transport/camions?societe_id=${currentSocieteId}`).catch(() => []),
    api(`/transport/interventions?societe_id=${currentSocieteId}&cible=camion`).catch(() => []),
  ]);
  el.innerHTML = `<div class="section-hdr" style="margin-bottom:12px">
      <div class="section-title"><i class="ti ti-truck"></i> Flotte (${camions.filter((c) => c.actif).length} camions)</div>
      <div style="margin-left:auto;display:flex;gap:8px">
        <button class="btn btn-sm" id="fl-chauffeur"><i class="ti ti-user-plus"></i> Chauffeur</button>
        <button class="btn btn-sm" id="fl-panne"><i class="ti ti-tool"></i> Signaler / planifier</button>
        <button class="btn btn-sm btn-primary" id="fl-new"><i class="ti ti-plus"></i> Nouveau camion</button></div></div>
    <div class="caisse-cards">
      ${camions.filter((c) => c.actif).map((c) => { const [sl, sc] = CAMION_ST[c.statut] || [c.statut, ""]; return `
        <div class="caisse-card">
          <div class="cc-top"><b>${esc(c.immatriculation)}</b>
            ${c.type === "sous_traite" ? '<span class="tag">sous-traité</span>' : ""}</div>
          <div class="muted" style="font-size:12px;margin:4px 0">${esc(c.marque || "—")} · ${fmtNum(c.capacite_tonnes)} t
            ${c.proprietaire ? `<br/><i class="ti ti-user"></i> ${esc(c.proprietaire)}${c.remuneration_mode ? ` (${c.remuneration_mode === "forfait" ? fmtNum(c.remuneration_valeur) + " $/voyage" : fmtNum(c.remuneration_valeur) + " % du prix"})` : ""}` : ""}</div>
          <span class="pill ${sc}">${sl}</span>
          ${c.motif_immobilisation ? `<div class="muted" style="font-size:11px;margin-top:4px"><i class="ti ti-alert-triangle"></i> ${esc(c.motif_immobilisation)}${c.immobilise_depuis ? " · depuis " + c.immobilise_depuis : ""}</div>` : ""}
        </div>`; }).join("") || '<div class="empty"><i class="ti ti-truck"></i>Aucun camion — créez la flotte.</div>'}
    </div>
    <div class="card" style="margin-top:16px"><div class="card-hdr"><div class="card-hdr-title"><i class="ti ti-tool"></i> Maintenance</div></div>
      <div class="card-body">${maintenanceTableHTML(inters)}</div></div>`;
  $("#fl-new").onclick = () => camionModal();
  $("#fl-chauffeur").onclick = () => chauffeurModal();
  $("#fl-panne").onclick = () => interventionModal(camions.filter((c) => c.actif), "camion", () => RENDER.flotte());
  bindMaintenance(el, () => RENDER.flotte());
};

async function camionModal() {
  const fourn = await api(`/commercial/tiers?societe_id=${currentSocieteId}&type=fournisseur`).catch(() => []);
  modal({
    title: "Nouveau camion",
    body: `<div class="form-row">
        <div class="form-group"><label class="form-label">Immatriculation</label><input id="cm-immat" class="form-input" placeholder="ex. 9412 AB 05" /></div>
        <div class="form-group"><label class="form-label">Marque</label><input id="cm-marque" class="form-input" placeholder="Howo, Mercedes…" /></div>
        <div class="form-group"><label class="form-label">Capacité (t)</label><input id="cm-cap" class="form-input right" type="number" step="any" value="30" /></div></div>
      <div class="form-row">
        <div class="form-group"><label class="form-label">Type</label><select id="cm-type" class="form-select">
          <option value="propre">Camion propre (flotte KAKO Logistique)</option>
          <option value="sous_traite">Sous-traité (camion d'un tiers)</option></select></div>
        <div class="form-group"><label class="form-label">Consommation (L/100 km)</label><input id="cm-conso" class="form-input right" type="number" step="any" /></div></div>
      <div id="cm-st" class="hidden">
        <div class="form-row">
          <div class="form-group"><label class="form-label">Propriétaire (fournisseur)</label><select id="cm-prop" class="form-select">${fourn.map((f) => `<option value="${f.id}">${esc(Catalogue.label(f))}</option>`).join("")}</select></div>
          <div class="form-group"><label class="form-label">Rémunération</label><select id="cm-rmode" class="form-select">
            <option value="forfait">Forfait par voyage ($)</option><option value="pourcentage">% du prix client</option></select></div>
          <div class="form-group"><label class="form-label">Valeur</label><input id="cm-rval" class="form-input right" type="number" step="any" /></div></div>
        <div class="banner"><i class="ti ti-info-circle"></i> À chaque course livrée, la dette envers le propriétaire est générée automatiquement (compte 401, charge 612).</div></div>`,
    footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="cm-ok"><i class="ti ti-check"></i> Créer</button>`,
  });
  $("#cm-type").onchange = (e) => $("#cm-st").classList.toggle("hidden", e.target.value !== "sous_traite");
  $("#cm-ok").onclick = async () => {
    const st = $("#cm-type").value === "sous_traite";
    try {
      await api(`/transport/camions?societe_id=${currentSocieteId}`, { method: "POST", body: {
        immatriculation: $("#cm-immat").value, marque: $("#cm-marque").value || null,
        capacite_tonnes: +$("#cm-cap").value || 0, consommation_l_100km: +$("#cm-conso").value || null,
        type: $("#cm-type").value,
        proprietaire_tiers_id: st ? $("#cm-prop").value : null,
        remuneration_mode: st ? $("#cm-rmode").value : null,
        remuneration_valeur: st ? +$("#cm-rval").value || null : null } });
      closeModal(); toast("Camion ajouté à la flotte.", "ok"); RENDER.flotte();
    } catch (e) { toast(e.message, "ko"); }
  };
}

function chauffeurModal() {
  modal({
    title: "Nouveau chauffeur",
    body: `<div class="form-group"><label class="form-label">Nom complet</label><input id="ch-nom" class="form-input" /></div>
      <div class="form-row"><div class="form-group"><label class="form-label">Téléphone</label><input id="ch-tel" class="form-input" /></div>
      <div class="form-group"><label class="form-label">N° permis</label><input id="ch-permis" class="form-input" /></div></div>
      <div class="banner"><i class="ti ti-info-circle"></i> Un tiers « personnel » est créé automatiquement — il servira pour ses avances à justifier.</div>`,
    footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="ch-ok"><i class="ti ti-check"></i> Créer</button>`,
  });
  $("#ch-ok").onclick = async () => {
    try {
      await api(`/transport/chauffeurs?societe_id=${currentSocieteId}`, { method: "POST", body: {
        nom: $("#ch-nom").value, telephone: $("#ch-tel").value || null, numero_permis: $("#ch-permis").value || null } });
      closeModal(); toast("Chauffeur créé.", "ok");
    } catch (e) { toast(e.message, "ko"); }
  };
}

function interventionModal(vehicules, cible = "camion", refresh = null) {
  // Maintenance mutualisée : cible "camion" ou "engin". Une date prévue crée
  // une intervention PLANIFIÉE (le véhicule reste disponible jusqu'au démarrage).
  const libelle = (v) => cible === "engin"
    ? `${v.nom}${v.statut === "immobilise" ? " (immobilisé)" : ""}`
    : `${v.immatriculation} (${(CAMION_ST[v.statut] || [v.statut])[0]})`;
  modal({
    title: cible === "engin" ? "Panne / entretien d'un engin" : "Signaler une panne / un entretien",
    body: `<div class="form-row">
        <div class="form-group"><label class="form-label">${cible === "engin" ? "Engin" : "Camion"}</label><select id="iv-cam" class="form-select">${vehicules.map((v) => `<option value="${v.id}">${esc(libelle(v))}</option>`).join("")}</select></div>
        <div class="form-group"><label class="form-label">Type</label><select id="iv-type" class="form-select">
          <option value="reparation">Réparation (panne)</option><option value="entretien">Entretien préventif</option>
          <option value="controle">Contrôle technique</option><option value="accident">Accident</option></select></div></div>
      <div class="form-group"><label class="form-label">Description du problème</label><input id="iv-desc" class="form-input" /></div>
      <div class="form-row">
        <div class="form-group"><label class="form-label">Prestataire (garage, mécanicien)</label><input id="iv-prest" class="form-input" /></div>
        <div class="form-group"><label class="form-label">Coût estimé USD</label><input id="iv-cout" class="form-input right" type="number" step="any" /></div>
        <div class="form-group"><label class="form-label">Planifier pour le (facultatif)</label><input id="iv-prevue" class="form-input" type="date" /></div></div>
      <label style="display:flex;align-items:center;gap:8px;font-size:13px"><input type="checkbox" id="iv-immo" checked style="width:auto" /> Immobiliser le véhicule pendant l'intervention</label>
      <div class="banner" style="margin-top:10px"><i class="ti ti-info-circle"></i> Une date future = intervention planifiée : le véhicule reste disponible jusqu'au démarrage. Le financement passe par le circuit réquisition → avance habituel.</div>`,
    footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="iv-ok"><i class="ti ti-tool"></i> Enregistrer</button>`,
  });
  $("#iv-ok").onclick = async () => {
    try {
      const body = {
        type: $("#iv-type").value, description: $("#iv-desc").value,
        prestataire: $("#iv-prest").value || null, cout_estime: +$("#iv-cout").value || null,
        date_prevue: $("#iv-prevue").value || null,
        immobilise: $("#iv-immo").checked };
      body[cible === "engin" ? "engin_id" : "camion_id"] = $("#iv-cam").value;
      await api(`/transport/interventions?societe_id=${currentSocieteId}`, { method: "POST", body });
      closeModal(); toast("Intervention enregistrée.", "ok"); (refresh || RENDER.flotte)();
    } catch (e) { toast(e.message, "ko"); }
  };
}

// ═════════════════════════════════════════════════════════════════════
// LOCATION D'ENGINS — parc, heures prestées, RPE & facturation
// ═════════════════════════════════════════════════════════════════════
const ENGIN_ST = { disponible: ["Disponible", "st-payee"], immobilise: ["Immobilisé", "st-due"] };
let enginsCfg = null;

async function chargerEnginsCfg() {
  enginsCfg = await api(`/engins/config?societe_id=${currentSocieteId}`)
    .catch(() => ({ forfait_mensuel_h: 208, arrondi: "nearest", rpe_prefix: "HRZ", locataire: "" }));
  return enginsCfg;
}

// Calculs identiques au serveur (et à l'app desktop) pour l'aperçu en direct
function egParse(hhmm) {
  const m = String(hhmm || "").match(/^(\d{1,2}):(\d{2})$/);
  if (!m) return null;
  return +m[1] * 60 + +m[2];
}
function egDuree(d, f) {
  const a = egParse(d), b = egParse(f);
  if (a == null || b == null) return 0;
  return b > a ? b - a : b + 1440 - a;
}
function egArrondi(min) {
  const mode = enginsCfg?.arrondi || "nearest";
  if (mode === "down") return Math.floor(min / 5) * 5;
  if (mode === "up") return Math.ceil(min / 5) * 5;
  return Math.round(min / 5) * 5;
}
function egHM(min) { const m = Math.abs(Math.round(min)); return (min < 0 ? "-" : "") + Math.floor(m / 60) + "h" + String(m % 60).padStart(2, "0"); }
function egDec(min) { return (egArrondi(min) / 60).toFixed(2).replace(".", ","); }

// ── Parc & maintenance ───────────────────────────────────────────────
RENDER["engins-parc"] = async () => {
  const el = $("#view-engins-parc");
  el.innerHTML = `<div class="muted">Chargement…</div>`;
  const [engins, inters] = await Promise.all([
    api(`/engins/engins?societe_id=${currentSocieteId}`).catch(() => []),
    api(`/transport/interventions?societe_id=${currentSocieteId}&cible=engin`).catch(() => []),
  ]);
  const actifs = engins.filter((e) => e.actif);
  el.innerHTML = `<div class="section-hdr" style="margin-bottom:12px">
      <div class="section-title"><i class="ti ti-backhoe"></i> Parc d'engins (${actifs.length})</div>
      <div style="margin-left:auto;display:flex;gap:8px">
        <button class="btn btn-sm" id="eg-panne"><i class="ti ti-tool"></i> Signaler / planifier</button>
        <button class="btn btn-sm btn-primary" id="eg-new"><i class="ti ti-plus"></i> Nouvel engin</button></div></div>
    <div class="caisse-cards">
      ${actifs.map((e) => { const [sl, sc] = ENGIN_ST[e.statut] || [e.statut, ""]; return `
        <div class="caisse-card">
          <div class="cc-top"><b>${esc(e.nom)}</b>
            <button class="btn btn-sm" data-edit="${e.id}" title="Modifier" style="margin-left:auto"><i class="ti ti-pencil"></i></button></div>
          <div class="muted" style="font-size:12px;margin:4px 0">${esc(e.categorie || "—")}${e.immatriculation ? " · " + esc(e.immatriculation) : ""}<br/>
            Forfait ${fmtNum(e.tarif_mensuel_usd)} $/mois · H. supp. ${fmtNum(e.tarif_heure_supp_usd)} $/h</div>
          <span class="pill ${sc}">${sl}</span>
          ${e.motif_immobilisation ? `<div class="muted" style="font-size:11px;margin-top:4px"><i class="ti ti-alert-triangle"></i> ${esc(e.motif_immobilisation)}${e.immobilise_depuis ? " · depuis " + e.immobilise_depuis : ""}</div>` : ""}
        </div>`; }).join("") || '<div class="empty"><i class="ti ti-backhoe"></i>Aucun engin — commencez par créer le parc et ses tarifs.</div>'}
    </div>
    <div class="card" style="margin-top:16px"><div class="card-hdr"><div class="card-hdr-title"><i class="ti ti-tool"></i> Maintenance des engins</div></div>
      <div class="card-body">${maintenanceTableHTML(inters)}</div></div>`;
  $("#eg-new").onclick = () => enginModal();
  $("#eg-panne").onclick = () => actifs.length
    ? interventionModal(actifs, "engin", () => RENDER["engins-parc"]())
    : toast("Créez d'abord un engin.", "ko");
  el.querySelectorAll("[data-edit]").forEach((b) => b.onclick = () => enginModal(engins.find((e) => e.id === b.dataset.edit)));
  bindMaintenance(el, () => RENDER["engins-parc"]());
};

function enginModal(e = null) {
  modal({
    title: e ? `Modifier ${e.nom}` : "Nouvel engin",
    body: `<div class="form-row">
        <div class="form-group"><label class="form-label">Nom</label><input id="eg-nom" class="form-input" placeholder="ex. Chargeuse 01" value="${esc(e?.nom || "")}" /></div>
        <div class="form-group"><label class="form-label">Catégorie</label><input id="eg-cat" class="form-input" placeholder="Pelle, Chargeuse, Camion…" value="${esc(e?.categorie || "")}" /></div>
        <div class="form-group"><label class="form-label">Immatriculation / n° série</label><input id="eg-immat" class="form-input" value="${esc(e?.immatriculation || "")}" /></div></div>
      <div class="form-row">
        <div class="form-group"><label class="form-label">Tarif mensuel (forfait) USD</label><input id="eg-tm" class="form-input right" type="number" step="any" value="${e?.tarif_mensuel_usd ?? ""}" /></div>
        <div class="form-group"><label class="form-label">Tarif heure supplémentaire USD</label><input id="eg-ts" class="form-input right" type="number" step="any" value="${e?.tarif_heure_supp_usd ?? ""}" /></div>
        <div class="form-group"><label class="form-label">Consommation (L/heure)</label><input id="eg-conso" class="form-input right" type="number" step="any" value="${e?.consommation_l_heure ?? ""}" placeholder="pour le suivi carburant" /></div></div>
      ${e ? `<label style="display:flex;align-items:center;gap:8px;font-size:13px"><input type="checkbox" id="eg-actif" ${e.actif ? "checked" : ""} style="width:auto" /> Engin actif (décochez pour le sortir du parc)</label>` : ""}
      <div class="banner"><i class="ti ti-info-circle"></i> Le forfait mensuel couvre ${enginsCfg ? fmtNum(enginsCfg.forfait_mensuel_h) : 208} h — au-delà, chaque heure est facturée au tarif d'heure supplémentaire.</div>`,
    footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="eg-ok"><i class="ti ti-check"></i> ${e ? "Enregistrer" : "Créer"}</button>`,
  });
  $("#eg-ok").onclick = async () => {
    const body = { nom: $("#eg-nom").value, categorie: $("#eg-cat").value || null,
      immatriculation: $("#eg-immat").value || null,
      tarif_mensuel_usd: +$("#eg-tm").value || 0, tarif_heure_supp_usd: +$("#eg-ts").value || 0,
      consommation_l_heure: $("#eg-conso").value === "" ? null : +$("#eg-conso").value };
    if (e) body.actif = $("#eg-actif").checked;
    try {
      await api(e ? `/engins/engins/${e.id}?societe_id=${currentSocieteId}` : `/engins/engins?societe_id=${currentSocieteId}`,
        { method: e ? "PATCH" : "POST", body });
      closeModal(); toast(e ? "Engin modifié." : "Engin créé.", "ok"); RENDER["engins-parc"]();
    } catch (err) { toast(err.message, "ko"); }
  };
}

// ── Heures prestées ──────────────────────────────────────────────────
let enginsHeuresFiltre = null;

RENDER["engins-heures"] = async () => {
  const el = $("#view-engins-heures");
  el.innerHTML = `<div class="muted">Chargement…</div>`;
  const auj = isoLocal(new Date());
  enginsHeuresFiltre ??= { engin_id: "", du: auj.slice(0, 7) + "-01", au: auj };
  const f = enginsHeuresFiltre;
  const [engins, fiches] = await Promise.all([
    api(`/engins/engins?societe_id=${currentSocieteId}&actifs=1`).catch(() => []),
    api(`/engins/prestations?societe_id=${currentSocieteId}&du=${f.du}&au=${f.au}${f.engin_id ? `&engin_id=${f.engin_id}` : ""}`).catch(() => []),
    enginsCfg ? null : chargerEnginsCfg(),
  ]);
  const totalMin = fiches.reduce((s, p) => s + p.minutes, 0);
  el.innerHTML = `<div class="section-hdr" style="margin-bottom:12px">
      <div class="section-title"><i class="ti ti-clock-hour-4"></i> Heures prestées</div>
      <div style="margin-left:auto;display:flex;gap:8px;align-items:end;flex-wrap:wrap">
        <div class="form-group" style="margin:0"><label class="form-label">Engin</label>
          <select id="eh-engin" class="form-select"><option value="">Tous</option>
          ${engins.map((e) => `<option value="${e.id}" ${f.engin_id === e.id ? "selected" : ""}>${esc(e.nom)}</option>`).join("")}</select></div>
        <div class="form-group" style="margin:0"><label class="form-label">Du</label><input id="eh-du" class="form-input" type="date" value="${f.du}" /></div>
        <div class="form-group" style="margin:0"><label class="form-label">Au</label><input id="eh-au" class="form-input" type="date" value="${f.au}" /></div>
        ${boutonsExport("eh")}
        <button class="btn btn-sm btn-primary" id="eh-new" style="height:34px"><i class="ti ti-plus"></i> Nouvelle fiche</button></div></div>
    <div class="card"><div class="card-body">${!fiches.length ? '<div class="empty"><i class="ti ti-clock-hour-4"></i>Aucune prestation sur cette période.</div>' : `
      <table><thead><tr><th>Date</th><th>Engin</th><th>Poste</th><th>Opérateur</th><th class="right">Début</th><th class="right">Fin</th>
        <th class="right">Arrêts</th><th class="right">Heures</th><th class="right">Nombre</th><th class="right">Index</th><th>Affectation</th><th></th></tr></thead><tbody>
      ${fiches.map((p) => `<tr>
        <td>${p.date}</td><td><b>${esc(p.engin)}</b></td>
        <td><span class="pill ${p.poste === "nuit" ? "st-confirme" : "st-partielle"}">${p.poste === "nuit" ? "Nuit" : "Jour"}</span></td>
        <td>${esc(p.operateur || "—")}</td>
        <td class="right">${p.heure_debut}</td><td class="right">${p.heure_fin}</td>
        <td class="right">${p.minutes_arrets ? egHM(p.minutes_arrets) : "—"}</td>
        <td class="right"><b>${p.heures_hm}</b></td>
        <td class="right">${String(p.heures_dec.toFixed(2)).replace(".", ",")}</td>
        <td class="right">${p.index_delta != null ? p.index_delta : "—"}</td>
        <td>${esc(p.affectation || "")}</td>
        <td class="right" style="white-space:nowrap">
          <button class="btn btn-sm" data-pedit="${p.id}" title="Modifier"><i class="ti ti-pencil"></i></button>
          <button class="btn btn-sm" data-pdel="${p.id}" title="Supprimer"><i class="ti ti-trash"></i></button></td></tr>`).join("")}
      </tbody><tfoot><tr><td colspan="7"><b>TOTAL — ${fiches.length} fiche(s)</b></td>
        <td class="right"><b>${egHM(totalMin)}</b></td><td class="right"><b>${egDec(totalMin)}</b></td><td colspan="3"></td></tr></tfoot></table>`}</div></div>
    <div class="banner" style="margin-top:10px"><i class="ti ti-info-circle"></i> Poste de nuit : une heure de fin plus petite que l'heure de début est comptée sur le jour suivant (ex. 18h30 → 00h30). Les arrêts (pause, panne…) sont déduits, puis le temps est arrondi à 5 minutes.</div>`;
  const maj = () => { enginsHeuresFiltre = { engin_id: $("#eh-engin").value, du: $("#eh-du").value, au: $("#eh-au").value }; RENDER["engins-heures"](); };
  $("#eh-engin").onchange = maj; $("#eh-du").onchange = maj; $("#eh-au").onchange = maj;
  $("#eh-new").onclick = () => engins.length ? prestationModal(null, engins) : toast("Créez d'abord un engin dans le parc.", "ko");
  const ehCols = ["Date", "Engin", "Poste", "Opérateur", "Début", "Fin", "Arrêts (min)", "Heures", "Heures (nombre)", "Index", "Affectation"];
  const ehLignes = fiches.map((p) => [p.date, p.engin, p.poste, p.operateur || "", p.heure_debut, p.heure_fin,
    p.minutes_arrets, p.heures_hm, p.heures_dec.toFixed(2).replace(".", ","), p.index_delta ?? "", p.affectation || ""]);
  $("#eh-xls").onclick = () => exporterExcel(`heures-prestees-${f.du}-${f.au}.csv`, ehCols, ehLignes);
  $("#eh-pdf").onclick = () => imprimerRapport("Heures prestées", `du ${f.du} au ${f.au}`, ehCols, ehLignes,
    `TOTAL : ${fiches.length} fiche(s) · ${egHM(totalMin)} soit ${egDec(totalMin)} en nombre.`);
  el.querySelectorAll("[data-pedit]").forEach((b) => b.onclick = () => prestationModal(fiches.find((p) => p.id === b.dataset.pedit), engins));
  el.querySelectorAll("[data-pdel]").forEach((b) => b.onclick = async () => {
    const p = fiches.find((x) => x.id === b.dataset.pdel);
    if (!confirm(`Supprimer la fiche du ${p.date} — ${p.engin} (${p.poste}) ?`)) return;
    try { await api(`/engins/prestations/${p.id}?societe_id=${currentSocieteId}`, { method: "DELETE" });
      toast("Fiche supprimée.", "ok"); RENDER["engins-heures"](); } catch (e) { toast(e.message, "ko"); }
  });
};

function prestationModal(p, engins) {
  const auj = isoLocal(new Date());
  modal({ wide: true,
    title: p ? "Modifier la fiche de prestation" : "Nouvelle fiche de prestation",
    body: `<div class="form-row">
        <div class="form-group"><label class="form-label">Date</label><input id="pr-date" class="form-input" type="date" value="${p?.date || auj}" /></div>
        <div class="form-group"><label class="form-label">Engin</label><select id="pr-engin" class="form-select">${engins.map((e) => `<option value="${e.id}" ${p?.engin_id === e.id ? "selected" : ""}>${esc(e.nom)}</option>`).join("")}</select></div>
        <div class="form-group"><label class="form-label">Poste</label><select id="pr-poste" class="form-select">
          <option value="jour" ${!p || p.poste === "jour" ? "selected" : ""}>Jour</option>
          <option value="nuit" ${p?.poste === "nuit" ? "selected" : ""}>Nuit</option></select></div>
        <div class="form-group"><label class="form-label">Chauffeur / opérateur</label><input id="pr-op" class="form-input" value="${esc(p?.operateur || "")}" /></div></div>
      <div class="form-row">
        <div class="form-group"><label class="form-label">Heure début</label><input id="pr-hd" class="form-input" type="time" value="${p?.heure_debut || ""}" /></div>
        <div class="form-group"><label class="form-label">Heure fin</label><input id="pr-hf" class="form-input" type="time" value="${p?.heure_fin || ""}" /></div>
        <div class="form-group"><label class="form-label">Index compteur début</label><input id="pr-id" class="form-input right" type="number" step="0.1" value="${p?.index_debut ?? ""}" /></div>
        <div class="form-group"><label class="form-label">Index compteur fin</label><input id="pr-if" class="form-input right" type="number" step="0.1" value="${p?.index_fin ?? ""}" /></div></div>
      <div class="form-group"><label class="form-label">Arrêts de travail (pauses, pannes… — déduits du temps presté)</label>
        <div id="pr-arrets"></div>
        <button type="button" class="btn btn-sm" id="pr-addarret"><i class="ti ti-plus"></i> Ajouter un arrêt</button></div>
      <div class="form-group"><label class="form-label">Affectation / nature du travail</label><input id="pr-aff" class="form-input" placeholder="ex. Chargement chaux" value="${esc(p?.affectation || "")}" /></div>
      <div class="banner" id="pr-calc"></div>`,
    footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="pr-ok"><i class="ti ti-check"></i> ${p ? "Enregistrer" : "Enregistrer la fiche"}</button>`,
  });
  const host = $("#pr-arrets");
  const lireArrets = () => [...host.querySelectorAll(".pr-arret")].map((r) => ({
    nature: r.querySelector(".pa-nat").value, debut: r.querySelector(".pa-deb").value, fin: r.querySelector(".pa-fin").value }))
    .filter((a) => a.debut && a.fin);
  const recalc = () => {
    const brut = egDuree($("#pr-hd").value, $("#pr-hf").value);
    const arrets = lireArrets().reduce((s, a) => s + egDuree(a.debut, a.fin), 0);
    const net = egArrondi(Math.max(0, brut - arrets));
    $("#pr-calc").innerHTML = `<i class="ti ti-calculator"></i> Durée brute <b>${egHM(brut)}</b> − arrêts <b>${egHM(arrets)}</b> = heures prestées <b>${egHM(net)}</b> soit <b>${egDec(net)}</b> en nombre (arrondi 5 min)`;
  };
  const addArret = (a = {}) => {
    const row = document.createElement("div");
    row.className = "pr-arret form-row";
    row.style.marginBottom = "6px";
    row.innerHTML = `
      <div class="form-group" style="margin:0"><select class="form-select pa-nat">${["Pause", "Panne", "Maintenance", "Attente", "Autre"].map((n) => `<option ${a.nature === n ? "selected" : ""}>${n}</option>`).join("")}</select></div>
      <div class="form-group" style="margin:0"><input class="form-input pa-deb" type="time" value="${a.debut || ""}" /></div>
      <div class="form-group" style="margin:0"><input class="form-input pa-fin" type="time" value="${a.fin || ""}" /></div>
      <button type="button" class="btn btn-sm pa-del" style="height:34px"><i class="ti ti-x"></i></button>`;
    row.querySelector(".pa-del").onclick = () => { row.remove(); recalc(); };
    row.querySelectorAll("input,select").forEach((i) => i.oninput = recalc);
    host.appendChild(row);
  };
  (p?.arrets || []).forEach(addArret);
  $("#pr-addarret").onclick = () => addArret();
  ["pr-hd", "pr-hf"].forEach((id) => $("#" + id).oninput = recalc);
  recalc();
  $("#pr-ok").onclick = async () => {
    const body = {
      engin_id: $("#pr-engin").value, date: $("#pr-date").value, poste: $("#pr-poste").value,
      operateur: $("#pr-op").value || null,
      heure_debut: $("#pr-hd").value, heure_fin: $("#pr-hf").value,
      index_debut: $("#pr-id").value === "" ? null : +$("#pr-id").value,
      index_fin: $("#pr-if").value === "" ? null : +$("#pr-if").value,
      affectation: $("#pr-aff").value || null, arrets: lireArrets() };
    try {
      await api(p ? `/engins/prestations/${p.id}?societe_id=${currentSocieteId}` : `/engins/prestations?societe_id=${currentSocieteId}`,
        { method: p ? "PATCH" : "POST", body });
      closeModal(); toast(p ? "Fiche modifiée." : "Fiche enregistrée.", "ok"); RENDER["engins-heures"]();
    } catch (e) { toast(e.message, "ko"); }
  };
}

// ── RPE & facturation ────────────────────────────────────────────────
let enginsRpeYm = null;

RENDER["engins-rpe"] = async () => {
  const el = $("#view-engins-rpe");
  el.innerHTML = `<div class="muted">Chargement…</div>`;
  enginsRpeYm ??= isoLocal(new Date()).slice(0, 7);
  let d;
  try { d = await api(`/engins/rpe?societe_id=${currentSocieteId}&ym=${enginsRpeYm}`); }
  catch (e) { el.innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }
  enginsCfg = d.reglages;
  const dec = (x) => x.toFixed(2).replace(".", ",");
  const usd = (x) => fmtNum(x) + " $";
  const t = d.totaux;
  el.innerHTML = `<div class="section-hdr" style="margin-bottom:12px">
      <div class="section-title"><i class="ti ti-file-invoice"></i> RPE ${esc(d.numero_rpe)}</div>
      <div style="margin-left:auto;display:flex;gap:8px;align-items:center">
        <input id="rp-ym" class="form-input" type="month" value="${enginsRpeYm}" style="width:170px" />
        ${boutonsExport("rp")}
        ${has("DFI", "PRESIDENT", "ADMIN_SYS") ? `<button class="btn btn-sm" id="rp-cfg" title="Réglages du module"><i class="ti ti-settings"></i></button>` : ""}
        ${d.facture
          ? `<span class="pill st-payee" title="Total ${fmtNum(d.facture.total_ttc)} $ TTC"><i class="ti ti-check"></i> Facturé — ${esc(d.facture.numero)}</span>`
          : (has("DFI", "DG", "COMPTABLE") ? `<button class="btn btn-sm btn-primary" id="rp-fact"><i class="ti ti-file-invoice"></i> Facturer le mois</button>` : "")}</div></div>
    ${d.reglages.locataire ? `<div class="muted" style="margin-bottom:8px">Locataire : <b>${esc(d.reglages.locataire)}</b> · Forfait ${fmtNum(d.reglages.forfait_mensuel_h)} h/mois/engin · arrondi 5 min (${{ nearest: "au plus proche", down: "vers le bas", up: "vers le haut" }[d.reglages.arrondi] || d.reglages.arrondi})</div>` : ""}
    <div class="card"><div class="card-body">${!d.rows.length ? '<div class="empty"><i class="ti ti-backhoe"></i>Aucun engin actif dans le parc.</div>' : `
      <table><thead><tr><th>Engin</th><th class="right">Jour</th><th class="right">Nombre</th><th class="right">Nuit</th><th class="right">Nombre</th>
        <th class="right">Total</th><th class="right">Nombre</th><th class="right">Forfait h</th><th class="right">H. supp.</th><th class="right">Nombre</th>
        <th class="right">Forfait $</th><th class="right">H. supp. $</th><th class="right">Total $</th></tr></thead><tbody>
      ${d.rows.map((r) => `<tr>
        <td><b>${esc(r.engin)}</b>${r.categorie ? `<div class="muted" style="font-size:11px">${esc(r.categorie)}</div>` : ""}</td>
        <td class="right">${r.jour_hm}</td><td class="right">${dec(r.jour_dec)}</td>
        <td class="right">${r.nuit_hm}</td><td class="right">${dec(r.nuit_dec)}</td>
        <td class="right"><b>${r.total_hm}</b></td><td class="right"><b>${dec(r.total_dec)}</b></td>
        <td class="right">${fmtNum(d.reglages.forfait_mensuel_h)}</td>
        <td class="right">${r.supp_dec ? r.supp_hm : "—"}</td><td class="right">${r.supp_dec ? "<b>" + dec(r.supp_dec) + "</b>" : "—"}</td>
        <td class="right">${usd(r.montant_forfait)}</td><td class="right">${usd(r.montant_supp)}</td>
        <td class="right"><b>${usd(r.montant_total)}</b></td></tr>`).join("")}
      </tbody><tfoot><tr><td><b>TOTAL</b></td>
        <td colspan="2" class="right"><b>${dec(t.jour_dec)}</b></td><td colspan="2" class="right"><b>${dec(t.nuit_dec)}</b></td>
        <td colspan="2" class="right"><b>${dec(t.total_dec)}</b></td><td></td>
        <td colspan="2" class="right"><b>${dec(t.supp_dec)}</b></td>
        <td class="right"><b>${usd(t.montant_forfait)}</b></td><td class="right"><b>${usd(t.montant_supp)}</b></td>
        <td class="right"><b>${usd(t.montant_total)}</b></td></tr></tfoot></table>`}</div></div>
    <div class="banner" style="margin-top:10px"><i class="ti ti-info-circle"></i> Les colonnes « Nombre » sont la conversion en heures décimales (8h30 → 8,50), arrondie aux multiples de 5 minutes — c'est la base de la facturation. Heures supplémentaires = total presté − forfait mensuel. Montants hors TVA (la TVA est ajoutée sur la facture).</div>`;
  $("#rp-ym").onchange = (e) => { enginsRpeYm = e.target.value || enginsRpeYm; RENDER["engins-rpe"](); };
  $("#rp-cfg") && ($("#rp-cfg").onclick = () => enginsConfigModal(d.reglages));
  $("#rp-fact") && ($("#rp-fact").onclick = () => facturerEnginsModal(d));
  const rpeCols = ["Engin", "Jour (h:min)", "Jour (nombre)", "Nuit (h:min)", "Nuit (nombre)",
    "Total (h:min)", "Total (nombre)", "Forfait h", "H. supp. (h:min)", "H. supp. (nombre)",
    "Forfait $", "H. supp. $", "Total $"];
  const rpeLignes = d.rows.map((r) => [r.engin, r.jour_hm, dec(r.jour_dec), r.nuit_hm, dec(r.nuit_dec),
    r.total_hm, dec(r.total_dec), d.reglages.forfait_mensuel_h, r.supp_hm, dec(r.supp_dec),
    r.montant_forfait, r.montant_supp, r.montant_total]);
  $("#rp-xls").onclick = () => exporterExcel(`RPE-${enginsRpeYm}.csv`, rpeCols, rpeLignes);
  $("#rp-pdf").onclick = () => imprimerRapport(`Relevé de Prestation Engins ${d.numero_rpe}`,
    `${enginsRpeYm}${d.reglages.locataire ? " · Locataire : " + d.reglages.locataire : ""}`,
    rpeCols, rpeLignes,
    `TOTAL : ${dec(t.total_dec)} h prestées · ${dec(t.supp_dec)} h supplémentaires · <b>${fmtNum(t.montant_total)} $ HT</b>. Colonnes « nombre » = heures décimales arrondies aux multiples de 5 minutes (base de facturation).`);
};

function enginsConfigModal(cfg) {
  modal({
    title: "Réglages — location d'engins",
    body: `<div class="form-row">
        <div class="form-group"><label class="form-label">Forfait mensuel (heures/engin)</label><input id="ec-forfait" class="form-input right" type="number" step="any" value="${cfg.forfait_mensuel_h}" /></div>
        <div class="form-group"><label class="form-label">Arrondi (pas de 5 min)</label><select id="ec-arrondi" class="form-select">
          <option value="nearest" ${cfg.arrondi === "nearest" ? "selected" : ""}>Au plus proche</option>
          <option value="down" ${cfg.arrondi === "down" ? "selected" : ""}>Vers le bas</option>
          <option value="up" ${cfg.arrondi === "up" ? "selected" : ""}>Vers le haut</option></select></div></div>
      <div class="form-row">
        <div class="form-group"><label class="form-label">Préfixe des n° RPE</label><input id="ec-prefix" class="form-input" value="${esc(cfg.rpe_prefix)}" /></div>
        <div class="form-group"><label class="form-label">Locataire (affiché sur le RPE)</label><input id="ec-loc" class="form-input" value="${esc(cfg.locataire || "")}" placeholder="ex. GCK / Production" /></div></div>`,
    footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="ec-ok"><i class="ti ti-check"></i> Enregistrer</button>`,
  });
  $("#ec-ok").onclick = async () => {
    try {
      await api(`/engins/config?societe_id=${currentSocieteId}`, { method: "POST", body: {
        forfait_mensuel_h: +$("#ec-forfait").value, arrondi: $("#ec-arrondi").value,
        rpe_prefix: $("#ec-prefix").value, locataire: $("#ec-loc").value } });
      closeModal(); toast("Réglages enregistrés.", "ok"); RENDER["engins-rpe"]();
    } catch (e) { toast(e.message, "ko"); }
  };
}

async function facturerEnginsModal(d) {
  const clients = await api(`/commercial/tiers?societe_id=${currentSocieteId}&type=client`).catch(() => []);
  if (!clients.length) { toast("Créez d'abord le client (locataire) dans Tiers & articles.", "ko"); return; }
  modal({
    title: `Facturer ${enginsRpeYm}`,
    body: `<div class="form-group"><label class="form-label">Client (locataire)</label>
        <select id="fe-tiers" class="form-select">${clients.map((c) => `<option value="${c.id}">${esc(Catalogue.label(c))}</option>`).join("")}</select></div>
      <div class="banner"><i class="ti ti-info-circle"></i> Une facture de vente sera créée : le forfait mensuel de chaque engin actif + les heures supplémentaires au tarif de l'engin, soit <b>${fmtNum(d.totaux.montant_total)} $ HT</b> (+ TVA). L'écriture comptable est passée automatiquement (411 / produit location / TVA collectée).</div>`,
    footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="fe-ok"><i class="ti ti-file-invoice"></i> Créer la facture</button>`,
  });
  $("#fe-ok").onclick = async () => {
    try {
      const r = await api(`/engins/facturer?societe_id=${currentSocieteId}`, { method: "POST",
        body: { ym: enginsRpeYm, tiers_id: $("#fe-tiers").value } });
      closeModal(); toast(`Facture ${r.facture.numero} créée — ${fmtNum(r.facture.total_ttc)} $ TTC.`, "ok");
      RENDER["engins-rpe"]();
    } catch (e) { toast(e.message, "ko"); }
  };
}

// ═════════════════════════════════════════════════════════════════════
// MAINTENANCE — métier séparé : parc transversal, plans d'entretien,
// échéances calculées sur l'usage réel, interventions mutualisées
// ═════════════════════════════════════════════════════════════════════
const PLAN_ST = { ok: ["À jour", "st-payee"], bientot: ["Bientôt", "st-partielle"], echu: ["Échu", "st-due"] };
const PERIODICITE_LBL = { heures: "h", courses: "courses", km: "km", jours: "jours" };

function usageLigne(v) {
  const u = v.usage || {};
  const bouts = [];
  if (v.type === "engin") {
    bouts.push(`${String(u.heures ?? 0).replace(".", ",")} h prestées`);
    if (u.dernier_index != null) bouts.push(`index ${String(u.dernier_index).replace(".", ",")}`);
  } else {
    bouts.push(`${u.courses ?? 0} course(s)`);
    bouts.push(`${String(u.heures ?? 0).replace(".", ",")} h de route`);
    if (u.km) bouts.push(`${fmtNum(u.km)} km`);
  }
  return bouts.join(" · ");
}

RENDER["maintenance-parc"] = async () => {
  const el = $("#view-maintenance-parc");
  el.innerHTML = `<div class="muted">Chargement…</div>`;
  let d;
  try { d = await api(`/maintenance/parc?societe_id=${currentSocieteId}`); }
  catch (e) { el.innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }
  const vs = d.vehicules;
  const al = d.alertes;
  el.innerHTML = `
    ${al.echu || al.bientot ? `<div class="banner" style="margin-bottom:12px"><i class="ti ti-alert-triangle"></i>
      ${al.echu ? `<b>${al.echu} entretien(s) échu(s)</b>` : ""}${al.echu && al.bientot ? " · " : ""}${al.bientot ? `${al.bientot} à prévoir bientôt` : ""} — planifiez-les depuis les cartes ci-dessous.</div>` : ""}
    <div class="section-hdr" style="margin-bottom:12px">
      <div class="section-title"><i class="ti ti-gauge"></i> Parc suivi (${vs.length} véhicule(s))</div></div>
    ${!vs.length ? '<div class="empty"><i class="ti ti-gauge"></i>Aucun véhicule — créez des camions (Transport) ou des engins (Location d\'engins).</div>' : `
    <div class="caisse-cards">
      ${vs.map((v) => { const [sl, sc] = (v.type === "camion" ? CAMION_ST : ENGIN_ST)[v.statut] || [v.statut, ""]; return `
        <div class="caisse-card">
          <div class="cc-top"><b>${esc(v.nom)}</b> <span class="tag">${v.type === "camion" ? "camion" : "engin"}</span>
            <span class="pill ${sc}" style="margin-left:auto">${sl}</span>
            <button class="btn btn-sm" data-hist="${v.type}:${v.id}" title="Historique & coûts"><i class="ti ti-history"></i></button></div>
          <div class="muted" style="font-size:12px;margin:4px 0">${esc(v.detail || "")}${v.detail ? " · " : ""}${usageLigne(v)}
            ${v.interventions_ouvertes ? ` · <i class="ti ti-tool"></i> ${v.interventions_ouvertes} intervention(s) ouverte(s)` : ""}</div>
          ${v.motif_immobilisation ? `<div class="muted" style="font-size:11px"><i class="ti ti-alert-triangle"></i> ${esc(v.motif_immobilisation)}</div>` : ""}
          ${v.plans.map((p) => { const e = p.etat; const [pl, pc] = PLAN_ST[e.statut]; return `
            <div style="border-top:1px solid var(--grayl);margin-top:8px;padding-top:8px">
              <div style="display:flex;align-items:center;gap:6px;font-size:13px">
                <b>${esc(p.libelle)}</b><span class="pill ${pc}">${pl}</span>
                <span style="margin-left:auto;white-space:nowrap">
                  ${e.intervention_ouverte
                    ? `<span class="tag" title="intervention ouverte">${esc(e.intervention_ouverte)}</span>`
                    : `<button class="btn btn-sm" data-planif="${p.id}" title="Créer l'intervention d'entretien"><i class="ti ti-calendar-plus"></i></button>`}
                  <button class="btn btn-sm" data-pedit="${p.id}" title="Modifier le plan"><i class="ti ti-pencil"></i></button>
                  <button class="btn btn-sm" data-pdel="${p.id}" title="Supprimer le plan"><i class="ti ti-trash"></i></button></span></div>
              <div class="muted" style="font-size:11px;margin-top:2px">${String(e.consomme).replace(".", ",")} / ${String(e.periode).replace(".", ",")} ${PERIODICITE_LBL[p.periodicite_type]} depuis le dernier entretien${p.derniere_date ? ` (${p.derniere_date})` : ""}</div>
              <div style="height:5px;background:var(--grayl);border-radius:3px;margin-top:3px"><div style="height:5px;border-radius:3px;width:${e.pct}%;background:${e.statut === "echu" ? "var(--r)" : e.statut === "bientot" ? "var(--a)" : "var(--g)"}"></div></div>
            </div>`; }).join("")}
          <div style="margin-top:8px"><button class="btn btn-sm" data-newplan="${v.type}:${v.id}"><i class="ti ti-plus"></i> Plan d'entretien</button></div>
        </div>`; }).join("")}
    </div>`}`;
  const refresh = () => RENDER["maintenance-parc"]();
  const plansParId = {};
  vs.forEach((v) => v.plans.forEach((p) => { plansParId[p.id] = { plan: p, veh: v }; }));
  el.querySelectorAll("[data-newplan]").forEach((b) => b.onclick = () => {
    const [type, id] = b.dataset.newplan.split(":");
    planModal(null, { type, id, nom: vs.find((v) => v.id === id)?.nom }, refresh);
  });
  el.querySelectorAll("[data-pedit]").forEach((b) => b.onclick = () => {
    const { plan, veh } = plansParId[b.dataset.pedit];
    planModal(plan, { type: veh.type, id: veh.id, nom: veh.nom }, refresh);
  });
  el.querySelectorAll("[data-pdel]").forEach((b) => b.onclick = async () => {
    const { plan, veh } = plansParId[b.dataset.pdel];
    if (!confirm(`Supprimer le plan « ${plan.libelle} » de ${veh.nom} ?`)) return;
    try { await api(`/maintenance/plans/${plan.id}?societe_id=${currentSocieteId}`, { method: "DELETE" });
      toast("Plan supprimé.", "ok"); refresh(); } catch (e) { toast(e.message, "ko"); }
  });
  el.querySelectorAll("[data-planif]").forEach((b) => b.onclick = () => {
    const { plan, veh } = plansParId[b.dataset.planif];
    planifierModal(plan, veh, refresh);
  });
  el.querySelectorAll("[data-hist]").forEach((b) => b.onclick = () => {
    const [type, id] = b.dataset.hist.split(":");
    historiqueVehiculeModal(vs.find((v) => v.id === id && v.type === type));
  });
};

async function historiqueVehiculeModal(v) {
  const inters = await api(`/transport/interventions?societe_id=${currentSocieteId}&${v.type === "engin" ? "engin_id" : "camion_id"}=${v.id}`).catch(() => []);
  const terminees = inters.filter((i) => i.statut === "terminee");
  const coutTotal = terminees.reduce((s, i) => s + (i.cout_reel || 0), 0);
  const joursImmo = terminees.filter((i) => i.immobilise && i.date_fin).reduce((s, i) =>
    s + Math.max(0, Math.round((new Date(i.date_fin) - new Date(i.date_signalement)) / 86400000)), 0);
  modal({ wide: true,
    title: `Historique maintenance — ${v.nom}`,
    body: `<div class="kpi-row" style="margin-bottom:12px">
        <div class="kpi-card"><div class="kpi-label">Interventions</div><div class="kpi-val">${inters.length}</div><div class="kpi-sub">${terminees.length} terminée(s)</div></div>
        <div class="kpi-card" style="--accent:var(--a)"><div class="kpi-label">Coût total</div><div class="kpi-val">${fmtNum(coutTotal)} $</div><div class="kpi-sub">coûts réels enregistrés</div></div>
        <div class="kpi-card" style="--accent:var(--r)"><div class="kpi-label">Jours d'immobilisation</div><div class="kpi-val">${joursImmo}</div><div class="kpi-sub">cumul des arrêts terminés</div></div>
        <div class="kpi-card" style="--accent:var(--g)"><div class="kpi-label">Usage</div><div class="kpi-val" style="font-size:15px;line-height:1.3">${usageLigne(v)}</div><div class="kpi-sub">depuis les modules opérationnels</div></div></div>
      ${!inters.length ? '<div class="empty">Aucune intervention enregistrée pour ce véhicule.</div>' :
        `<table><thead><tr><th>N°</th><th>Type</th><th>Description</th><th>Prestataire</th><th>Signalée</th><th>Terminée</th><th class="right">Coût réel $</th><th>Statut</th></tr></thead><tbody>
        ${inters.map((i) => { const [sl, sc] = INTER_ST[i.statut] || [i.statut, "st-partielle"]; return `<tr ${i.statut === "terminee" ? 'style="opacity:.75"' : ""}>
          <td class="num-cell">${esc(i.numero)}</td><td>${esc(i.type)}</td><td>${esc(i.description)}</td>
          <td>${esc(i.prestataire || "—")}</td><td>${i.date_signalement}</td><td>${i.date_fin || "—"}</td>
          <td class="right">${i.cout_reel != null ? fmtNum(i.cout_reel) : "—"}</td>
          <td><span class="pill ${sc}">${sl}</span></td></tr>`; }).join("")}
        </tbody></table>`}`,
    footer: `<button class="btn" onclick="closeModal()">Fermer</button>`,
  });
}

function planModal(plan, veh, refresh) {
  modal({
    title: plan ? `Modifier le plan — ${veh.nom}` : `Nouveau plan d'entretien — ${veh.nom}`,
    body: `<div class="form-group"><label class="form-label">Libellé</label>
        <input id="pe-lib" class="form-input" placeholder="ex. Vidange moteur" value="${esc(plan?.libelle || "")}" /></div>
      <div class="form-row">
        <div class="form-group"><label class="form-label">Périodicité</label>
          <select id="pe-type" class="form-select" ${plan ? "disabled" : ""}>
            <option value="heures" ${plan?.periodicite_type === "heures" || !plan ? "selected" : ""}>${veh.type === "engin" ? "Toutes les X heures prestées" : "Toutes les X heures de route"}</option>
            ${veh.type === "camion" ? `<option value="courses" ${plan?.periodicite_type === "courses" ? "selected" : ""}>Toutes les X courses</option>
            <option value="km" ${plan?.periodicite_type === "km" ? "selected" : ""}>Tous les X km parcourus</option>` : ""}
            <option value="jours" ${plan?.periodicite_type === "jours" ? "selected" : ""}>Tous les X jours</option></select></div>
        <div class="form-group"><label class="form-label">Valeur (X)</label>
          <input id="pe-val" class="form-input right" type="number" step="any" value="${plan?.periodicite_valeur ?? ""}" placeholder="ex. 250" /></div></div>
      <div class="form-group"><label class="form-label">Note (huile, filtres, référence…)</label>
        <input id="pe-note" class="form-input" value="${esc(plan?.note || "")}" /></div>
      <div class="banner"><i class="ti ti-info-circle"></i> L'échéance se calcule sur l'usage réel (heures prestées des fiches, courses effectuées). À la clôture de chaque entretien, le compteur repart de zéro.</div>`,
    footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="pe-ok"><i class="ti ti-check"></i> ${plan ? "Enregistrer" : "Créer"}</button>`,
  });
  $("#pe-ok").onclick = async () => {
    try {
      if (plan) {
        await api(`/maintenance/plans/${plan.id}?societe_id=${currentSocieteId}`, { method: "PATCH",
          body: { libelle: $("#pe-lib").value, periodicite_valeur: +$("#pe-val").value, note: $("#pe-note").value } });
      } else {
        const body = { libelle: $("#pe-lib").value, periodicite_type: $("#pe-type").value,
          periodicite_valeur: +$("#pe-val").value, note: $("#pe-note").value };
        body[veh.type === "engin" ? "engin_id" : "camion_id"] = veh.id;
        await api(`/maintenance/plans?societe_id=${currentSocieteId}`, { method: "POST", body });
      }
      closeModal(); toast(plan ? "Plan modifié." : "Plan créé.", "ok"); refresh();
    } catch (e) { toast(e.message, "ko"); }
  };
}

function planifierModal(plan, veh, refresh) {
  modal({
    title: `Entretien « ${plan.libelle} » — ${veh.nom}`,
    body: `<div class="form-row">
        <div class="form-group"><label class="form-label">Date prévue (vide = démarrer maintenant)</label>
          <input id="pf-date" class="form-input" type="date" /></div>
        <div class="form-group"><label class="form-label">Prestataire</label><input id="pf-prest" class="form-input" /></div>
        <div class="form-group"><label class="form-label">Coût estimé USD</label><input id="pf-cout" class="form-input right" type="number" step="any" /></div></div>
      <label style="display:flex;align-items:center;gap:8px;font-size:13px"><input type="checkbox" id="pf-immo" checked style="width:auto" /> Immobiliser le véhicule pendant l'entretien</label>
      <div class="banner" style="margin-top:10px"><i class="ti ti-info-circle"></i> Une date future = intervention planifiée (le véhicule reste disponible jusqu'au démarrage). À la clôture, le compteur du plan repartira de l'usage actuel.</div>`,
    footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="pf-ok"><i class="ti ti-calendar-plus"></i> Créer l'intervention</button>`,
  });
  $("#pf-ok").onclick = async () => {
    try {
      const r = await api(`/maintenance/plans/${plan.id}/planifier?societe_id=${currentSocieteId}`, { method: "POST",
        body: { date_prevue: $("#pf-date").value || null, prestataire: $("#pf-prest").value || null,
          cout_estime: +$("#pf-cout").value || null, immobilise: $("#pf-immo").checked } });
      closeModal(); toast(`Intervention ${r.numero} ${r.statut === "planifiee" ? "planifiée" : "démarrée"}.`, "ok"); refresh();
    } catch (e) { toast(e.message, "ko"); }
  };
}

// ── Interventions (tous véhicules) ───────────────────────────────────
let maintInterFiltre = "";

RENDER["maintenance-interventions"] = async () => {
  const el = $("#view-maintenance-interventions");
  el.innerHTML = `<div class="muted">Chargement…</div>`;
  const [inters, parc] = await Promise.all([
    api(`/transport/interventions?societe_id=${currentSocieteId}`).catch(() => []),
    api(`/maintenance/parc?societe_id=${currentSocieteId}`).catch(() => ({ vehicules: [] })),
  ]);
  const filtres = [["", "Toutes"], ["planifiee", "Planifiées"], ["en_cours", "En cours"], ["terminee", "Terminées"]];
  const liste = maintInterFiltre ? inters.filter((i) => i.statut === maintInterFiltre) : inters;
  el.innerHTML = `<div class="section-hdr" style="margin-bottom:12px">
      <div class="section-title"><i class="ti ti-tool"></i> Interventions</div>
      <div style="margin-left:auto;display:flex;gap:10px;align-items:center">
        <div class="seg">${filtres.map(([v, l]) => `<button data-mf="${v}" class="${maintInterFiltre === v ? "on" : ""}">${l}</button>`).join("")}</div>
        ${boutonsExport("mi")}
        <button class="btn btn-sm btn-primary" id="mi-new"><i class="ti ti-plus"></i> Signaler / planifier</button></div></div>
    <div class="card"><div class="card-body">${maintenanceTableHTML(liste)}</div></div>`;
  const refresh = () => RENDER["maintenance-interventions"]();
  el.querySelectorAll("[data-mf]").forEach((b) => b.onclick = () => { maintInterFiltre = b.dataset.mf; refresh(); });
  $("#mi-new").onclick = () => {
    const vs = parc.vehicules.filter((v) => v.statut !== undefined);
    if (!vs.length) { toast("Aucun véhicule dans le parc.", "ko"); return; }
    maintInterventionModal(vs, refresh);
  };
  const miCols = ["N°", "Véhicule", "Type", "Description", "Prestataire", "Prévue le", "Signalée", "Terminée", "Coût est. $", "Coût réel $", "Statut"];
  const miLignes = liste.map((i) => [i.numero, i.vehicule || "", i.type, i.description, i.prestataire || "",
    i.date_prevue || "", i.date_signalement, i.date_fin || "", i.cout_estime ?? "", i.cout_reel ?? "",
    (INTER_ST[i.statut] || [i.statut])[0]]);
  $("#mi-xls").onclick = () => exporterExcel("interventions-maintenance.csv", miCols, miLignes);
  $("#mi-pdf").onclick = () => imprimerRapport("Interventions de maintenance",
    maintInterFiltre ? (INTER_ST[maintInterFiltre] || [maintInterFiltre])[0] : "toutes",
    miCols, miLignes,
    `${liste.length} intervention(s) · coût réel total : ${fmtNum(liste.reduce((s2, i) => s2 + (i.cout_reel || 0), 0))} $.`);
  bindMaintenance(el, refresh);
};

function maintInterventionModal(vehicules, refresh) {
  modal({
    title: "Signaler une panne / planifier un entretien",
    body: `<div class="form-row">
        <div class="form-group"><label class="form-label">Véhicule</label><select id="mi-veh" class="form-select">
          ${vehicules.map((v) => `<option value="${v.type}:${v.id}">${esc(v.nom)} (${v.type === "camion" ? "camion" : "engin"})</option>`).join("")}</select></div>
        <div class="form-group"><label class="form-label">Type</label><select id="mi-type" class="form-select">
          <option value="reparation">Réparation (panne)</option><option value="entretien">Entretien préventif</option>
          <option value="controle">Contrôle technique</option><option value="accident">Accident</option></select></div></div>
      <div class="form-group"><label class="form-label">Description</label><input id="mi-desc" class="form-input" /></div>
      <div class="form-row">
        <div class="form-group"><label class="form-label">Prestataire</label><input id="mi-prest" class="form-input" /></div>
        <div class="form-group"><label class="form-label">Coût estimé USD</label><input id="mi-cout" class="form-input right" type="number" step="any" /></div>
        <div class="form-group"><label class="form-label">Planifier pour le (facultatif)</label><input id="mi-date" class="form-input" type="date" /></div></div>
      <label style="display:flex;align-items:center;gap:8px;font-size:13px"><input type="checkbox" id="mi-immo" checked style="width:auto" /> Immobiliser le véhicule pendant l'intervention</label>`,
    footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="mi-ok"><i class="ti ti-tool"></i> Enregistrer</button>`,
  });
  $("#mi-ok").onclick = async () => {
    try {
      const [type, id] = $("#mi-veh").value.split(":");
      const body = { type: $("#mi-type").value, description: $("#mi-desc").value,
        prestataire: $("#mi-prest").value || null, cout_estime: +$("#mi-cout").value || null,
        date_prevue: $("#mi-date").value || null, immobilise: $("#mi-immo").checked };
      body[type === "engin" ? "engin_id" : "camion_id"] = id;
      await api(`/transport/interventions?societe_id=${currentSocieteId}`, { method: "POST", body });
      closeModal(); toast("Intervention enregistrée.", "ok"); refresh();
    } catch (e) { toast(e.message, "ko"); }
  };
}

// ═════════════════════════════════════════════════════════════════════
// DOCUMENTS & ÉCHÉANCES DE LA FLOTTE (camions, engins, chauffeurs)
// ═════════════════════════════════════════════════════════════════════
const DOC_TYPES = { assurance: "Assurance", controle_technique: "Contrôle technique",
  carte_rose: "Carte rose", vignette: "Vignette", permis: "Permis de conduire",
  certificat: "Certificat", autre: "Autre" };
const DOC_ST = { echu: ["Échu", "st-due"], bientot: ["Expire bientôt", "st-partielle"],
  valide: ["Valide", "st-payee"], permanent: ["Sans échéance", "st-brouillon"] };

RENDER["flotte-documents"] = async () => {
  const el = $("#view-flotte-documents");
  el.innerHTML = `<div class="muted">Chargement…</div>`;
  const [d, camions, engins, chauffeurs] = await Promise.all([
    api(`/flotte/documents?societe_id=${currentSocieteId}`).catch(() => ({ documents: [], alertes: { echu: 0, bientot: 0 } })),
    api(`/transport/camions?societe_id=${currentSocieteId}`).catch(() => []),
    api(`/engins/engins?societe_id=${currentSocieteId}&actifs=1`).catch(() => []),
    api(`/transport/chauffeurs?societe_id=${currentSocieteId}`).catch(() => []),
  ]);
  const porteurs = [
    ...camions.filter((c) => c.actif).map((c) => ({ cle: `camion_id:${c.id}`, nom: `${c.immatriculation} (camion)` })),
    ...engins.map((e) => ({ cle: `engin_id:${e.id}`, nom: `${e.nom} (engin)` })),
    ...chauffeurs.map((c) => ({ cle: `chauffeur_id:${c.id}`, nom: `${c.nom} (chauffeur)` })),
  ];
  const docs = d.documents;
  el.innerHTML = `
    ${d.alertes.echu || d.alertes.bientot ? `<div class="banner" style="margin-bottom:12px"><i class="ti ti-alert-triangle"></i>
      ${d.alertes.echu ? `<b>${d.alertes.echu} document(s) échu(s)</b>` : ""}${d.alertes.echu && d.alertes.bientot ? " · " : ""}${d.alertes.bientot ? `${d.alertes.bientot} expirent sous 30 jours` : ""} — renouvelez-les et mettez à jour la date d'expiration.</div>` : ""}
    <div class="section-hdr" style="margin-bottom:12px">
      <div class="section-title"><i class="ti ti-license"></i> Documents (${docs.length})</div>
      <div style="margin-left:auto;display:flex;gap:8px">${boutonsExport("df")}
      <button class="btn btn-sm btn-primary" id="df-new"><i class="ti ti-plus"></i> Nouveau document</button></div></div>
    <div class="card"><div class="card-body">${!docs.length ? '<div class="empty"><i class="ti ti-license"></i>Aucun document — enregistrez assurances, contrôles techniques, permis…</div>' : `
      <table><thead><tr><th>Porteur</th><th>Type</th><th>Libellé</th><th>N°</th><th>Émis le</th><th>Expire le</th><th>État</th><th class="right">Fichiers</th><th></th></tr></thead><tbody>
      ${docs.map((doc) => { const [sl, sc] = DOC_ST[doc.etat.statut]; return `<tr>
        <td><b>${esc(doc.porteur || "—")}</b> <span class="tag">${doc.cible}</span></td>
        <td>${DOC_TYPES[doc.type_document] || esc(doc.type_document)}</td>
        <td>${esc(doc.libelle)}${doc.note ? `<div class="muted" style="font-size:11px">${esc(doc.note)}</div>` : ""}</td>
        <td class="num-cell">${esc(doc.numero || "—")}</td>
        <td>${doc.date_emission || "—"}</td>
        <td>${doc.date_expiration || "—"}</td>
        <td><span class="pill ${sc}">${sl}</span>${doc.etat.jours_restants != null && doc.etat.statut !== "echu" ? `<div class="muted" style="font-size:11px">${doc.etat.jours_restants} j restants</div>` : ""}</td>
        <td class="right"><button class="btn btn-sm" data-dpj="${doc.id}" title="Pièces jointes (scans)"><i class="ti ti-paperclip"></i> ${doc.nb_pieces || ""}</button></td>
        <td class="right" style="white-space:nowrap">
          <button class="btn btn-sm" data-dedit="${doc.id}" title="Modifier / renouveler"><i class="ti ti-pencil"></i></button>
          <button class="btn btn-sm" data-ddel="${doc.id}" title="Supprimer"><i class="ti ti-trash"></i></button></td></tr>`; }).join("")}
      </tbody></table>`}</div></div>
    <div class="banner" style="margin-top:10px"><i class="ti ti-info-circle"></i> Pour renouveler un document, modifiez simplement sa date d'expiration (✎) — l'historique des fichiers scannés reste attaché. Alerte automatique 30 jours avant l'échéance.</div>`;
  const refresh = () => RENDER["flotte-documents"]();
  $("#df-new").onclick = () => porteurs.length ? documentModal(null, porteurs, refresh)
    : toast("Créez d'abord un camion, un engin ou un chauffeur.", "ko");
  const dfCols = ["Porteur", "Type", "Type de document", "Libellé", "N°", "Émis le", "Expire le", "État", "Jours restants"];
  const dfLignes = docs.map((doc) => [doc.porteur || "", doc.cible, DOC_TYPES[doc.type_document] || doc.type_document,
    doc.libelle, doc.numero || "", doc.date_emission || "", doc.date_expiration || "",
    DOC_ST[doc.etat.statut][0], doc.etat.jours_restants ?? ""]);
  $("#df-xls").onclick = () => exporterExcel("documents-flotte.csv", dfCols, dfLignes);
  $("#df-pdf").onclick = () => imprimerRapport("Documents & échéances de la flotte", "",
    dfCols, dfLignes,
    `${d.alertes.echu} document(s) échu(s) · ${d.alertes.bientot} expirent sous 30 jours.`);
  el.querySelectorAll("[data-dedit]").forEach((b) => b.onclick = () =>
    documentModal(docs.find((x) => x.id === b.dataset.dedit), porteurs, refresh));
  el.querySelectorAll("[data-dpj]").forEach((b) => b.onclick = () => {
    const doc = docs.find((x) => x.id === b.dataset.dpj);
    piecesModal("document_flotte", doc.id, `Fichiers — ${doc.libelle}`);
  });
  el.querySelectorAll("[data-ddel]").forEach((b) => b.onclick = async () => {
    const doc = docs.find((x) => x.id === b.dataset.ddel);
    if (!confirm(`Supprimer « ${doc.libelle} » (${doc.porteur}) ?`)) return;
    try { await api(`/flotte/documents/${doc.id}?societe_id=${currentSocieteId}`, { method: "DELETE" });
      toast("Document supprimé.", "ok"); refresh(); } catch (e) { toast(e.message, "ko"); }
  });
};

function documentModal(doc, porteurs, refresh) {
  const cleActuelle = doc ? (doc.camion_id ? `camion_id:${doc.camion_id}` : doc.engin_id ? `engin_id:${doc.engin_id}` : `chauffeur_id:${doc.chauffeur_id}`) : null;
  modal({
    title: doc ? `Modifier — ${doc.libelle}` : "Nouveau document",
    body: `<div class="form-row">
        <div class="form-group"><label class="form-label">Porteur (véhicule ou chauffeur)</label>
          <select id="df-port" class="form-select" ${doc ? "disabled" : ""}>${porteurs.map((p) => `<option value="${p.cle}" ${cleActuelle === p.cle ? "selected" : ""}>${esc(p.nom)}</option>`).join("")}</select></div>
        <div class="form-group"><label class="form-label">Type</label>
          <select id="df-type" class="form-select">${Object.entries(DOC_TYPES).map(([v, l]) => `<option value="${v}" ${doc?.type_document === v ? "selected" : ""}>${l}</option>`).join("")}</select></div></div>
      <div class="form-row">
        <div class="form-group"><label class="form-label">Libellé</label><input id="df-lib" class="form-input" placeholder="ex. Assurance RC 2026" value="${esc(doc?.libelle || "")}" /></div>
        <div class="form-group"><label class="form-label">N° du document</label><input id="df-num" class="form-input" value="${esc(doc?.numero || "")}" /></div></div>
      <div class="form-row">
        <div class="form-group"><label class="form-label">Date d'émission</label><input id="df-emis" class="form-input" type="date" value="${doc?.date_emission || ""}" /></div>
        <div class="form-group"><label class="form-label">Date d'expiration (vide = permanent)</label><input id="df-exp" class="form-input" type="date" value="${doc?.date_expiration || ""}" /></div></div>
      <div class="form-group"><label class="form-label">Note</label><input id="df-note" class="form-input" value="${esc(doc?.note || "")}" /></div>
      ${doc ? "" : '<div class="banner"><i class="ti ti-info-circle"></i> Après création, joignez le scan du document via le bouton 📎 de la liste.</div>'}`,
    footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="df-ok"><i class="ti ti-check"></i> ${doc ? "Enregistrer" : "Créer"}</button>`,
  });
  $("#df-ok").onclick = async () => {
    const body = { type_document: $("#df-type").value, libelle: $("#df-lib").value,
      numero: $("#df-num").value || null, date_emission: $("#df-emis").value || null,
      date_expiration: $("#df-exp").value || null, note: $("#df-note").value || null };
    if (!doc) {
      const [cle, id] = $("#df-port").value.split(":");
      body[cle] = id;
    }
    try {
      await api(doc ? `/flotte/documents/${doc.id}?societe_id=${currentSocieteId}` : `/flotte/documents?societe_id=${currentSocieteId}`,
        { method: doc ? "PATCH" : "POST", body });
      closeModal(); toast(doc ? "Document mis à jour." : "Document créé.", "ok"); refresh();
    } catch (e) { toast(e.message, "ko"); }
  };
}

// ═════════════════════════════════════════════════════════════════════
// SUIVI CARBURANT — pleins, conso réelle vs théorique, coût unitaire
// ═════════════════════════════════════════════════════════════════════
const CARBU_ST = { ok: ["Normale", "st-payee"], surconso: ["Surconsommation", "st-due"],
  inconnu: ["À compléter", "st-brouillon"] };
let carbuFiltre = null;

RENDER.carburant = async () => {
  const el = $("#view-carburant");
  el.innerHTML = `<div class="muted">Chargement…</div>`;
  const auj = isoLocal(new Date());
  carbuFiltre ??= { du: auj.slice(0, 7) + "-01", au: auj };
  const f = carbuFiltre;
  const [rap, pleins, camions, engins] = await Promise.all([
    api(`/carburant/rapport?societe_id=${currentSocieteId}&du=${f.du}&au=${f.au}`).catch(() => ({ rapport: [], totaux: { pleins: 0, litres: 0, montant: 0, surconso: 0 } })),
    api(`/carburant/pleins?societe_id=${currentSocieteId}&du=${f.du}&au=${f.au}`).catch(() => []),
    api(`/transport/camions?societe_id=${currentSocieteId}`).catch(() => []),
    api(`/engins/engins?societe_id=${currentSocieteId}&actifs=1`).catch(() => []),
  ]);
  const porteurs = [
    ...camions.filter((c) => c.actif).map((c) => ({ cle: `camion_id:${c.id}`, nom: `${c.immatriculation} (camion)` })),
    ...engins.map((e) => ({ cle: `engin_id:${e.id}`, nom: `${e.nom} (engin)` })),
  ];
  const t = rap.totaux;
  const dec = (x) => x == null ? "—" : String(x).replace(".", ",");
  el.innerHTML = `
    ${t.surconso ? `<div class="banner" style="margin-bottom:12px"><i class="ti ti-alert-triangle"></i> <b>${t.surconso} véhicule(s) en surconsommation</b> (plus de 10 % au-dessus de la consommation théorique) sur la période — vérifiez les pleins et les relevés.</div>` : ""}
    <div class="section-hdr" style="margin-bottom:12px">
      <div class="section-title"><i class="ti ti-gas-station"></i> Suivi carburant</div>
      <div style="margin-left:auto;display:flex;gap:8px;align-items:end">
        <div class="form-group" style="margin:0"><label class="form-label">Du</label><input id="cb-du" class="form-input" type="date" value="${f.du}" /></div>
        <div class="form-group" style="margin:0"><label class="form-label">Au</label><input id="cb-au" class="form-input" type="date" value="${f.au}" /></div>
        ${boutonsExport("cb")}
        <button class="btn btn-sm btn-primary" id="cb-new" style="height:34px"><i class="ti ti-plus"></i> Nouveau plein</button></div></div>
    <div class="kpi-row" style="margin-bottom:14px">
      <div class="kpi-card"><div class="kpi-label"><i class="ti ti-gas-station"></i> Pleins</div><div class="kpi-val">${t.pleins}</div><div class="kpi-sub">sur la période</div></div>
      <div class="kpi-card" style="--accent:var(--a)"><div class="kpi-label"><i class="ti ti-droplet"></i> Litres</div><div class="kpi-val">${fmtNum(t.litres)}</div><div class="kpi-sub">carburant consommé</div></div>
      <div class="kpi-card" style="--accent:var(--p)"><div class="kpi-label"><i class="ti ti-cash"></i> Dépense carburant</div><div class="kpi-val">${fmtNum(t.montant)} $</div><div class="kpi-sub">tous véhicules</div></div>
      <div class="kpi-card" style="--accent:var(--r)"><div class="kpi-label"><i class="ti ti-alert-triangle"></i> Surconsommations</div><div class="kpi-val" ${t.surconso ? 'style="color:var(--r)"' : ""}>${t.surconso}</div><div class="kpi-sub">écart &gt; 10 % vs théorique</div></div></div>
    <div class="card"><div class="card-hdr"><div class="card-hdr-title"><i class="ti ti-chart-bar"></i> Consommation par véhicule</div></div>
      <div class="card-body">${!rap.rapport.length ? '<div class="muted">Aucun plein sur la période.</div>' : `
      <table><thead><tr><th>Véhicule</th><th class="right">Pleins</th><th class="right">Litres</th><th class="right">Montant $</th>
        <th class="right">Usage</th><th class="right">Conso réelle</th><th class="right">Théorique</th><th class="right">Écart</th><th class="right">Coût unitaire</th><th>État</th></tr></thead><tbody>
      ${rap.rapport.map((r) => { const [sl, sc] = CARBU_ST[r.statut]; const uConso = r.unite === "km" ? "L/100km" : "L/h"; return `<tr>
        <td><b>${esc(r.vehicule)}</b> <span class="tag">${r.cible}</span></td>
        <td class="right">${r.pleins}</td><td class="right">${fmtNum(r.litres)}</td>
        <td class="right"><b>${fmtNum(r.montant_usd)}</b></td>
        <td class="right">${r.usage ? `${fmtNum(r.usage)} ${r.unite}` : "—"}</td>
        <td class="right">${r.conso_reelle != null ? `<b>${dec(r.conso_reelle)}</b> ${uConso}` : "—"}</td>
        <td class="right">${r.conso_theorique != null ? `${dec(r.conso_theorique)} ${uConso}` : "—"}</td>
        <td class="right">${r.ecart_pct != null ? `<b style="${r.ecart_pct > 10 ? "color:var(--r)" : ""}">${r.ecart_pct > 0 ? "+" : ""}${dec(r.ecart_pct)} %</b>` : "—"}</td>
        <td class="right">${r.cout_unitaire != null ? `${dec(r.cout_unitaire)} $/${r.unite}` : "—"}</td>
        <td><span class="pill ${sc}">${sl}</span></td></tr>`; }).join("")}
      </tbody></table>
      <div class="hint muted" style="font-size:11.5px;margin-top:8px">Conso réelle = litres ÷ km parcourus (relevés des courses) pour les camions, litres ÷ heures prestées (fiches) pour les engins. « À compléter » = il manque les relevés km/heures ou la consommation théorique du véhicule.</div>`}</div></div>
    <div class="card" style="margin-top:14px"><div class="card-hdr"><div class="card-hdr-title"><i class="ti ti-list-details"></i> Journal des pleins</div></div>
      <div class="card-body">${!pleins.length ? '<div class="muted">Aucun plein enregistré sur la période.</div>' : `
      <table><thead><tr><th>Date</th><th>Véhicule</th><th class="right">Litres</th><th class="right">Prix/L $</th><th class="right">Montant $</th>
        <th class="right">Compteur</th><th>Station</th><th>Course</th><th></th></tr></thead><tbody>
      ${pleins.map((p) => `<tr>
        <td>${p.date}</td><td><b>${esc(p.vehicule)}</b> <span class="tag">${p.cible}</span></td>
        <td class="right">${fmtNum(p.litres)}</td>
        <td class="right">${p.prix_litre_usd != null ? dec(p.prix_litre_usd) : "—"}</td>
        <td class="right"><b>${fmtNum(p.montant_usd)}</b></td>
        <td class="right">${p.compteur != null ? fmtNum(p.compteur) : "—"}</td>
        <td>${esc(p.fournisseur || "—")}${p.note ? `<div class="muted" style="font-size:11px">${esc(p.note)}</div>` : ""}</td>
        <td class="num-cell">${esc(p.course || "—")}</td>
        <td class="right" style="white-space:nowrap">
          <button class="btn btn-sm" data-cedit="${p.id}"><i class="ti ti-pencil"></i></button>
          <button class="btn btn-sm" data-cdel="${p.id}"><i class="ti ti-trash"></i></button></td></tr>`).join("")}
      </tbody></table>`}</div></div>`;
  const refresh = () => RENDER.carburant();
  const maj = () => { carbuFiltre = { du: $("#cb-du").value, au: $("#cb-au").value }; refresh(); };
  $("#cb-du").onchange = maj; $("#cb-au").onchange = maj;
  $("#cb-new").onclick = () => porteurs.length ? pleinModal(null, porteurs, refresh)
    : toast("Créez d'abord un camion ou un engin.", "ko");
  const cbCols = ["Véhicule", "Type", "Pleins", "Litres", "Montant $", "Usage", "Conso réelle", "Conso théorique", "Écart %", "Coût unitaire", "État"];
  const cbLignes = rap.rapport.map((r) => [r.vehicule, r.cible, r.pleins, r.litres, r.montant_usd,
    r.usage ? `${r.usage} ${r.unite}` : "", r.conso_reelle ?? "", r.conso_theorique ?? "",
    r.ecart_pct ?? "", r.cout_unitaire != null ? `${r.cout_unitaire} $/${r.unite}` : "", (CARBU_ST[r.statut] || [r.statut])[0]]);
  $("#cb-xls").onclick = () => exporterExcel(`carburant-${f.du}-${f.au}.csv`, cbCols, cbLignes);
  $("#cb-pdf").onclick = () => imprimerRapport("Suivi carburant", `du ${f.du} au ${f.au}`, cbCols, cbLignes,
    `TOTAL : ${t.pleins} plein(s) · ${fmtNum(t.litres)} L · <b>${fmtNum(t.montant)} $</b> · ${t.surconso} surconsommation(s) détectée(s).`);
  el.querySelectorAll("[data-cedit]").forEach((b) => b.onclick = () =>
    pleinModal(pleins.find((x) => x.id === b.dataset.cedit), porteurs, refresh));
  el.querySelectorAll("[data-cdel]").forEach((b) => b.onclick = async () => {
    const p = pleins.find((x) => x.id === b.dataset.cdel);
    if (!confirm(`Supprimer le plein du ${p.date} — ${p.vehicule} (${fmtNum(p.litres)} L) ?`)) return;
    try { await api(`/carburant/pleins/${p.id}?societe_id=${currentSocieteId}`, { method: "DELETE" });
      toast("Plein supprimé.", "ok"); refresh(); } catch (e) { toast(e.message, "ko"); }
  });
};

function pleinModal(p, porteurs, refresh) {
  const auj = isoLocal(new Date());
  const cleActuelle = p ? (p.camion_id ? `camion_id:${p.camion_id}` : `engin_id:${p.engin_id}`) : null;
  modal({
    title: p ? "Modifier le plein" : "Nouveau plein de carburant",
    body: `<div class="form-row">
        <div class="form-group"><label class="form-label">Véhicule</label>
          <select id="cp-veh" class="form-select" ${p ? "disabled" : ""}>${porteurs.map((x) => `<option value="${x.cle}" ${cleActuelle === x.cle ? "selected" : ""}>${esc(Catalogue.label(x))}</option>`).join("")}</select></div>
        <div class="form-group"><label class="form-label">Date</label><input id="cp-date" class="form-input" type="date" value="${p?.date || auj}" /></div></div>
      <div class="form-row">
        <div class="form-group"><label class="form-label">Litres</label><input id="cp-litres" class="form-input right" type="number" step="any" value="${p?.litres ?? ""}" /></div>
        <div class="form-group"><label class="form-label">Prix par litre (USD)</label><input id="cp-prix" class="form-input right" type="number" step="any" value="${p?.prix_litre_usd ?? ""}" /></div>
        <div class="form-group"><label class="form-label">Montant USD</label><input id="cp-mont" class="form-input right" type="number" step="any" value="${p?.montant_usd ?? ""}" placeholder="auto : litres × prix" /></div></div>
      <div class="form-row">
        <div class="form-group"><label class="form-label">Compteur (km ou index)</label><input id="cp-cpt" class="form-input right" type="number" step="any" value="${p?.compteur ?? ""}" /></div>
        <div class="form-group"><label class="form-label">Station / fournisseur</label><input id="cp-fourn" class="form-input" value="${esc(p?.fournisseur || "")}" /></div></div>
      <div class="form-group"><label class="form-label">Note</label><input id="cp-note" class="form-input" value="${esc(p?.note || "")}" /></div>`,
    footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="cp-ok"><i class="ti ti-check"></i> ${p ? "Enregistrer" : "Enregistrer le plein"}</button>`,
  });
  const majMontant = () => {
    const l = +$("#cp-litres").value, pr = +$("#cp-prix").value;
    if (l && pr) $("#cp-mont").value = (l * pr).toFixed(2);
  };
  $("#cp-litres").oninput = majMontant; $("#cp-prix").oninput = majMontant;
  $("#cp-ok").onclick = async () => {
    const body = { date: $("#cp-date").value,
      litres: +$("#cp-litres").value || 0,
      prix_litre_usd: $("#cp-prix").value === "" ? null : +$("#cp-prix").value,
      montant_usd: $("#cp-mont").value === "" ? null : +$("#cp-mont").value,
      compteur: $("#cp-cpt").value === "" ? null : +$("#cp-cpt").value,
      fournisseur: $("#cp-fourn").value || null, note: $("#cp-note").value || null };
    if (!p) {
      const [cle, id] = $("#cp-veh").value.split(":");
      body[cle] = id;
    }
    try {
      await api(p ? `/carburant/pleins/${p.id}?societe_id=${currentSocieteId}` : `/carburant/pleins?societe_id=${currentSocieteId}`,
        { method: p ? "PATCH" : "POST", body });
      closeModal(); toast(p ? "Plein modifié." : "Plein enregistré.", "ok"); refresh();
    } catch (e) { toast(e.message, "ko"); }
  };
}

// ═════════════════════════════════════════════════════════════════════
// HÔTELLERIE (Guest House Relax) — réception, séjours, folio, housekeeping
// ═════════════════════════════════════════════════════════════════════
const CHAMBRE_ST = { libre: ["Libre", "st-payee"], occupee: ["Occupée", "st-envoye"],
  sale: ["Sale", "st-due"], nettoyage: ["Nettoyage", "st-partielle"], maintenance: ["Maintenance", "st-confirme"] };
const SEJOUR_ST = { reservee: ["Réservée", "st-envoye"], arrivee: ["En séjour", "st-payee"],
  terminee: ["Terminé", "st-brouillon"], annulee: ["Annulée", "st-annule"], no_show: ["No-show", "st-due"] };
const SEJOUR_SOURCES = { directe: "Directe", telephone: "Téléphone", entreprise: "Entreprise", en_ligne: "En ligne" };

// Date locale AAAA-MM-JJ (jamais toISOString : il bascule en UTC et décale d'un jour)
function isoLocal(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

const hotelPlanningPeriods = new Map();
RENDER["hotel-reception"] = async () => {
  const el = $("#view-hotel-reception");
  el.innerHTML = `<div class="muted">Chargement…</div>`;
  const auj = isoLocal(new Date());
  const planningPeriod = hotelPlanningPeriods.get(currentSocieteId) || {du:auj, jours:14};
  let chambres, sejours, rapport, planning;
  try {
    [chambres, sejours, rapport, planning] = await Promise.all([
      api(`/hotel/chambres?societe_id=${currentSocieteId}`),
      api(`/hotel/sejours?societe_id=${currentSocieteId}`),
      api(`/hotel/rapport?societe_id=${currentSocieteId}`),
      api(`/hotel/planning?societe_id=${currentSocieteId}&jours=${planningPeriod.jours}&du=${planningPeriod.du}`),
    ]);
  } catch (e) { el.innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }
  const actives = chambres.filter((c) => c.actif);
  const arrivees = sejours.filter((s) => s.statut === "reservee" && s.date_arrivee <= auj);
  const aVenir = sejours.filter((s) => s.statut === "reservee" && s.date_arrivee > auj);
  const enCours = sejours.filter((s) => s.statut === "arrivee");
  const departsJour = enCours.filter((s) => s.date_depart_prevue <= auj);
  const clos = sejours.filter((s) => ["terminee", "annulee", "no_show"].includes(s.statut)).slice(0, 8);

  // Période de consultation indépendante des indicateurs du jour et du mois.
  const JS_JOUR = 86400000;
  const jours = Array.from({ length: planning.jours }, (_, i) => {
    const d = new Date(new Date(planning.du + "T00:00:00").getTime() + i * JS_JOUR);
    return { iso: isoLocal(d), j: d.getDate(),
      sem: ["dim", "lun", "mar", "mer", "jeu", "ven", "sam"][d.getDay()] };
  });
  const timeline = `<div class="hotel-planning-wrap"><table style="border-collapse:collapse;min-width:100%">
    <thead><tr><th style="text-align:left;padding:6px 10px;position:sticky;left:0;background:var(--card,#fff);min-width:110px">Chambre</th>
      ${jours.map((d) => `<th style="padding:4px 2px;font-size:10.5px;min-width:58px;text-align:center;${d.iso === auj ? "background:var(--pl);color:var(--p);border-radius:6px 6px 0 0" : "color:var(--gray)"}">
        ${d.sem}<br/><b style="font-size:13px">${d.j}</b></th>`).join("")}</tr></thead>
    <tbody>${planning.chambres.map((c) => {
      const [sl, sc] = CHAMBRE_ST[c.etat] || [c.etat, ""];
      return `<tr style="border-top:1px solid var(--grayl)">
        <td style="padding:6px 10px;position:sticky;left:0;background:var(--card,#fff);white-space:nowrap">
          <b>Ch. ${esc(c.numero)}</b> <span class="pill ${sc}" style="font-size:10px">${sl}</span></td>
        ${jours.map((d) => {
          const occ = c.occupations.find((o) => o.du <= d.iso && d.iso < o.au);
          if (!occ) return `<td style="padding:2px 1px;${d.iso === auj ? "background:var(--pl)" : ""}"></td>`;
          const premier = d.iso === (occ.du > planning.du ? occ.du : planning.du);
          const enCoursOcc = occ.statut === "arrivee";
          return `<td style="padding:2px 0;${d.iso === auj ? "background:var(--pl)" : ""}">
            <button type="button" data-tlsej="${occ.sejour_id}" aria-label="${esc(occ.client)} — ${d.iso} — ${enCoursOcc ? "en séjour" : "réservé"}" title="${esc(occ.client)} — ${occ.du} → ${occ.au} (${enCoursOcc ? "en séjour" : "réservé"})"
              style="border:0;width:100%;text-align:left;cursor:pointer;height:24px;line-height:24px;font-size:10.5px;overflow:hidden;white-space:nowrap;padding:0 5px;color:#fff;
              background:${enCoursOcc ? "var(--g,#16a34a)" : "var(--p,#3C3489)"};
              border-radius:${premier ? "6px" : "0"} ${d.iso === isoLocal(new Date(new Date(occ.au + "T00:00:00").getTime() - JS_JOUR)) || d.iso === jours[jours.length - 1].iso ? "6px" : "0"} 0 0">
              ${premier ? esc(occ.client) : "&nbsp;"}</button></td>`;
        }).join("")}</tr>`;
    }).join("")}</tbody></table></div>
    <div class="muted" style="font-size:11px;margin-top:6px"><span style="display:inline-block;width:10px;height:10px;background:var(--p,#3C3489);border-radius:2px"></span> Réservé
      &nbsp;<span style="display:inline-block;width:10px;height:10px;background:var(--g,#16a34a);border-radius:2px"></span> En séjour — cliquez une barre pour ouvrir la fiche du séjour.</div>
    ${departsJour.some(s=>s.date_depart_prevue < auj) ? '<div class="req-next-note">Un séjour en cours a dépassé sa date de départ prévue. Le planning représente les dates enregistrées ; consultez aussi la liste <b>Clients en séjour</b> ci-dessous.</div>' : ''}`;

  const ligneSejour = (s, action) => `<tr data-fiche="${s.id}" style="cursor:pointer" title="Ouvrir la fiche du séjour">
    <td class="num-cell">${esc(s.numero)}</td>
    <td><b>${esc(s.client_nom)}</b></td>
    <td>Ch. <b>${esc(s.chambre)}</b></td>
    <td>${s.date_arrivee} → ${s.date_depart_prevue}</td>
    <td class="right">${fmtNum(s.tarif_nuit_usd)} $/nuit</td>
    <td class="right" style="white-space:nowrap">${action}</td></tr>`;
  const tableau = (rows) => `<table><thead><tr><th>N°</th><th>Client</th><th>Chambre</th><th>Dates</th><th class="right">Tarif</th><th></th></tr></thead><tbody>${rows}</tbody></table>`;

  el.innerHTML = `
    <div class="section-hdr" style="margin-bottom:12px">
      <div class="section-title"><i class="ti ti-bed"></i> Réception — ${new Date().toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long" })}</div>
      <div style="margin-left:auto;display:flex;gap:8px">
        ${boutonsExport("hr")}
        <button class="btn btn-sm" id="hr-walkin"><i class="ti ti-user-check"></i> Walk-in</button>
        <button class="btn btn-sm btn-primary" id="hr-new"><i class="ti ti-plus"></i> Nouvelle réservation</button></div></div>
    <div class="kpi-row" style="margin-bottom:12px">
      <div class="kpi-card" style="--accent:var(--g)"><div class="kpi-label"><i class="ti ti-door"></i> Chambres libres</div>
        <div class="kpi-val">${actives.filter((c) => c.etat === "libre").length} <span style="font-size:15px;font-weight:600;color:var(--text3)">/ ${actives.length}</span></div>
        <div class="kpi-sub">${actives.filter((c) => c.etat === "occupee").length} occupée(s) · ${actives.filter((c) => ["sale", "nettoyage"].includes(c.etat)).length} à préparer · ${actives.filter((c) => c.etat === "maintenance").length} hors service</div></div>
      <div class="kpi-card"><div class="kpi-label"><i class="ti ti-login"></i> Arrivées attendues</div>
        <div class="kpi-val">${arrivees.length}</div><div class="kpi-sub">aujourd'hui et arrivées en retard</div></div>
      <div class="kpi-card"><div class="kpi-label"><i class="ti ti-logout"></i> Départs à effectuer</div>
        <div class="kpi-val">${departsJour.length}</div><div class="kpi-sub">aujourd'hui et départs en retard</div></div>
      <div class="kpi-card" style="--accent:var(--a)"><div class="kpi-label"><i class="ti ti-chart-pie"></i> Occupation du mois</div>
        <div class="kpi-val">${String(rapport.taux_occupation_pct).replace(".", ",")} %</div><div class="kpi-sub">${rapport.nuitees_vendues} nuitée(s) vendue(s)</div></div>
      <div class="kpi-card" style="--accent:var(--p)"><div class="kpi-label"><i class="ti ti-cash"></i> Revenu du mois</div>
        <div class="kpi-val">${fmtNum(rapport.revenu_hebergement_usd)} $</div><div class="kpi-sub">${fmtNum(rapport.adr_usd)} $ par nuitée en moyenne</div></div></div>
    <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px">
      ${actives.map((c) => { const [sl, sc] = CHAMBRE_ST[c.etat] || [c.etat, ""]; return `
        <div data-tuile="${c.id}" class="pill ${sc}" style="cursor:pointer;padding:7px 12px;font-size:13px" title="${sl}${c.sejour ? " — " + esc(c.sejour.client) : ""}">
          <b>${esc(c.numero)}</b>${c.sejour ? ` · ${esc(c.sejour.client.split(" ")[0])}` : ""}</div>`; }).join("")}
    </div>
    <div class="card" style="margin-bottom:14px"><div class="card-hdr"><div class="card-hdr-title"><i class="ti ti-calendar-week"></i> Planning · ${planning.du} → ${jours[jours.length-1].iso}</div></div>
      <div class="card-body"><div class="hotel-planning-tools">
        <button class="btn btn-sm" id="hp-prev" aria-label="Période précédente">←</button>
        <label>À partir du <input type="date" id="hp-du" class="form-input" value="${planning.du}" /></label>
        <label>Période <select id="hp-days" class="form-select">${[7,14,31].map(n=>`<option value="${n}" ${n===planning.jours?"selected":""}>${n} jours</option>`).join("")}</select></label>
        <button class="btn btn-sm" id="hp-next" aria-label="Période suivante">→</button>
        <button class="btn btn-sm" id="hp-today">Aujourd'hui</button></div>
        ${actives.length ? timeline : '<div class="empty"><i class="ti ti-door"></i>Créez d\'abord vos chambres (menu Configuration).</div>'}</div></div>
    ${arrivees.length ? `<div class="card" style="margin-bottom:14px"><div class="card-hdr"><div class="card-hdr-title"><i class="ti ti-login"></i> Arrivées attendues (${arrivees.length})</div></div>
      <div class="card-body">${tableau(arrivees.map((s) => ligneSejour(s, `<button class="btn btn-sm btn-primary" data-hin="${s.id}"><i class="ti ti-login"></i> Check-in</button>`)).join(""))}</div></div>` : ""}
    <div class="card" style="margin-bottom:14px"><div class="card-hdr"><div class="card-hdr-title"><i class="ti ti-bed-flat"></i> Clients en séjour (${enCours.length})</div></div>
      <div class="card-body">${!enCours.length ? '<div class="muted">Aucun client en séjour.</div>' : tableau(enCours.map((s) => ligneSejour(s, `<button class="btn btn-sm btn-primary" data-fiche2="${s.id}"><i class="ti ti-clipboard-text"></i> Fiche séjour${s.date_depart_prevue <= auj ? " · départ prévu" : ""}</button>`)).join(""))}</div></div>
    ${aVenir.length ? `<div class="card" style="margin-bottom:14px"><div class="card-hdr"><div class="card-hdr-title"><i class="ti ti-calendar"></i> Réservations à venir (${aVenir.length})</div></div>
      <div class="card-body">${tableau(aVenir.map((s) => ligneSejour(s, "")).join(""))}</div></div>` : ""}
    ${clos.length ? `<div class="card"><div class="card-hdr"><div class="card-hdr-title"><i class="ti ti-history"></i> Derniers séjours clôturés</div></div>
      <div class="card-body"><table><thead><tr><th>N°</th><th>Client</th><th>Chambre</th><th>Dates</th><th>Statut</th><th>Facture</th></tr></thead><tbody>
      ${clos.map((s) => { const [sl, sc] = SEJOUR_ST[s.statut]; return `<tr data-fiche="${s.id}" style="cursor:pointer;opacity:.8" title="Ouvrir la fiche">
        <td class="num-cell">${esc(s.numero)}</td><td>${esc(s.client_nom)}</td><td>Ch. ${esc(s.chambre)}</td>
        <td>${s.date_arrivee} → ${s.date_depart || s.date_depart_prevue}</td>
        <td><span class="pill ${sc}">${sl}</span></td><td class="num-cell">${esc(s.facture || "—")}</td></tr>`; }).join("")}
      </tbody></table></div></div>` : ""}`;
  const refresh = () => RENDER["hotel-reception"]();
  const changePeriod = (du, days) => {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(du) || !Number.isFinite(new Date(du + "T00:00:00").getTime())) return;
    hotelPlanningPeriods.set(currentSocieteId, {du, jours:Number(days)});
    go("hotel-reception");
  };
  $("#hp-du").onchange = () => changePeriod($("#hp-du").value, planning.jours);
  $("#hp-days").onchange = () => changePeriod(planning.du, $("#hp-days").value);
  $("#hp-today").onclick = () => changePeriod(auj, planning.jours);
  const shiftPeriod = direction => {
    const date = new Date(planning.du + "T00:00:00");
    date.setDate(date.getDate() + direction * planning.jours);
    changePeriod(isoLocal(date), planning.jours);
  };
  $("#hp-prev").onclick = () => shiftPeriod(-1);
  $("#hp-next").onclick = () => shiftPeriod(1);
  $("#hr-new").onclick = () => sejourModal(null, actives, false, refresh);
  $("#hr-walkin").onclick = () => sejourModal(null, actives, true, refresh);
  const hrCols = ["N°", "Client", "Téléphone", "Chambre", "Arrivée", "Départ", "Pers.", "Tarif/nuit $", "Statut", "Source", "Facture"];
  const hrLignes = sejours.map((s) => [s.numero, s.client_nom, s.client_telephone || "", s.chambre,
    s.date_arrivee, s.date_depart || s.date_depart_prevue, s.nb_personnes, s.tarif_nuit_usd,
    (SEJOUR_ST[s.statut] || [s.statut])[0], SEJOUR_SOURCES[s.source] || s.source, s.facture || ""]);
  $("#hr-xls").onclick = () => exporterExcel("sejours-hotel.csv", hrCols, hrLignes);
  $("#hr-pdf").onclick = () => imprimerRapport("Rapport hôtel — séjours & occupation",
    `${rapport.du} → ${rapport.au}`, hrCols, hrLignes,
    `Occupation : <b>${String(rapport.taux_occupation_pct).replace(".", ",")} %</b> · ${rapport.nuitees_vendues} nuitée(s) vendue(s) · revenu hébergement ${fmtNum(rapport.revenu_hebergement_usd)} $ · prix moyen/nuitée ${fmtNum(rapport.adr_usd)} $ · RevPAR ${fmtNum(rapport.revpar_usd)} $.`);
  el.querySelectorAll("[data-hin]").forEach((b) => b.onclick = async (ev) => {
    ev.stopPropagation();
    try { await api(`/hotel/sejours/${b.dataset.hin}/checkin?societe_id=${currentSocieteId}`, { method: "POST", body: {} });
      toast("Check-in effectué — bon séjour !", "ok"); ficheSejourModal(b.dataset.hin, refresh); refresh(); } catch (e) { toast(e.message, "ko"); }
  });
  el.querySelectorAll("[data-fiche]").forEach((tr) => tr.onclick = () => ficheSejourModal(tr.dataset.fiche, refresh));
  el.querySelectorAll("[data-fiche2]").forEach((b) => b.onclick = (ev) => { ev.stopPropagation(); ficheSejourModal(b.dataset.fiche2, refresh); });
  el.querySelectorAll("[data-tlsej]").forEach((d) => d.onclick = () => ficheSejourModal(d.dataset.tlsej, refresh));
  el.querySelectorAll("[data-tuile]").forEach((d) => d.onclick = () => {
    const c = actives.find((x) => x.id === d.dataset.tuile);
    if (c.sejour) ficheSejourModal(c.sejour.id, refresh); else go("hotel-chambres");
  });
};

async function sejourModal(s, chambres, walkIn, refresh) {
  let clients;
  try { clients=await api(`/hotel/clients?societe_id=${currentSocieteId}`); }
  catch(e){toast(e.message,'ko');return;}
  const auj = isoLocal(new Date());
  const demain = isoLocal(new Date(Date.now() + 86400000));
  const dispo = chambres.filter((c) => c.actif);
  modal({
    title: s ? `Modifier — ${s.numero}` : walkIn ? "Walk-in — arrivée directe" : "Nouvelle réservation",
    body: `<div class="form-row">
        <div class="form-group"><label class="form-label">Chambre</label>
          <select id="sj-ch" class="form-select" ${s ? "disabled" : ""}>${dispo.map((c) => `<option value="${c.id}" data-tarif="${c.tarif_nuit_usd}" ${s?.chambre_id === c.id ? "selected" : ""}>${esc(c.numero)}${c.categorie ? " · " + esc(c.categorie) : ""} — ${fmtNum(c.tarif_nuit_usd)} $/nuit (${(CHAMBRE_ST[c.etat] || [c.etat])[0]})</option>`).join("")}</select></div>
        <div class="form-group"><label class="form-label">Source</label>
          <select id="sj-src" class="form-select">${Object.entries(SEJOUR_SOURCES).map(([v, l]) => `<option value="${v}" ${s?.source === v ? "selected" : ""}>${l}</option>`).join("")}</select></div></div>
      <div class="form-group"><label class="form-label">Fiche client — ${esc(societes.find(c=>c.id===currentSocieteId)?.nom||'')}</label><select id="sj-client" class="form-select" ${s?.tiers_id?'disabled':''}><option value="">— Sélectionner ou créer un client —</option>${clients.filter(c=>c.actif!==false||c.id===s?.tiers_id).map(c=>`<option value="${c.id}" ${c.id===s?.tiers_id?'selected':''}>${esc(c.code)} — ${esc(Catalogue.label(c))}</option>`).join('')}</select></div>
      <div class="form-row">
        <div class="form-group"><label class="form-label">Nom du client</label><input id="sj-nom" class="form-input" value="${esc(s?.client_nom || "")}" /></div>
        <div class="form-group"><label class="form-label">Téléphone</label><input id="sj-tel" class="form-input" value="${esc(s?.client_telephone || "")}" /></div>
        <div class="form-group"><label class="form-label">Personnes</label><input id="sj-nb" class="form-input right" type="number" min="1" value="${s?.nb_personnes || 1}" /></div></div>
      <div class="form-row">
        <div class="form-group"><label class="form-label">Arrivée</label><input id="sj-arr" class="form-input" type="date" value="${s?.date_arrivee || auj}" ${walkIn || s?.statut === "arrivee" ? "disabled" : ""} /></div>
        <div class="form-group"><label class="form-label">Départ prévu</label><input id="sj-dep" class="form-input" type="date" value="${s?.date_depart_prevue || demain}" /></div>
        <div class="form-group"><label class="form-label">Tarif/nuit USD</label><input id="sj-tarif" class="form-input right" type="number" step="any" value="${s ? s.tarif_nuit_usd : (dispo[0]?.tarif_nuit_usd ?? "")}" /></div></div>
      <div class="form-group"><label class="form-label">Note</label><input id="sj-note" class="form-input" value="${esc(s?.note || "")}" /></div>
      ${walkIn ? '<div class="banner"><i class="ti ti-info-circle"></i> Walk-in : le client entre immédiatement — la chambre passe « occupée » et son compte client est ouvert.</div>' : ""}`,
    footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="sj-ok"><i class="ti ti-check"></i> ${s ? "Enregistrer" : walkIn ? "Check-in immédiat" : "Réserver"}</button>`,
  });
  const chooseClient=()=>{
    const selected=clients.find(c=>c.id===$('#sj-client').value);
    $('#sj-nom').readOnly=!!selected;
    if(selected)$('#sj-nom').value=selected.nom;
  };
  $('#sj-client').onchange=chooseClient;
  Catalogue.bind($('#sj-client'),{kind:'client',endpoint:'/hotel/clients',accept:c=>{if(!clients.some(x=>x.id===c.id))clients.push(c);}});
  chooseClient();
  if (!s) $("#sj-ch").onchange = (e) => { $("#sj-tarif").value = e.target.selectedOptions[0].dataset.tarif; };
  $("#sj-ok").onclick = async () => {
    const body = { client_nom: $("#sj-nom").value, client_telephone: $("#sj-tel").value || null,
      nb_personnes: +$("#sj-nb").value || 1, date_arrivee: $("#sj-arr").value,
      date_depart_prevue: $("#sj-dep").value, tarif_nuit_usd: +$("#sj-tarif").value || 0,
      note: $("#sj-note").value || null };
    if($('#sj-client').value)body.tiers_id=$('#sj-client').value;
    try {
      if (s) {
        if (s.statut === "arrivee") delete body.date_arrivee;
        await api(`/hotel/sejours/${s.id}?societe_id=${currentSocieteId}`, { method: "PATCH", body });
      } else {
        body.chambre_id = $("#sj-ch").value;
        body.source = $("#sj-src").value;
        body.arrivee_immediate = walkIn;
        await api(`/hotel/sejours?societe_id=${currentSocieteId}`, { method: "POST", body });
      }
      closeModal(); toast(s ? "Séjour modifié." : walkIn ? "Client arrivé — bon séjour !" : "Réservation enregistrée.", "ok"); refresh();
    } catch (e) { toast(e.message, "ko"); }
  };
}

// ── Fiche de séjour : le poste de suivi du client, du check-in au départ ─
const SERVICES_RAPIDES = [["Repassage", "blanchisserie", 2], ["Blanchisserie", "blanchisserie", 5],
  ["Petit-déjeuner", "restaurant", 8], ["Transport / course", "divers", 10]];

async function ficheSejourModal(sejourId, refresh) {
  let f;
  try { f = await api(`/hotel/sejours/${sejourId}/folio?societe_id=${currentSocieteId}`); }
  catch (e) { toast(e.message, "ko"); return; }
  const s = f.sejour;
  const [sl, sc] = SEJOUR_ST[s.statut] || [s.statut, ""];
  const enSejour = s.statut === "arrivee";
  const termine = s.statut === "terminee";
  const reserve = s.statut === "reservee";
  const info = (l, v) => `<div><div class="muted" style="font-size:10.5px;text-transform:uppercase">${l}</div><div style="font-size:13.5px"><b>${v}</b></div></div>`;
  modal({ wide: true,
    title: `Fiche de séjour ${s.numero}`,
    body: `<div style="display:flex;gap:22px;flex-wrap:wrap;align-items:center;margin-bottom:14px">
        ${info("Client", esc(s.client_nom))}${info("Téléphone", esc(s.client_telephone || "—"))}
        ${info("Chambre", "Ch. " + esc(s.chambre))}${info("Séjour", `${s.date_arrivee} → ${s.date_depart || s.date_depart_prevue}`)}
        ${info("Personnes", s.nb_personnes)}${info("Statut", `<span class="pill ${sc}">${sl}</span>`)}</div>
      ${enSejour ? `<div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px">
        ${SERVICES_RAPIDES.map(([lb, org, pu], i) => `<button class="btn btn-sm" data-svc="${i}"><i class="ti ti-plus"></i> ${lb}</button>`).join("")}
        <button class="btn btn-sm" id="fs-autre"><i class="ti ti-plus"></i> Autre service…</button></div>` : ""}
      <table><thead><tr><th>Date</th><th>Désignation</th><th class="right">Qté</th><th class="right">PU $</th><th class="right">Montant $</th><th></th></tr></thead><tbody>
        <tr><td>${s.date_arrivee}</td><td><b>Hébergement</b> — ${f.nuits} nuit(s) × ${fmtNum(s.tarif_nuit_usd)} $</td>
          <td class="right">${f.nuits}</td><td class="right">${fmtNum(s.tarif_nuit_usd)}</td><td class="right"><b>${fmtNum(f.montant_nuitees)}</b></td><td></td></tr>
        ${f.extras.map((ln) => `<tr><td>${ln.date}</td><td>${esc(ln.designation)} <span class="tag">${ln.origine}</span></td>
          <td class="right">${fmtNum(ln.qte)}</td><td class="right">${fmtNum(ln.prix_unitaire)}</td><td class="right">${fmtNum(ln.montant_usd)}</td>
          <td class="right">${enSejour ? `<button class="btn btn-sm" data-fdel="${ln.id}"><i class="ti ti-trash"></i></button>` : ""}</td></tr>`).join("")}
        ${f.tickets_pos.map((ln) => `<tr style="opacity:.85"><td>${ln.date}</td><td>${esc(ln.designation)} <span class="tag">${ln.origine}</span> <span class="pill ${ln.solde_du_usd > 0 ? "st-partielle" : "st-payee"}" style="font-size:10px">${ln.solde_du_usd > 0 ? "à encaisser" : "réglé"}</span></td>
          <td class="right">1</td><td class="right">${fmtNum(ln.montant_usd)}</td><td class="right">${fmtNum(ln.montant_usd)}</td><td></td></tr>`).join("")}
      </tbody><tfoot>
        <tr class="total-row"><td colspan="4"><b>TOTAL DE LA NOTE</b></td><td class="right"><b>${fmtNum(f.total_note)}</b></td><td></td></tr>
        ${termine && f.facture_sejour ? `
          <tr><td colspan="4">Facture ${esc(f.facture_sejour.numero)} — TTC (TVA ${fmtNum(f.facture_sejour.total_tva)} $)</td><td class="right">${fmtNum(f.facture_sejour.total_ttc)}</td><td></td></tr>
          <tr><td colspan="4">Déjà payé (séjour + tickets)</td><td class="right">${fmtNum(Math.round((f.facture_sejour.paye_usd + f.tickets_pos.reduce((a, t) => a + (t.montant_usd - t.solde_du_usd), 0)) * 100) / 100)}</td><td></td></tr>
          <tr><td colspan="4"><b style="color:${f.solde_du_usd > 0 ? "var(--r)" : "var(--g)"}">${f.solde_du_usd > 0 ? "SOLDE À ENCAISSER" : "TOUT EST RÉGLÉ"}</b></td><td class="right"><b>${fmtNum(f.solde_du_usd)}</b></td><td></td></tr>` : ""}
      </tfoot></table>
      ${reserve ? '<div class="banner" style="margin-top:10px"><i class="ti ti-info-circle"></i> Client pas encore arrivé — faites le check-in à son arrivée pour ouvrir la note.</div>' : ""}`,
    footer: `<button class="btn" onclick="closeModal()">Fermer</button>
      ${reserve ? `<button class="btn" id="fs-edit"><i class="ti ti-pencil"></i> Modifier</button>
        <button class="btn" id="fs-ann"><i class="ti ti-x"></i> Annuler / no-show</button>
        <button class="btn btn-primary" id="fs-in"><i class="ti ti-login"></i> Check-in</button>` : ""}
      ${enSejour ? `<button class="btn" id="fs-edit"><i class="ti ti-pencil"></i> Modifier</button>
        <button class="btn" id="fs-print"><i class="ti ti-printer"></i> Imprimer la note</button>
        <button class="btn btn-primary" id="fs-out"><i class="ti ti-logout"></i> Check-out & facturer</button>` : ""}
      ${termine ? `<button class="btn" id="fs-print"><i class="ti ti-printer"></i> Imprimer la facture</button>
        ${f.solde_du_usd > 0 ? `<button class="btn btn-primary" id="fs-pay"><i class="ti ti-cash"></i> Encaisser le solde (${fmtNum(f.solde_du_usd)} $)</button>` : ""}` : ""}`,
  });
  const reouvrir = () => { closeModal(); ficheSejourModal(sejourId, refresh); };
  const ajouterService = async (designation, qte, pu, origine) => {
    try {
      await api(`/hotel/sejours/${sejourId}/lignes?societe_id=${currentSocieteId}`, { method: "POST",
        body: { designation, qte, prix_unitaire: pu, origine } });
      toast(`${designation} ajouté à la note.`, "ok"); reouvrir();
    } catch (e) { toast(e.message, "ko"); }
  };
  document.querySelectorAll("[data-svc]").forEach((b) => b.onclick = () => {
    const [lb, org, pu] = SERVICES_RAPIDES[+b.dataset.svc];
    modal({ title: `${lb} — sur la note de ${s.client_nom}`,
      body: `<div class="form-row">
        <div class="form-group"><label class="form-label">Qté</label><input id="sv-qte" class="form-input right" type="number" step="any" value="1" /></div>
        <div class="form-group"><label class="form-label">Prix unitaire $</label><input id="sv-pu" class="form-input right" type="number" step="any" value="${pu}" /></div></div>`,
      footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="sv-ok"><i class="ti ti-check"></i> Ajouter</button>` });
    $("#sv-ok").onclick = () => {
      const qte = +$("#sv-qte").value || 1, pu = +$("#sv-pu").value || 0;
      closeModal(); ajouterService(lb, qte, pu, org);
    };
  });
  const btnAutre = $("#fs-autre");
  if (btnAutre) btnAutre.onclick = () => {
    modal({ title: `Service — sur la note de ${s.client_nom}`,
      body: `<div class="form-group"><label class="form-label">Désignation</label><input id="sv-des" class="form-input" placeholder="ex. Location salle, taxi…" /></div>
        <div class="form-row">
        <div class="form-group"><label class="form-label">Qté</label><input id="sv-qte" class="form-input right" type="number" step="any" value="1" /></div>
        <div class="form-group"><label class="form-label">Prix unitaire $</label><input id="sv-pu" class="form-input right" type="number" step="any" /></div>
        <div class="form-group"><label class="form-label">Origine</label><select id="sv-org" class="form-select">
          <option value="divers">Divers</option><option value="blanchisserie">Blanchisserie</option><option value="restaurant">Restaurant</option><option value="bar">Bar</option></select></div></div>`,
      footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="sv-ok"><i class="ti ti-check"></i> Ajouter</button>` });
    $("#sv-ok").onclick = () => {
      const des = $("#sv-des").value, qte = +$("#sv-qte").value || 1,
        pu = +$("#sv-pu").value || 0, org = $("#sv-org").value;
      closeModal(); ajouterService(des, qte, pu, org);
    };
  };
  document.querySelectorAll("[data-fdel]").forEach((b) => b.onclick = async () => {
    try { await api(`/hotel/sejours/${sejourId}/lignes/${b.dataset.fdel}?societe_id=${currentSocieteId}`, { method: "DELETE" });
      toast("Ligne retirée.", "ok"); reouvrir(); } catch (e) { toast(e.message, "ko"); }
  });
  const btnEdit = $("#fs-edit");
  if (btnEdit) btnEdit.onclick = async () => {
    const chambres = await api(`/hotel/chambres?societe_id=${currentSocieteId}`).catch(() => []);
    closeModal(); sejourModal(s, chambres, false, () => { refresh(); ficheSejourModal(sejourId, refresh); });
  };
  const btnIn = $("#fs-in");
  if (btnIn) btnIn.onclick = async () => {
    try { await api(`/hotel/sejours/${sejourId}/checkin?societe_id=${currentSocieteId}`, { method: "POST", body: {} });
      toast("Check-in effectué — bon séjour !", "ok"); refresh(); reouvrir(); } catch (e) { toast(e.message, "ko"); }
  };
  const btnAnn = $("#fs-ann");
  if (btnAnn) btnAnn.onclick = () => {
    modal({ title: `Annuler — ${s.numero}`,
      body: `<p style="font-size:13.5px">Réservation de <b>${esc(s.client_nom)}</b> (ch. ${esc(s.chambre)}, ${s.date_arrivee}).</p>`,
      footer: `<button class="btn" onclick="closeModal()">Retour</button>
        <button class="btn" id="ha-ns"><i class="ti ti-user-off"></i> No-show</button>
        <button class="btn btn-danger" id="ha-ok"><i class="ti ti-x"></i> Annuler la réservation</button>` });
    const faire = async (noShow) => {
      try { await api(`/hotel/sejours/${sejourId}/annuler?societe_id=${currentSocieteId}`, { method: "POST", body: { no_show: noShow } });
        closeModal(); closeModal(); toast(noShow ? "No-show enregistré." : "Réservation annulée.", "ok"); refresh(); } catch (e) { toast(e.message, "ko"); }
    };
    $("#ha-ok").onclick = () => faire(false);
    $("#ha-ns").onclick = () => faire(true);
  };
  const btnPrint = $("#fs-print");
  if (btnPrint) btnPrint.onclick = () => imprimerNoteSejour(f);
  const btnOut = $("#fs-out");
  if (btnOut) btnOut.onclick = async () => {
    if (!confirm(`Check-out de ${s.client_nom} (ch. ${s.chambre}) ?\nLa facture d'hébergement sera générée et la chambre passera « à nettoyer ».`)) return;
    try {
      await api(`/hotel/sejours/${sejourId}/checkout?societe_id=${currentSocieteId}`, { method: "POST", body: {} });
      toast("Check-out effectué — facture générée.", "ok"); refresh(); reouvrir();
    } catch (e) { toast(e.message, "ko"); }
  };
  const btnPay = $("#fs-pay");
  if (btnPay) btnPay.onclick = () => {
    const pieces = [];
    if (f.facture_sejour && f.facture_sejour.solde_du_usd > 0)
      pieces.push({ id: f.facture_sejour.id, libelle: `Facture hébergement ${f.facture_sejour.numero}`, montant: f.facture_sejour.solde_du_usd });
    const vus = new Set();
    for (const t of f.tickets_pos) {
      if (t.solde_du_usd > 0 && !vus.has(t.facture_pos_id)) {
        vus.add(t.facture_pos_id);
        pieces.push({ id: t.facture_pos_id, libelle: t.designation, montant: t.solde_du_usd });
      }
    }
    encaisserPiecesModal(pieces, `Encaisser le séjour ${s.numero}`, () => { refresh(); ficheSejourModal(sejourId, refresh); });
  };
}

function imprimerNoteSejour(f) {
  const s = f.sejour;
  const soc = (societes.find((x) => x.id === currentSocieteId) || {}).nom || "";
  const estFacture = !!f.facture_sejour;
  const titre = estFacture ? `FACTURE ${f.facture_sejour.numero}` : `NOTE DE SÉJOUR (pro forma) — ${s.numero}`;
  const ligne = (date2, des, qte, pu, m) => `<tr><td>${date2}</td><td>${des}</td><td class="r">${fmtNum(qte)}</td><td class="r">${fmtNum(pu)}</td><td class="r">${fmtNum(m)}</td></tr>`;
  let corps = ligne(s.date_arrivee, `Hébergement chambre ${esc(s.chambre)} — ${f.nuits} nuit(s)`, f.nuits, s.tarif_nuit_usd, f.montant_nuitees);
  corps += f.extras.map((ln) => ligne(ln.date, esc(ln.designation), ln.qte, ln.prix_unitaire, ln.montant_usd)).join("");
  corps += f.tickets_pos.map((ln) => ligne(ln.date, esc(ln.designation) + " (facturé POS, TTC)", 1, ln.montant_usd, ln.montant_usd)).join("");
  const w = Editions.fenetre();
  w.document.write(`<html><head><meta charset="utf-8"><title>${esc(s.numero)}</title><style>
    body{font-family:Arial,sans-serif;padding:34px;color:#222}h1{font-size:18px;color:#3C3489;margin:0 0 2px}
    .sub{color:#666;margin-bottom:14px;font-size:13px}table{width:100%;border-collapse:collapse;font-size:12.5px;margin:12px 0}
    th{text-align:left;padding:7px 10px;background:#F1F0FB;color:#3C3489;font-size:11px}td{padding:7px 10px;border-bottom:1px solid #eee}.r{text-align:right}
    .tot{text-align:right;font-size:15px;font-weight:800;color:#3C3489;margin-top:8px}
    .solde{text-align:right;font-size:13px;margin-top:4px}
    .sign{margin-top:56px;display:flex;justify-content:space-between}.sign div{border-top:1px solid #999;width:40%;text-align:center;padding-top:6px;font-size:12px;color:#666}</style></head><body>
    <h1>${esc(soc)}</h1><div class="sub">${titre} · ${new Date().toLocaleDateString("fr-FR")}</div>
    <p><b>Client :</b> ${esc(s.client_nom)}${s.client_telephone ? ` · ${esc(s.client_telephone)}` : ""}<br/>
       <b>Chambre :</b> ${esc(s.chambre)} · <b>Séjour :</b> du ${s.date_arrivee} au ${s.date_depart || s.date_depart_prevue} (${f.nuits} nuit(s), ${s.nb_personnes} pers.)</p>
    <table><thead><tr><th>Date</th><th>Désignation</th><th class="r">Qté</th><th class="r">P.U. $</th><th class="r">Montant $</th></tr></thead><tbody>${corps}</tbody></table>
    ${estFacture ? `<div class="solde">Total HT hébergement : ${fmtNum(f.facture_sejour.total_ht)} $ · TVA : ${fmtNum(f.facture_sejour.total_tva)} $ · <b>TTC : ${fmtNum(f.facture_sejour.total_ttc)} $</b></div>` : ""}
    <div class="tot">TOTAL DE LA NOTE : ${fmtNum(estFacture ? Math.round((f.facture_sejour.total_ttc + f.total_tickets_pos) * 100) / 100 : f.total_note)} USD</div>
    ${estFacture ? `<div class="solde">Déjà payé : ${fmtNum(Math.round((f.facture_sejour.paye_usd + f.tickets_pos.reduce((a, t) => a + (t.montant_usd - t.solde_du_usd), 0)) * 100) / 100)} $ · <b>Solde dû : ${fmtNum(f.solde_du_usd)} $</b></div>` : '<div class="solde">Document provisoire — la facture est émise au check-out.</div>'}
    <div class="sign"><div>Le client</div><div>Pour ${esc(soc)}</div></div></body></html>`);
  w.document.close(); w.focus(); setTimeout(() => w.print(), 300);
}

async function encaisserPiecesModal(pieces, titre, refresh) {
  if (!pieces.length) { toast("Rien à encaisser.", "ok"); return; }
  const caisses = await api(`/caisses?societe_id=${currentSocieteId}`).catch(() => []);
  const total = Math.round(pieces.reduce((s2, x) => s2 + x.montant, 0) * 100) / 100;
  modal({
    title: `${titre} — ${fmtNum(total)} $`,
    body: `<table><thead><tr><th>Pièce</th><th class="right">Solde $</th></tr></thead><tbody>
        ${pieces.map((x) => `<tr><td>${esc(x.libelle)}</td><td class="right">${fmtNum(x.montant)}</td></tr>`).join("")}
      </tbody><tfoot><tr class="total-row"><td><b>TOTAL À ENCAISSER</b></td><td class="right"><b>${fmtNum(total)}</b></td></tr></tfoot></table>
      <div class="form-row" style="margin-top:12px">
        <div class="form-group"><label class="form-label">Mode</label><select id="es-mode" class="form-select">
          <option value="espece">Espèces</option><option value="mobile_money">Mobile Money</option><option value="banque">Banque</option></select></div>
        <div class="form-group" id="es-caisse-grp"><label class="form-label">Caisse</label><select id="es-caisse" class="form-select">${caisses.map((c) => `<option value="${c.id}">${esc(c.libelle)}</option>`).join("")}</select></div>
        <div class="form-group"><label class="form-label">Devise</label><select id="es-dev" class="form-select"><option value="USD">USD</option><option value="CDF">CDF</option></select></div></div>
      <div class="banner"><i class="ti ti-info-circle"></i> « Plus tard » laisse la créance sur le compte du client — visible dans l'encours clients et sur la fiche du séjour.</div>`,
    footer: `<button class="btn" onclick="closeModal()">Encaisser plus tard (crédit)</button>
      <button class="btn btn-primary" id="es-ok"><i class="ti ti-cash"></i> Encaisser tout</button>`,
  });
  $("#es-mode").onchange = (e) => $("#es-caisse-grp").style.display = e.target.value === "espece" ? "" : "none";
  $("#es-ok").onclick = async () => {
    const mode = $("#es-mode").value;
    const devise = $("#es-dev").value;
    let regles = 0;
    try {
      for (const x of pieces) {
        const body = { mode, devise, montant: x.montant, caisse_id: mode === "espece" ? $("#es-caisse").value : null };
        if (devise === "CDF") {
          const taux = posCtx?.taux_cdf;
          if (!taux) { toast("Définissez le taux du jour pour encaisser en CDF.", "ko"); return; }
          body.montant = Math.round(x.montant * taux);
        }
        await api(`/ventes/factures/${x.id}/regler?societe_id=${currentSocieteId}`, { method: "POST", body });
        regles += 1;
      }
      closeModal(); toast(`${regles} pièce(s) réglée(s) — merci !`, "ok"); refresh();
    } catch (e) { toast(`${e.message} (${regles} pièce(s) déjà réglée(s))`, "ko"); refresh(); }
  };
}

// ── Chambres & housekeeping ──────────────────────────────────────────
RENDER["hotel-chambres"] = async () => {
  const el = $("#view-hotel-chambres");
  el.innerHTML = `<div class="muted">Chargement…</div>`;
  let chambres;
  try { chambres = await api(`/hotel/chambres?societe_id=${currentSocieteId}`); }
  catch (e) { el.innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }
  const actives = chambres.filter((c) => c.actif);
  const actionsEtat = { sale: [["nettoyage", "ti-spray", "Lancer nettoyage"], ["libre", "ti-check", "Marquer propre"]],
    nettoyage: [["libre", "ti-check", "Marquer propre"]],
    libre: [["maintenance", "ti-tool", "Maintenance"]],
    maintenance: [["libre", "ti-check", "Remettre en service"]] };
  el.innerHTML = `<div class="section-hdr" style="margin-bottom:12px">
      <div class="section-title"><i class="ti ti-door"></i> Chambres (${actives.length})</div>
      <button class="btn btn-sm btn-primary" id="hc-new" style="margin-left:auto"><i class="ti ti-plus"></i> Nouvelle chambre</button></div>
    <div class="caisse-cards">
      ${actives.map((c) => { const [sl, sc] = CHAMBRE_ST[c.etat] || [c.etat, ""]; return `
        <div class="caisse-card">
          <div class="cc-top"><b>Ch. ${esc(c.numero)}</b>${c.categorie ? ` <span class="tag">${esc(c.categorie)}</span>` : ""}
            <span class="pill ${sc}" style="margin-left:auto">${sl}</span>
            <button class="btn btn-sm" data-cedit="${c.id}" title="Modifier"><i class="ti ti-pencil"></i></button></div>
          <div class="muted" style="font-size:12px;margin:4px 0">${fmtNum(c.tarif_nuit_usd)} $/nuit · ${c.capacite} pers.${c.note ? `<br/>${esc(c.note)}` : ""}</div>
          ${c.sejour ? `<div class="muted" style="font-size:12px"><i class="ti ti-user"></i> ${esc(c.sejour.client)} — départ prévu ${c.sejour.date_depart_prevue}</div>` : ""}
          <div style="margin-top:8px;display:flex;gap:6px;flex-wrap:wrap">
            ${(actionsEtat[c.etat] || []).map(([e2, ic, lb]) => `<button class="btn btn-sm" data-etat="${c.id}:${e2}"><i class="ti ${ic}"></i> ${lb}</button>`).join("")}
          </div>
        </div>`; }).join("") || '<div class="empty"><i class="ti ti-door"></i>Aucune chambre — créez le parc.</div>'}
    </div>`;
  const refresh = () => RENDER["hotel-chambres"]();
  $("#hc-new").onclick = () => chambreModal(null, refresh);
  el.querySelectorAll("[data-cedit]").forEach((b) => b.onclick = () => chambreModal(chambres.find((c) => c.id === b.dataset.cedit), refresh));
  el.querySelectorAll("[data-etat]").forEach((b) => b.onclick = async () => {
    const [id, etat] = b.dataset.etat.split(":");
    try { await api(`/hotel/chambres/${id}?societe_id=${currentSocieteId}`, { method: "PATCH", body: { etat } });
      toast("État mis à jour.", "ok"); refresh(); } catch (e) { toast(e.message, "ko"); }
  });
};

function chambreModal(c, refresh) {
  modal({
    title: c ? `Modifier la chambre ${c.numero}` : "Nouvelle chambre",
    body: `<div class="form-row">
        <div class="form-group"><label class="form-label">Numéro</label><input id="ch-num" class="form-input" value="${esc(c?.numero || "")}" placeholder="ex. 101" /></div>
        <div class="form-group"><label class="form-label">Catégorie</label><input id="ch-cat" class="form-input" value="${esc(c?.categorie || "")}" placeholder="Standard, Suite…" /></div></div>
      <div class="form-row">
        <div class="form-group"><label class="form-label">Tarif par nuit (USD)</label><input id="ch-tarif" class="form-input right" type="number" step="any" value="${c?.tarif_nuit_usd ?? ""}" /></div>
        <div class="form-group"><label class="form-label">Capacité (personnes)</label><input id="ch-cap" class="form-input right" type="number" min="1" value="${c?.capacite ?? 2}" /></div></div>
      <div class="form-group"><label class="form-label">Note</label><input id="ch-note" class="form-input" value="${esc(c?.note || "")}" /></div>
      ${c ? `<label style="display:flex;align-items:center;gap:8px;font-size:13px"><input type="checkbox" id="ch-actif" ${c.actif ? "checked" : ""} style="width:auto" /> Chambre active</label>` : ""}`,
    footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="ch-ok"><i class="ti ti-check"></i> ${c ? "Enregistrer" : "Créer"}</button>`,
  });
  $("#ch-ok").onclick = async () => {
    const body = { numero: $("#ch-num").value, categorie: $("#ch-cat").value || null,
      tarif_nuit_usd: +$("#ch-tarif").value || 0, capacite: +$("#ch-cap").value || 2,
      note: $("#ch-note").value || null };
    if (c) body.actif = $("#ch-actif").checked;
    try {
      await api(c ? `/hotel/chambres/${c.id}?societe_id=${currentSocieteId}` : `/hotel/chambres?societe_id=${currentSocieteId}`,
        { method: c ? "PATCH" : "POST", body });
      closeModal(); toast(c ? "Chambre modifiée." : "Chambre créée.", "ok"); refresh();
    } catch (e) { toast(e.message, "ko"); }
  };
}

// ═════════════════════════════════════════════════════════════════════
// EXPORTS — Excel (CSV) et PDF (impression) génériques pour les modules
// ═════════════════════════════════════════════════════════════════════
function exporterExcel(nomFichier, colonnes, lignes) {
  return Editions.excel(nomFichier,colonnes,lignes);
}
function imprimerRapport(titre,sousTitre,colonnes,lignes,pied="") {
  return Editions.tableau(titre,sousTitre,colonnes,lignes,pied);
}

function boutonsExport(idBase) {
  return `<button class="btn btn-sm" id="${idBase}-xls" title="Télécharger un classeur Excel (.xlsx)"><i class="ti ti-file-spreadsheet"></i> Excel</button>
    <button class="btn btn-sm" id="${idBase}-pdf" title="Imprimer / PDF"><i class="ti ti-printer"></i> PDF</button>`;
}

// ═════════════════════════════════════════════════════════════════════
// CONFIGURATION PAR MODULE — réglages + données de base (guide numéroté)
// ═════════════════════════════════════════════════════════════════════
async function renderConfigModule(elId, intro, sections) {
  const el = $(elId);
  el.innerHTML = `<div class="muted">Chargement…</div>`;
  const compteurs = await Promise.all(sections.map((s) =>
    s.count ? s.count().catch(() => "—") : Promise.resolve(null)));
  el.innerHTML = `
    <div class="banner" style="margin-bottom:14px"><i class="ti ti-list-numbers"></i> ${intro}</div>
    <div class="caisse-cards">
    ${sections.map((s, i) => `<div class="caisse-card">
      <div class="cc-top"><b>${i + 1}. ${s.titre}</b>${compteurs[i] != null ? `<span class="pill ${String(compteurs[i]).startsWith("0") ? "st-due" : "st-payee"}" style="margin-left:auto">${compteurs[i]}</span>` : ""}</div>
      <div class="muted" style="font-size:12px;margin:6px 0;min-height:32px">${s.desc}</div>
      <div style="display:flex;gap:6px;flex-wrap:wrap">
        ${s.actions.map((a, j) => `<button class="btn btn-sm ${j === 0 ? "btn-primary" : ""}" data-cfg="${i}:${j}"><i class="ti ${a.icone || "ti-arrow-right"}"></i> ${a.label}</button>`).join("")}</div>
    </div>`).join("")}</div>`;
  el.querySelectorAll("[data-cfg]").forEach((b) => b.onclick = () => {
    const [i, j] = b.dataset.cfg.split(":").map(Number);
    sections[i].actions[j].onclick();
  });
}

RENDER["config-hotel"] = () => {
  const refresh = () => RENDER["config-hotel"]();
  renderConfigModule("#view-config-hotel",
    "Pour démarrer l'hôtel, suivez les étapes dans l'ordre : les pastilles rouges signalent ce qui manque encore.",
    [
      { titre: "Chambres & tarifs",
        desc: "Créez chaque chambre : numéro, catégorie, tarif par nuit, capacité. C'est la base des réservations.",
        count: async () => `${(await api(`/hotel/chambres?societe_id=${currentSocieteId}`)).filter((c) => c.actif).length} chambre(s)`,
        actions: [{ label: "Nouvelle chambre", icone: "ti-plus", onclick: () => chambreModal(null, refresh) },
                  { label: "Chambres & ménage", onclick: () => go("hotel-chambres") }] },
      { titre: "Caisses",
        desc: "Une caisse par point d'encaissement : la principale (réception) est créée avec la société — ajoutez une caisse par bar et restaurant.",
        count: async () => `${(await api(`/caisses?societe_id=${currentSocieteId}`)).length} caisse(s)`,
        actions: [{ label: "Nouvelle caisse", icone: "ti-plus", onclick: () => caisseModal(null, refresh) },
                  { label: "Journal & soldes", onclick: () => go("caisse") }] },
      { titre: "Articles bar & restaurant",
        desc: "Boissons (stock géré) et plats/services (sans stock). Catégorie = regroupement à l'écran du POS.",
        count: async () => `${(await api(`/commercial/articles?societe_id=${currentSocieteId}`)).length} article(s)`,
        actions: [{ label: "Nouvel article", icone: "ti-plus", onclick: () => articleModal() },
                  { label: "Référentiel articles", onclick: () => go("articles") }] },
      { titre: "Dépôts bar & restaurant",
        desc: "Le dépôt central reçoit les achats ; créez un dépôt par comptoir et approvisionnez-le par bons de transfert.",
        count: async () => `${(await api(`/stock/depots?societe_id=${currentSocieteId}`)).filter((d) => d.type !== "central").length} dépôt(s) dédié(s)`,
        actions: [{ label: "Dépôts & transferts", icone: "ti-plus", onclick: () => go("depots") }] },
      { titre: "Points de vente Restaurant & Bar",
        desc: "Un point de vente par comptoir, avec sa liste de prix, sa caisse et son dépôt. Le POS existant fait le reste (dont « Sur la chambre »).",
        count: async () => `${(await api(`/commercial/points-vente?societe_id=${currentSocieteId}`)).length} point(s) de vente`,
        actions: [{ label: "Tarifs & points de vente", icone: "ti-plus", onclick: () => go("tarifs-pos") }] },
      { titre: "Cuisine & food cost",
        desc: "Créez le Dépôt Cuisine, choisissez-le dans les réglages ⚙ de la page Cuisine, puis décrivez la fiche technique de chaque plat.",
        count: async () => `${(await api(`/cuisine/fiches?societe_id=${currentSocieteId}`)).length} fiche(s) technique(s)`,
        actions: [{ label: "Cuisine & food cost", icone: "ti-plus", onclick: () => go("cuisine") }] },
      { titre: "Équipe & rôles",
        desc: "Affectez vos réceptionnistes (rôle RECEPTIONNISTE) et caissiers à la société GHR dans Administration.",
        actions: [{ label: "Administration", onclick: () => go("administration") }] },
      { titre: "Comptes & TVA",
        desc: "Produit hébergement au 7062 (paramètre compte.compte_vente_hebergement), TVA par défaut — dans le Paramétrage général.",
        actions: [{ label: "Paramétrage", onclick: () => go("config") }] },
    ]);
};

RENDER["config-engins"] = () => {
  const refresh = () => RENDER["config-engins"]();
  renderConfigModule("#view-config-engins",
    "Location d'engins : réglez le module, créez le parc, puis la saisie des heures peut commencer.",
    [
      { titre: "Réglages du module",
        desc: "Forfait mensuel d'heures (208 h), règle d'arrondi 5 min, préfixe des RPE, nom du locataire affiché.",
        actions: [{ label: "Modifier les réglages", icone: "ti-settings",
          onclick: async () => enginsConfigModal(await api(`/engins/config?societe_id=${currentSocieteId}`)) }] },
      { titre: "Parc d'engins & tarifs",
        desc: "Chaque engin : tarif mensuel (forfait), tarif d'heure supplémentaire, consommation théorique L/h pour le suivi carburant.",
        count: async () => `${(await api(`/engins/engins?societe_id=${currentSocieteId}&actifs=1`)).length} engin(s)`,
        actions: [{ label: "Nouvel engin", icone: "ti-plus", onclick: () => enginModal() },
                  { label: "Parc d'engins", onclick: () => go("engins-parc") }] },
      { titre: "Client locataire",
        desc: "Le client facturé chaque mois (ex. GCK / Production) — un tiers de type « client » de la société.",
        count: async () => `${(await api(`/commercial/tiers?societe_id=${currentSocieteId}&type=client`)).length} client(s)`,
        actions: [{ label: "Administration (tiers)", onclick: () => go("administration") }] },
      { titre: "Plans d'entretien",
        desc: "Entretiens préventifs par engin (toutes les X heures prestées ou X jours) — gérés par le module Maintenance.",
        actions: [{ label: "Maintenance — parc & échéances", onclick: () => go("maintenance-parc") }] },
    ]);
};

RENDER["config-transport"] = () => {
  const refresh = () => RENDER["config-transport"]();
  renderConfigModule("#view-config-transport",
    "Transport : réglez le validateur, créez la flotte et les contrats — les fiches de course s'appuient dessus.",
    [
      { titre: "Réglages du module",
        desc: "Le rôle qui valide les fiches de course avant départ (DFI par défaut).",
        actions: [{ label: "Modifier les réglages", icone: "ti-settings",
          onclick: async () => { await chargerTransportCfg(); reglagesTransportModal(); } }] },
      { titre: "Camions",
        desc: "Flotte propre ou sous-traitée (propriétaire + rémunération), capacité, consommation théorique L/100 km.",
        count: async () => `${(await api(`/transport/camions?societe_id=${currentSocieteId}`)).filter((c) => c.actif).length} camion(s)`,
        actions: [{ label: "Nouveau camion", icone: "ti-plus", onclick: () => camionModal() },
                  { label: "Flotte & maintenance", onclick: () => go("flotte") }] },
      { titre: "Chauffeurs",
        desc: "Chaque chauffeur reçoit automatiquement un tiers « personnel » pour ses avances à justifier.",
        count: async () => `${(await api(`/transport/chauffeurs?societe_id=${currentSocieteId}`)).length} chauffeur(s)`,
        actions: [{ label: "Nouveau chauffeur", icone: "ti-plus", onclick: () => chauffeurModal() }] },
      { titre: "Contrats de transport",
        desc: "Contrats-cadres clients avec grilles tarifaires par trajet (à la tonne ou au voyage).",
        count: async () => `${(await api(`/transport/contrats?societe_id=${currentSocieteId}`)).length} contrat(s)`,
        actions: [{ label: "Nouveau contrat", icone: "ti-plus", onclick: () => contratModal() },
                  { label: "Contrats de transport", onclick: () => go("contrats-transport") }] },
      { titre: "Documents & échéances",
        desc: "Assurances, contrôles techniques, permis des chauffeurs — avec alertes avant expiration.",
        actions: [{ label: "Documents & échéances", onclick: () => go("flotte-documents") }] },
    ]);
};

RENDER["config-maintenance"] = () => {
  renderConfigModule("#view-config-maintenance",
    "Maintenance : le métier du maintenancier, séparé du dispatching — équipe, plans préventifs et conformité documentaire.",
    [
      { titre: "Équipe & rôles",
        desc: "Affectez vos maintenanciers (rôle MAINTENANCIER) et le Directeur Technique (DT) aux sociétés concernées.",
        actions: [{ label: "Administration", onclick: () => go("administration") }] },
      { titre: "Plans d'entretien préventif",
        desc: "Par véhicule : toutes les X heures, X courses, X km ou X jours — l'échéance suit l'usage réel. Modifiables et supprimables depuis les cartes du parc.",
        count: async () => `${(await api(`/maintenance/plans?societe_id=${currentSocieteId}`)).filter((p) => p.actif).length} plan(s)`,
        actions: [{ label: "Parc & échéances", icone: "ti-plus", onclick: () => go("maintenance-parc") }] },
      { titre: "Consommations théoriques",
        desc: "L/100 km des camions (fiche camion) et L/heure des engins (fiche engin) — la base des alertes de surconsommation carburant.",
        actions: [{ label: "Suivi carburant", onclick: () => go("carburant") }] },
      { titre: "Documents & échéances du parc",
        desc: "Contrôles techniques, assurances et permis — modifiables, renouvelables et supprimables, avec alertes à 30 jours.",
        count: async () => { const d = await api(`/flotte/documents?societe_id=${currentSocieteId}`); return `${d.documents.length} document(s)`; },
        actions: [{ label: "Documents & échéances", icone: "ti-plus", onclick: () => go("flotte-documents") }] },
    ]);
};

// ═════════════════════════════════════════════════════════════════════
// DÉPÔTS & TRANSFERTS — central → dédiés (bar, restaurant, cuisine…)
// ═════════════════════════════════════════════════════════════════════
let depotEtatOuvert = null;

RENDER.depots = async () => {
  const el = $("#view-depots");
  el.innerHTML = `<div class="muted">Chargement…</div>`;
  let deps, transferts, inventaires;
  try {
    [deps, transferts, inventaires] = await Promise.all([
      api(`/stock/depots?societe_id=${currentSocieteId}`),
      api(`/stock/transferts?societe_id=${currentSocieteId}`),
      api(`/stock/inventaires?societe_id=${currentSocieteId}`).catch(() => []),
    ]);
  } catch (e) { el.innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }
  const gestionnaire = has("DFI", "PRESIDENT", "ADMIN_SYS", "DG");
  el.innerHTML = `
    <div class="section-hdr" style="margin-bottom:12px">
      <div class="section-title"><i class="ti ti-building-warehouse"></i> Dépôts (${deps.length})</div>
      <div style="margin-left:auto;display:flex;gap:8px">
        <button class="btn btn-sm btn-primary" id="dp-transfert" ${deps.length < 2 ? "disabled title=\"Créez d'abord un dépôt dédié\"" : ""}><i class="ti ti-transfer"></i> Nouveau transfert</button>
        ${gestionnaire ? `<button class="btn btn-sm" id="dp-new"><i class="ti ti-plus"></i> Nouveau dépôt</button>` : ""}</div></div>
    <div class="caisse-cards">
      ${deps.map((d) => `<div class="caisse-card">
        <div class="cc-top"><b>${esc(d.libelle)}</b>
          <span class="tag">${d.type === "central" ? "central" : "dédié"}</span>
          ${d.point_vente ? `<span class="tag" title="point de vente lié">${esc(d.point_vente)}</span>` : ""}
          ${gestionnaire && d.type !== "central" ? `<button class="btn btn-sm" data-dpmod="${d.id}" title="Modifier" style="margin-left:auto"><i class="ti ti-pencil"></i></button>` : ""}</div>
        <div class="muted" style="font-size:12px;margin:6px 0"><b>${fmtNum(d.valeur_stock_usd)} $</b> de stock · ${d.nb_references} référence(s)</div>
        <div style="display:flex;gap:6px;flex-wrap:wrap">
          <button class="btn btn-sm" data-dpetat="${d.id}"><i class="ti ti-list-details"></i> Stock</button>
          <button class="btn btn-sm" data-dpinv="${d.id}" title="Comptage physique : écart théorique vs réel"><i class="ti ti-clipboard-check"></i> Inventaire</button></div>
      </div>`).join("")}
    </div>
    <div id="dp-etat" style="margin-top:14px"></div>
    <div class="card" style="margin-top:14px"><div class="card-hdr"><div class="card-hdr-title"><i class="ti ti-transfer"></i> Derniers transferts</div></div>
      <div class="card-body">${!transferts.length ? '<div class="muted">Aucun transfert — approvisionnez vos dépôts dédiés depuis le central.</div>' : `
        <table><thead><tr><th>N°</th><th>Date</th><th>De</th><th>Vers</th><th class="right">Lignes</th><th class="right">Valeur $</th><th></th></tr></thead><tbody>
        ${transferts.map((t) => `<tr>
          <td class="num-cell">${esc(t.numero)}</td><td>${t.date}</td>
          <td>${esc(t.source)}</td><td><b>${esc(t.cible)}</b></td>
          <td class="right">${t.lignes.length}</td><td class="right"><b>${fmtNum(t.valeur_totale)}</b></td>
          <td class="right"><button class="btn btn-sm" data-tdprint="${t.id}" title="Imprimer le bon"><i class="ti ti-printer"></i></button></td></tr>`).join("")}
        </tbody></table>`}</div></div>
    <div class="card" style="margin-top:14px"><div class="card-hdr"><div class="card-hdr-title"><i class="ti ti-clipboard-check"></i> Derniers inventaires</div></div>
      <div class="card-body">${!inventaires.length ? '<div class="muted">Aucun inventaire — comptez régulièrement vos dépôts (bar, cuisine) pour chiffrer les écarts.</div>' : `
        <table><thead><tr><th>N°</th><th>Date</th><th>Dépôt</th><th class="right">Théorique $</th><th class="right">Réel $</th><th class="right">Écart $</th><th></th></tr></thead><tbody>
        ${inventaires.map((iv) => `<tr>
          <td class="num-cell">${esc(iv.numero)}<div class="muted">${iv.statut === "brouillon" ? "Comptage à valider" : iv.statut === "annule" ? "Annulé" : "Validé"}</div></td><td>${iv.date}</td><td>${esc(iv.depot)}</td>
          <td class="right">${fmtNum(iv.valeur_theorique)}</td><td class="right">${fmtNum(iv.valeur_reelle)}</td>
          <td class="right"><b style="${iv.ecart_valeur < -0.004 ? "color:var(--r)" : iv.ecart_valeur > 0.004 ? "color:var(--g)" : ""}">${fmtNum(iv.ecart_valeur)}</b></td>
          <td class="right"><button class="btn btn-sm" data-ivprint="${iv.id}" title="Imprimer"><i class="ti ti-printer"></i></button></td></tr>`).join("")}
        </tbody></table>`}</div></div>`;
  const refresh = () => RENDER.depots();
  const dpNew = $("#dp-new");
  if (dpNew) dpNew.onclick = () => {
    modal({ title: "Nouveau dépôt dédié",
      body: `<div class="form-group"><label class="form-label">Libellé</label><input id="dd-lib" class="form-input" placeholder="ex. Dépôt Bar, Dépôt Cuisine…" /></div>
        <div class="banner"><i class="ti ti-info-circle"></i> Le dépôt central reçoit tous les achats ; approvisionnez ce dépôt par transferts, puis liez-le à son point de vente dans « Tarifs & points de vente ».</div>`,
      footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="dd-ok"><i class="ti ti-check"></i> Créer</button>` });
    $("#dd-ok").onclick = async () => {
      try { await api(`/stock/depots?societe_id=${currentSocieteId}`, { method: "POST", body: { libelle: $("#dd-lib").value } });
        closeModal(); toast("Dépôt créé — approvisionnez-le par transfert.", "ok"); refresh(); } catch (e) { toast(e.message, "ko"); }
    };
  };
  el.querySelectorAll("[data-dpmod]").forEach((b) => b.onclick = () => {
    const d = deps.find((x) => x.id === b.dataset.dpmod);
    modal({ title: `Modifier — ${d.libelle}`,
      body: `<div class="form-group"><label class="form-label">Libellé</label><input id="dd-lib" class="form-input" value="${esc(d.libelle)}" /></div>
        <label style="display:flex;align-items:center;gap:8px;font-size:13px"><input type="checkbox" id="dd-actif" ${d.actif ? "checked" : ""} style="width:auto" /> Dépôt actif (fermeture possible seulement à stock vide)</label>`,
      footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="dd-ok"><i class="ti ti-check"></i> Enregistrer</button>` });
    $("#dd-ok").onclick = async () => {
      try { await api(`/stock/depots/${d.id}?societe_id=${currentSocieteId}`, { method: "PATCH", body: { libelle: $("#dd-lib").value, actif: $("#dd-actif").checked } });
        closeModal(); toast("Dépôt modifié.", "ok"); refresh(); } catch (e) { toast(e.message, "ko"); }
    };
  });
  el.querySelectorAll("[data-dpetat]").forEach((b) => b.onclick = async () => {
    try {
      const d = await api(`/stock/depots-etat?societe_id=${currentSocieteId}&depot_id=${b.dataset.dpetat}`);
      $("#dp-etat").innerHTML = `<div class="card"><div class="card-hdr"><div class="card-hdr-title"><i class="ti ti-packages"></i> Stock — ${esc(d.depot.libelle)} (${fmtNum(d.valeur_totale)} $)</div></div>
        <div class="card-body">${!d.articles.length ? '<div class="muted">Dépôt vide.</div>' : `
        <table><thead><tr><th>Code</th><th>Article</th><th class="right">Qté</th><th class="right">CUMP $</th><th class="right">Valeur $</th></tr></thead><tbody>
        ${d.articles.map((a) => `<tr><td class="num-cell">${esc(a.code)}</td><td>${esc(a.designation)}</td>
          <td class="right"><b>${fmtNum(a.qte)}</b> ${esc(a.unite)}</td><td class="right">${a.cump.toFixed(2).replace(".", ",")}</td>
          <td class="right">${fmtNum(a.valeur)}</td></tr>`).join("")}
        </tbody></table>`}</div></div>`;
      $("#dp-etat").scrollIntoView({ behavior: "smooth", block: "nearest" });
    } catch (e) { toast(e.message, "ko"); }
  });
  el.querySelectorAll("[data-tdprint]").forEach((b) => b.onclick = () => {
    const t = transferts.find((x) => x.id === b.dataset.tdprint);
    imprimerRapport(`Bon de transfert ${t.numero}`, `${t.date} · ${t.source} → ${t.cible}${t.note ? " · " + t.note : ""}`,
      ["Code", "Article", "Qté", "Valeur $ (CUMP source)"],
      t.lignes.map((l) => [l.code, l.designation, l.qte, l.valeur]),
      `Valeur totale transférée : <b>${fmtNum(t.valeur_totale)} $</b>. Signatures : magasinier cédant ______________ · réceptionnaire ______________`);
  });
  $("#dp-transfert").onclick = () => transfertDepotModal(deps, refresh);
  el.querySelectorAll("[data-dpinv]").forEach((b) => b.onclick = () =>
    inventaireDepotModal(deps.find((d) => d.id === b.dataset.dpinv), refresh));
  el.querySelectorAll("[data-ivprint]").forEach((b) => b.onclick = () => {
    const iv = inventaires.find((x) => x.id === b.dataset.ivprint);
    imprimerRapport(`Inventaire ${iv.numero} — ${iv.depot}`, `${iv.statut === "brouillon" ? "COMPTAGE NON VALIDÉ — STOCK INCHANGÉ" : iv.statut === "annule" ? "ANNULÉ" : "VALIDÉ"} · ${iv.date}` + (iv.note ? " · " + iv.note : ""),
      ["Code", "Article", "Théorique", "Compté", "Écart qté", "Écart $"],
      iv.lignes.map((l) => [l.code, l.designation, l.qte_theorique, l.qte_reelle, l.ecart_qte, l.ecart_valeur]),
      `Valeur théorique ${fmtNum(iv.valeur_theorique)} $ · réelle ${fmtNum(iv.valeur_reelle)} $ · <b>écart ${fmtNum(iv.ecart_valeur)} $</b>. Signatures : compteur ______________ · contrôleur ______________`);
  });
};

async function inventaireDepotModal(depot, refresh) {
  return Clotures.comptage(depot, refresh);
}

async function transfertDepotModal(deps, refresh) {
  const articles = (await api(`/commercial/articles?societe_id=${currentSocieteId}`).catch(() => []))
    .filter((a) => a.gere_stock !== false && a.actif !== false);
  const central = deps.find((d) => d.type === "central");
  let lignes = [];
  let optionsArt = articles.map((a) => `<option value="${a.id}">${esc(a.code)} — ${esc(a.designation)}${a.nature === "matiere_premiere" ? " · matière première" : a.nature === "consommable" ? " · consommable" : ""}</option>`).join("");
  modal({ wide: true,
    title: "Transfert entre dépôts",
    body: `<div class="form-row">
        <div class="form-group"><label class="form-label">Depuis</label><select id="td-src" class="form-select">${deps.map((d) => `<option value="${d.id}" ${d.type === "central" ? "selected" : ""}>${esc(d.libelle)}</option>`).join("")}</select></div>
        <div class="form-group"><label class="form-label">Vers</label><select id="td-cib" class="form-select">${deps.map((d) => `<option value="${d.id}" ${central && d.id !== central.id ? "" : "disabled"}>${esc(d.libelle)}</option>`).join("")}</select></div>
        <div class="form-group"><label class="form-label">Note</label><input id="td-note" class="form-input" placeholder="facultatif" /></div></div>
      <div id="td-lignes"></div>
      <button class="btn btn-sm" id="td-add"><i class="ti ti-plus"></i> Ajouter un article</button>
      <div class="banner" style="margin-top:10px"><i class="ti ti-info-circle"></i> Transfert valorisé au CUMP du dépôt source — aucun impact comptable, seuls les soldes par dépôt changent. Un bon TD numéroté est généré.</div>`,
    footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="td-ok"><i class="ti ti-transfer"></i> Transférer</button>`,
  });
  const host = $("#td-lignes");
  const dessiner = () => {
    host.innerHTML = lignes.map((l, i) => `<div class="form-row" style="margin-bottom:6px;align-items:end">
      <div class="form-group" style="margin:0;flex:2"><select class="form-select td-art" data-i="${i}">${optionsArt.replace(`value="${l.article_id}"`, `value="${l.article_id}" selected`)}</select></div>
      <div class="form-group" style="margin:0"><input class="form-input right td-qte" data-i="${i}" type="number" step="any" value="${l.qte || ""}" placeholder="Qté" style="width:100px" /></div>
      <button class="btn btn-sm td-del" data-i="${i}" style="height:34px"><i class="ti ti-x"></i></button></div>`).join("");
    host.querySelectorAll(".td-art").forEach((s) => s.onchange = (e) => { lignes[+e.target.dataset.i].article_id = e.target.value; });
    host.querySelectorAll('.td-art').forEach(select=>Catalogue.bind(select,{kind:'article',stockRequired:true,create:has('DFI','COMPTABLE'),accept:a=>{
      if(!articles.some(x=>x.id===a.id)){articles.push(a);optionsArt+=`<option value="${a.id}">${esc(a.code)} — ${esc(a.designation)}</option>`;}
    }}));
    host.querySelectorAll(".td-qte").forEach((s) => s.onchange = (e) => { lignes[+e.target.dataset.i].qte = +e.target.value || 0; });
    host.querySelectorAll(".td-del").forEach((b) => b.onclick = () => { lignes.splice(+b.dataset.i, 1); dessiner(); });
  };
  $("#td-add").onclick = () => { lignes.push({ article_id: articles[0]?.id, qte: 0 }); dessiner(); };
  $("#td-add").click();
  $("#td-ok").onclick = async () => {
    const corps = { depot_source_id: $("#td-src").value, depot_cible_id: $("#td-cib").value,
      note: $("#td-note").value || null,
      lignes: lignes.filter((l) => l.article_id && +l.qte > 0).map((l) => ({ article_id: l.article_id, qte: +l.qte })) };
    if (!corps.lignes.length) { toast("Ajoutez au moins un article avec une quantité.", "ko"); return; }
    try {
      const t = await api(`/stock/transferts?societe_id=${currentSocieteId}`, { method: "POST", body: corps });
      closeModal(); toast(`Transfert ${t.numero} effectué — ${fmtNum(t.valeur_totale)} $.`, "ok"); refresh();
    } catch (e) { toast(e.message, "ko"); }
  };
}

// ═════════════════════════════════════════════════════════════════════
// CUISINE & FOOD COST — fiches techniques, conso théorique, ratio
// ═════════════════════════════════════════════════════════════════════
RENDER.cuisine = async () => {
  const el = $("#view-cuisine");
  el.innerHTML = `<div class="muted">Chargement…</div>`;
  let cfg, fiches, consos, rapport;
  try {
    [cfg, fiches, consos, rapport] = await Promise.all([
      api(`/cuisine/config?societe_id=${currentSocieteId}`),
      api(`/cuisine/fiches?societe_id=${currentSocieteId}`),
      api(`/cuisine/consommations?societe_id=${currentSocieteId}`),
      api(`/cuisine/rapport?societe_id=${currentSocieteId}`),
    ]);
  } catch (e) { el.innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }
  const fcPill = (pct) => pct == null ? "—"
    : `<span class="pill ${pct > cfg.seuil_food_cost_pct ? "st-due" : "st-payee"}">${String(pct).replace(".", ",")} %</span>`;
  el.innerHTML = `
    ${cfg.depot_est_central ? `<div class="banner" style="margin-bottom:12px"><i class="ti ti-alert-triangle"></i> La cuisine consomme pour l'instant depuis le <b>dépôt central</b> — créez un « Dépôt Cuisine » (Dépôts & transferts) puis choisissez-le dans les réglages ⚙ pour un contrôle propre.</div>` : ""}
    <div class="banner" style="margin-bottom:12px">Inventaires validés du mois au dépôt « ${esc(rapport.depot_inventaire)} » : <b>${rapport.inventaires_valides}</b> · Manquants <b>${fmtNum(rapport.manquants_inventaire)} $</b> · Excédents <b>${fmtNum(rapport.excedents_inventaire)} $</b>.<br>Les ratios ci-dessous restent théoriques. Les écarts sont présentés séparément pour leur suivi comptable.</div>
    ${rapport.alerte ? `<div class="banner" style="margin-bottom:12px"><i class="ti ti-alert-triangle"></i> <b>Food cost du mois à ${String(rapport.food_cost_pct).replace(".", ",")} %</b> — au-dessus du seuil de ${String(rapport.seuil_pct).replace(".", ",")} %.</div>` : ""}
    <div class="section-hdr" style="margin-bottom:12px">
      <div class="section-title"><i class="ti ti-chef-hat"></i> Cuisine — dépôt « ${esc(cfg.depot)} »</div><button class="btn btn-sm" onclick="go('inventaires')">Inventaires & écarts</button>
      <div style="margin-left:auto;display:flex;gap:8px">
        ${has("DFI", "PRESIDENT", "ADMIN_SYS", "DG") ? `<button class="btn btn-sm" id="cu-cfg" title="Réglages (dépôt, seuil)"><i class="ti ti-settings"></i></button>` : ""}
        <button class="btn btn-sm btn-primary" id="cu-gen"><i class="ti ti-flame"></i> Générer la consommation du jour</button></div></div>
    <div class="kpi-row" style="margin-bottom:14px">
      <div class="kpi-card" style="--accent:${rapport.alerte ? "var(--r)" : "var(--g)"}"><div class="kpi-label"><i class="ti ti-percentage"></i> Food cost du mois</div>
        <div class="kpi-val" ${rapport.alerte ? 'style="color:var(--r)"' : ""}>${rapport.food_cost_pct != null ? String(rapport.food_cost_pct).replace(".", ",") + " %" : "—"}</div>
        <div class="kpi-sub">seuil d'alerte : ${String(rapport.seuil_pct).replace(".", ",")} %</div></div>
      <div class="kpi-card"><div class="kpi-label"><i class="ti ti-shopping-cart"></i> Coût théorique</div>
        <div class="kpi-val">${fmtNum(rapport.cout_theorique)} $</div><div class="kpi-sub">matières consommées (fiches)</div></div>
      <div class="kpi-card" style="--accent:var(--p)"><div class="kpi-label"><i class="ti ti-cash"></i> CA plats</div>
        <div class="kpi-val">${fmtNum(rapport.ca_plats)} $</div><div class="kpi-sub">${fmtNum(rapport.nb_plats)} plat(s) vendu(s)</div></div>
      <div class="kpi-card"><div class="kpi-label"><i class="ti ti-calendar-check"></i> Jours générés</div>
        <div class="kpi-val">${rapport.jours_generes}</div><div class="kpi-sub">consommations du mois</div></div></div>
    <div class="card" style="margin-bottom:14px"><div class="card-hdr"><div class="card-hdr-title"><i class="ti ti-notebook"></i> Fiches techniques (${fiches.length})</div>
        <button class="btn btn-sm btn-primary" id="cu-fiche" style="margin-left:auto"><i class="ti ti-plus"></i> Nouvelle fiche</button></div>
      <div class="card-body">${!fiches.length ? '<div class="empty"><i class="ti ti-notebook"></i>Aucune fiche — décrivez la recette de chaque plat pour activer le food cost.</div>' : `
      <table><thead><tr><th>Plat</th><th class="right">Prix vente $</th><th class="right">Coût portion $</th><th class="right">Food cost</th><th class="right">Marge $</th><th>Ingrédients</th><th></th></tr></thead><tbody>
      ${fiches.map((f) => `<tr>
        <td><b>${esc(f.plat)}</b></td>
        <td class="right">${fmtNum(f.prix_vente)}</td>
        <td class="right"><b>${fmtNum(f.cout_portion)}</b></td>
        <td class="right">${fcPill(f.food_cost_pct)}</td>
        <td class="right">${fmtNum(f.marge_portion)}</td>
        <td class="muted" style="font-size:11.5px">${f.lignes.map((l) => `${esc(l.designation)} ${String(l.qte_par_portion).replace(".", ",")} ${esc(l.unite)}`).join(" · ")}</td>
        <td class="right" style="white-space:nowrap">
          <button class="btn btn-sm" data-fedit="${f.id}"><i class="ti ti-pencil"></i></button>
          <button class="btn btn-sm" data-fdel2="${f.id}"><i class="ti ti-trash"></i></button></td></tr>`).join("")}
      </tbody></table>`}</div></div>
    <div class="card"><div class="card-hdr"><div class="card-hdr-title"><i class="ti ti-flame"></i> Consommations théoriques</div></div>
      <div class="card-body">${!consos.length ? '<div class="muted">Aucune consommation générée — cliquez « Générer la consommation du jour » chaque soir.</div>' : `
      <table><thead><tr><th>Date</th><th>N°</th><th class="right">Plats</th><th class="right">Coût $</th><th class="right">CA $</th><th class="right">Food cost</th><th></th></tr></thead><tbody>
      ${consos.map((c) => `<tr>
        <td>${c.date}</td><td class="num-cell">${esc(c.numero)}</td>
        <td class="right">${fmtNum(c.nb_plats)}</td>
        <td class="right"><b>${fmtNum(c.cout_total)}</b></td>
        <td class="right">${fmtNum(c.ca_total)}</td>
        <td class="right">${fcPill(c.food_cost_pct)}</td>
        <td class="right"><button class="btn btn-sm" data-cdet="${c.id}" title="Détail des matières"><i class="ti ti-list-details"></i></button></td></tr>`).join("")}
      </tbody></table>`}</div></div>`;
  const refresh = () => RENDER.cuisine();
  const btnCfg = $("#cu-cfg");
  if (btnCfg) btnCfg.onclick = async () => {
    const deps = await api(`/stock/depots?societe_id=${currentSocieteId}`).catch(() => []);
    modal({ title: "Réglages — cuisine",
      body: `<div class="form-row">
        <div class="form-group"><label class="form-label">Dépôt de la cuisine</label>
          <select id="cc-dep" class="form-select">${deps.map((d) => `<option value="${d.id}" ${cfg.depot_id === d.id ? "selected" : ""}>${esc(d.libelle)}${d.type === "central" ? " (central)" : ""}</option>`).join("")}</select></div>
        <div class="form-group"><label class="form-label">Seuil d'alerte food cost (%)</label>
          <input id="cc-seuil" class="form-input right" type="number" step="any" value="${cfg.seuil_food_cost_pct}" /></div></div>`,
      footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="cc-ok"><i class="ti ti-check"></i> Enregistrer</button>` });
    $("#cc-ok").onclick = async () => {
      try { await api(`/cuisine/config?societe_id=${currentSocieteId}`, { method: "POST",
          body: { depot_id: $("#cc-dep").value, seuil_food_cost_pct: +$("#cc-seuil").value } });
        closeModal(); toast("Réglages enregistrés.", "ok"); refresh(); } catch (e) { toast(e.message, "ko"); }
    };
  };
  $("#cu-gen").onclick = () => {
    modal({ title: "Générer la consommation théorique",
      body: `<div class="form-group"><label class="form-label">Journée à consommer</label>
        <input id="cg-date" class="form-input" type="date" value="${isoLocal(new Date())}" /></div>
        <div class="banner"><i class="ti ti-info-circle"></i> Ventes de plats du jour × fiches techniques → les matières sortent du dépôt « ${esc(cfg.depot)} » au coût moyen, avec la pièce comptable (en attente de validation). Une seule génération par jour.</div>`,
      footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="cg-ok"><i class="ti ti-flame"></i> Générer</button>` });
    $("#cg-ok").onclick = async () => {
      const jour = $("#cg-date").value;
      try {
        const r = await api(`/cuisine/consommations?societe_id=${currentSocieteId}`, { method: "POST", body: { date: jour } });
        closeModal();
        toast(`Consommation ${r.numero} : ${fmtNum(r.cout_total)} $ pour ${fmtNum(r.nb_plats)} plat(s).`, "ok");
        if (r.alertes && r.alertes.length) modal({ title: "Attention — stocks négatifs",
          body: `<div class="banner"><i class="ti ti-alert-triangle"></i> ${r.alertes.map(esc).join("<br/>")}</div>`,
          footer: `<button class="btn btn-primary" onclick="closeModal()">Compris</button>` });
        refresh();
      } catch (e) { toast(e.message, "ko"); }
    };
  };
  $("#cu-fiche").onclick = () => ficheTechniqueModal(null, refresh);
  el.querySelectorAll("[data-fedit]").forEach((b) => b.onclick = () =>
    ficheTechniqueModal(fiches.find((f) => f.id === b.dataset.fedit), refresh));
  el.querySelectorAll("[data-fdel2]").forEach((b) => b.onclick = async () => {
    const f = fiches.find((x) => x.id === b.dataset.fdel2);
    if (!confirm(`Supprimer la fiche technique de « ${f.plat} » ?`)) return;
    try { await api(`/cuisine/fiches/${f.id}?societe_id=${currentSocieteId}`, { method: "DELETE" });
      toast("Fiche supprimée.", "ok"); refresh(); } catch (e) { toast(e.message, "ko"); }
  });
  el.querySelectorAll("[data-cdet]").forEach((b) => b.onclick = () => {
    const c = consos.find((x) => x.id === b.dataset.cdet);
    modal({ title: `Consommation ${c.numero} — ${c.date}`,
      body: `<table><thead><tr><th>Code</th><th>Matière</th><th class="right">Qté consommée</th><th class="right">Valeur $</th></tr></thead><tbody>
        ${c.lignes.map((l) => `<tr><td class="num-cell">${esc(l.code)}</td><td>${esc(l.designation)}</td>
          <td class="right">${fmtNum(l.qte)}</td><td class="right">${fmtNum(l.valeur)}</td></tr>`).join("")}
        </tbody><tfoot><tr class="total-row"><td colspan="3"><b>COÛT THÉORIQUE — ${fmtNum(c.nb_plats)} plat(s), CA ${fmtNum(c.ca_total)} $</b></td>
        <td class="right"><b>${fmtNum(c.cout_total)}</b></td></tr></tfoot></table>`,
      footer: `<button class="btn" onclick="closeModal()">Fermer</button>` });
  });
};

async function ficheTechniqueModal(f, refresh) {
  const articles = await api(`/commercial/articles?societe_id=${currentSocieteId}`).catch(() => []);
  const plats = articles.filter((a) => a.actif !== false && (a.nature || "marchandise") === "marchandise");
  const ingredients = articles.filter((a) => a.gere_stock !== false && a.actif !== false)
    .sort((x, y) => ((x.nature === "marchandise") - (y.nature === "marchandise"))
      || x.designation.localeCompare(y.designation));
  let lignes = (f?.lignes || []).map((l) => ({ article_id: l.article_id, qte: l.qte }));
  let optIng = ingredients.map((a) => `<option value="${a.id}">${esc(a.code)} — ${esc(a.designation)} (${esc(a.unite || "unité")})</option>`).join("");
  modal({ wide: true,
    title: f ? `Fiche technique — ${f.plat}` : "Nouvelle fiche technique",
    body: `<div class="form-row">
        <div class="form-group"><label class="form-label">Plat (article vendu)</label>
          <select id="ft-plat" class="form-select" ${f ? "disabled" : ""}>${plats.map((a) => `<option value="${a.id}" ${f?.article_id === a.id ? "selected" : ""}>${esc(a.code)} — ${esc(a.designation)}</option>`).join("")}</select></div>
        <div class="form-group"><label class="form-label">Recette pour N portions</label><input id="ft-portions" class="form-input right" type="number" step="any" value="${f?.portions ?? 1}" /></div></div>
      <label class="form-label">Ingrédients (articles gérés en stock)</label>
      <div id="ft-lignes"></div>
      <button class="btn btn-sm" id="ft-add"><i class="ti ti-plus"></i> Ajouter un ingrédient</button>
      <div class="form-group" style="margin-top:10px"><label class="form-label">Note (préparation, grammages…)</label><input id="ft-note" class="form-input" value="${esc(f?.note || "")}" /></div>
      <div class="banner"><i class="ti ti-info-circle"></i> Le coût de revient se calcule au coût moyen du dépôt cuisine — il suit automatiquement vos prix d'achat.</div>`,
    footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="ft-ok"><i class="ti ti-check"></i> Enregistrer la fiche</button>`,
  });
  Catalogue.bind($('#ft-plat'),{kind:'article',nature:'marchandise',natureLocked:true,create:has('DFI','COMPTABLE')});
  const host = $("#ft-lignes");
  const dessiner = () => {
    host.innerHTML = lignes.map((l, i) => `<div class="form-row" style="margin-bottom:6px;align-items:end">
      <div class="form-group" style="margin:0;flex:2"><select class="form-select ft-art" data-i="${i}">${optIng.replace(`value="${l.article_id}"`, `value="${l.article_id}" selected`)}</select></div>
      <div class="form-group" style="margin:0"><input class="form-input right ft-qte" data-i="${i}" type="number" step="any" value="${l.qte || ""}" placeholder="Qté" style="width:110px" /></div>
      <button class="btn btn-sm ft-del" data-i="${i}" style="height:34px"><i class="ti ti-x"></i></button></div>`).join("");
    host.querySelectorAll(".ft-art").forEach((s) => s.onchange = (e) => { lignes[+e.target.dataset.i].article_id = e.target.value; });
    host.querySelectorAll('.ft-art').forEach(select=>Catalogue.bind(select,{kind:'article',nature:'matiere_premiere',stockRequired:true,create:has('DFI','COMPTABLE'),accept:a=>{
      if(!ingredients.some(x=>x.id===a.id)){ingredients.push(a);optIng+=`<option value="${a.id}">${esc(a.code)} — ${esc(a.designation)} (${esc(a.unite)})</option>`;}
    }}));
    host.querySelectorAll(".ft-qte").forEach((s) => s.onchange = (e) => { lignes[+e.target.dataset.i].qte = +e.target.value || 0; });
    host.querySelectorAll(".ft-del").forEach((b) => b.onclick = () => { lignes.splice(+b.dataset.i, 1); dessiner(); });
  };
  $("#ft-add").onclick = () => { lignes.push({ article_id: ingredients[0]?.id, qte: 0 }); dessiner(); };
  if (!lignes.length) $("#ft-add").click(); else dessiner();
  $("#ft-ok").onclick = async () => {
    const corps = { article_id: f ? f.article_id : $("#ft-plat").value,
      portions: +$("#ft-portions").value || 1, note: $("#ft-note").value || null,
      lignes: lignes.filter((l) => l.article_id && +l.qte > 0).map((l) => ({ article_id: l.article_id, qte: +l.qte })) };
    if (!corps.lignes.length) { toast("Ajoutez au moins un ingrédient avec sa quantité.", "ko"); return; }
    try {
      const r = await api(`/cuisine/fiches?societe_id=${currentSocieteId}`, { method: "POST", body: corps });
      closeModal(); toast(`Fiche enregistrée — coût de revient ${fmtNum(r.cout_portion)} $/portion.`, "ok"); refresh();
    } catch (e) { toast(e.message, "ko"); }
  };
}

// ── Gestion des caisses (plusieurs par société : une par point de vente) ─
function caisseModal(c, refresh) {
  modal({
    title: c ? `Modifier — ${c.libelle}` : "Nouvelle caisse",
    body: `<div class="form-row">
        <div class="form-group"><label class="form-label">Libellé</label><input id="cs-lib" class="form-input" placeholder="ex. Caisse Bar, Caisse Restaurant…" value="${esc(c?.libelle || "")}" /></div>
        <div class="form-group"><label class="form-label">Compte comptable (57x)</label><input id="cs-cpt" class="form-input" placeholder="vide = auto (5711, 5712…)" value="${esc(c?.compte || "")}" /></div></div>
      ${c && !c.est_principale ? `<label style="display:flex;align-items:center;gap:8px;font-size:13px"><input type="checkbox" id="cs-actif" ${c.actif !== false ? "checked" : ""} style="width:auto" /> Caisse active</label>` : ""}
      <div class="banner"><i class="ti ti-info-circle"></i> Chaque point de vente (bar, restaurant…) doit avoir sa propre caisse : créez la caisse ici, puis liez-la au point de vente dans « Tarifs & points de vente ». Le sous-compte 57x est créé automatiquement au plan comptable.</div>`,
    footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="cs-ok"><i class="ti ti-check"></i> ${c ? "Enregistrer" : "Créer la caisse"}</button>`,
  });
  $("#cs-ok").onclick = async () => {
    const body = { libelle: $("#cs-lib").value, compte_comptable: $("#cs-cpt").value || null };
    const actifEl = $("#cs-actif");
    if (actifEl) body.actif = actifEl.checked;
    try {
      await api(c ? `/caisses/${c.id}?societe_id=${currentSocieteId}` : `/caisses?societe_id=${currentSocieteId}`,
        { method: c ? "PATCH" : "POST", body });
      closeModal(); toast(c ? "Caisse modifiée." : "Caisse créée — liez-la à son point de vente.", "ok"); refresh();
    } catch (e) { toast(e.message, "ko"); }
  };
}

// ── Fiches de course ─────────────────────────────────────────────────
RENDER.courses = async () => {
  const el = $("#view-courses");
  el.innerHTML = `<div class="muted">Chargement…</div>`;
  const [cs] = await Promise.all([
    api(`/transport/courses?societe_id=${currentSocieteId}${coursesFiltre ? `&statut=${coursesFiltre}` : ""}`).catch(() => []),
    chargerTransportCfg(),
  ]);
  const nbDemandes = coursesFiltre ? 0 : cs.filter((c) => c.statut === "demande").length;
  const seg = `<div class="seg">${[["", "Toutes"], ["demande", "Demandes"], ["brouillon", "Brouillons"], ["validee", "Validées"], ["en_cours", "En course"], ["livree", "À facturer"], ["facturee", "Facturées"]]
    .map(([v, l]) => `<button data-cf="${v}" class="${coursesFiltre === v ? "on" : ""}">${l}${v === "demande" && nbDemandes ? ` (${nbDemandes})` : ""}</button>`).join("")}</div>`;
  el.innerHTML = `<div class="section-hdr" style="margin-bottom:12px">
      <div class="section-title"><i class="ti ti-steering-wheel"></i> Fiches de course</div>
      <div style="margin-left:auto;display:flex;gap:10px;align-items:center">${seg}
        <button class="btn btn-sm" id="cr-rapport"><i class="ti ti-chart-bar"></i> Rentabilité</button>
        <button class="btn btn-sm" id="cr-facturer"><i class="ti ti-file-invoice"></i> Facturer les livrées</button>
        ${has("DFI", "PRESIDENT", "ADMIN_SYS") ? `<button class="btn btn-sm" id="cr-reglages" title="Réglages transport (validateur : ${esc(transportCfg.role_validation)})"><i class="ti ti-settings"></i></button>` : ""}
        <button class="btn btn-sm btn-primary" id="cr-new"><i class="ti ti-plus"></i> Nouvelle course</button></div></div>
    ${!cs.length ? `<div class="empty"><i class="ti ti-steering-wheel"></i>Aucune fiche de course${coursesFiltre ? " dans ce filtre" : ""}.</div>`
      : `<div class="card"><div class="card-body"><table><thead><tr><th>N°</th><th>Date</th><th>Client</th><th>Camion</th>
          <th>Trajet</th><th class="right">Tonnage</th><th class="right">Recette $</th><th class="right">Marge $</th><th>Statut</th><th></th></tr></thead><tbody>
        ${cs.map((c) => { const [sl, sc] = COURSE_ST[c.statut] || [c.statut, ""]; return `
          <tr style="cursor:pointer" data-cd="${c.id}">
            <td class="num-cell">${esc(c.numero)}</td><td>${c.date}</td>
            <td>${esc(c.client || "")}${c.intra_groupe ? ' <span class="tag">groupe</span>' : ""}</td>
            <td>${esc(c.camion || "—")}${c.camion_type === "sous_traite" ? ' <span class="tag">ST</span>' : ""}${c.commande_origine ? ` <span class="tag" title="Issue de la commande ${esc(c.commande_origine)}">PO</span>` : ""}</td>
            <td class="muted" style="font-size:12px">${esc(c.origine)} → ${esc(c.destination)}<br/>${esc(c.marchandise)}</td>
            <td class="right">${fmtNum(c.tonnage_livre != null ? c.tonnage_livre : c.tonnage_prevu)} <span class="muted" style="font-size:11px">${esc(c.unite || "t")}</span></td>
            <td class="right" style="font-weight:600">${fmtNum(c.recette_usd)}</td>
            <td class="right ${c.marge_usd < 0 ? "danger" : ""}">${c.marge_usd != null ? fmtNum(c.marge_usd) : "—"}</td>
            <td><span class="pill ${sc}">${sl}</span></td>
            <td class="right"><i class="ti ti-chevron-right muted"></i></td></tr>`; }).join("")}
        </tbody></table></div></div>`}`;
  el.querySelectorAll("[data-cf]").forEach((b) => b.onclick = () => { coursesFiltre = b.dataset.cf; RENDER.courses(); });
  $("#cr-new").onclick = () => courseModal();
  $("#cr-facturer").onclick = () => facturerCoursesModal();
  $("#cr-rapport").onclick = () => rapportTransportModal();
  if ($("#cr-reglages")) $("#cr-reglages").onclick = () => reglagesTransportModal();
  filtreTable(el);
  el.querySelectorAll("[data-cd]").forEach((r) => r.onclick = () => courseDetail(r.dataset.cd, cs.find((c) => c.id === r.dataset.cd)));
};

async function courseModal() {
  const [clients, camions, chauffeurs, contrats, reqs] = await Promise.all([
    api(`/commercial/tiers?societe_id=${currentSocieteId}&type=client`).catch(() => []),
    api(`/transport/camions?societe_id=${currentSocieteId}`).catch(() => []),
    api(`/transport/chauffeurs?societe_id=${currentSocieteId}`).catch(() => []),
    api(`/transport/contrats?societe_id=${currentSocieteId}`).catch(() => []),
    api(`/requisitions?societe_id=${currentSocieteId}`).catch(() => []),
  ]);
  const dispo = camions.filter((c) => c.actif && c.statut === "disponible");
  const actifs = contrats.filter((c) => c.statut === "actif");
  modal({
    title: "Nouvelle fiche de course",
    wide: true,
    body: `<div class="form-row">
        <div class="form-group"><label class="form-label">Client (demandeur)</label><select id="co-cli" class="form-select">${clients.filter((c) => c.code !== "COMPTANT").map((c) => `<option value="${c.id}">${esc(Catalogue.label(c))}</option>`).join("")}</select></div>
        <div class="form-group"><label class="form-label">Contrat (optionnel)</label><select id="co-ctr" class="form-select"><option value="">— hors contrat —</option>${actifs.map((c) => `<option value="${c.id}">${esc(c.libelle)}</option>`).join("")}</select></div>
        <div class="form-group" id="co-tarif-wrap" style="display:none"><label class="form-label">Tarif du contrat</label><select id="co-tarif" class="form-select"></select></div></div>
      <div class="form-row">
        <div class="form-group"><label class="form-label">Camion (disponibles uniquement)</label><select id="co-cam" class="form-select">${dispo.map((c) => `<option value="${c.id}">${esc(c.immatriculation)}${c.type === "sous_traite" ? " (sous-traité)" : ""} · ${fmtNum(c.capacite_tonnes)} t</option>`).join("") || '<option value="">(aucun camion disponible)</option>'}</select></div>
        <div class="form-group"><label class="form-label">Chauffeur</label><select id="co-chf" class="form-select"><option value="">—</option>${chauffeurs.map((c) => `<option value="${c.id}">${esc(Catalogue.label(c))}</option>`).join("")}</select></div>
        <div class="form-group"><label class="form-label">Date de départ</label><input id="co-date" class="form-input" type="date" value="${isoLocal(new Date())}" /></div></div>
      <div class="form-row">
        <div class="form-group"><label class="form-label">Origine</label><input id="co-orig" class="form-input" placeholder="Likasi" /></div>
        <div class="form-group"><label class="form-label">Destination</label><input id="co-dest" class="form-input" placeholder="Kolwezi" /></div>
        <div class="form-group"><label class="form-label">Marchandise</label><input id="co-march" class="form-input" placeholder="Ciment 42.5" /></div></div>
      <div class="form-row">
        <div class="form-group"><label class="form-label">Tonnage prévu</label><input id="co-ton" class="form-input right" type="number" step="any" value="30" /></div>
        <div class="form-group"><label class="form-label">Tarification</label><select id="co-mode" class="form-select"><option value="tonne">Prix à la tonne</option><option value="voyage">Forfait au voyage</option></select></div>
        <div class="form-group"><label class="form-label">Prix USD</label><input id="co-prix" class="form-input right" type="number" step="any" value="0" /></div></div>
      <div class="form-group"><label class="form-label">Réquisition carburant / frais de route liée (PROC-KL-02)</label>
        <select id="co-req" class="form-select"><option value="">— aucune (à lier plus tard) —</option>
          ${reqs.slice(0, 30).map((r) => `<option value="${r.id}">${esc(r.numero)} — ${esc(r.objet || "")} (${esc(r.statut)})</option>`).join("")}</select>
        <div class="muted" style="font-size:11.5px;margin-top:4px">Le départ sera bloqué tant que l'avance de cette réquisition n'est pas décaissée.</div></div>`,
    footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="co-ok"><i class="ti ti-check"></i> Créer la fiche</button>`,
  });
  $("#co-ctr").onchange = (e) => {
    const c = actifs.find((x) => x.id === e.target.value);
    $("#co-tarif-wrap").style.display = c && c.tarifs.length ? "" : "none";
    if (c) {
      $("#co-cli").value = c.client_tiers_id;
      $("#co-tarif").innerHTML = c.tarifs.map((t, i) => `<option value="${i}">${esc(t.trajet)} — ${fmtNum(t.prix)} $${t.mode === "tonne" ? "/t" : "/voyage"}</option>`).join("");
      const applique = () => {
        const t = c.tarifs[+$("#co-tarif").value || 0];
        if (!t) return;
        $("#co-mode").value = t.mode; $("#co-prix").value = t.prix;
        const [o, d] = t.trajet.split("→").map((s) => s.trim());
        if (o) $("#co-orig").value = o;
        if (d) $("#co-dest").value = d;
      };
      $("#co-tarif").onchange = applique; applique();
    }
  };
  $("#co-ok").onclick = async () => {
    try {
      await api(`/transport/courses?societe_id=${currentSocieteId}`, { method: "POST", body: {
        client_tiers_id: $("#co-cli").value, contrat_id: $("#co-ctr").value || null,
        camion_id: $("#co-cam").value, chauffeur_id: $("#co-chf").value || null,
        date_course: $("#co-date").value || null,
        origine: $("#co-orig").value, destination: $("#co-dest").value, marchandise: $("#co-march").value,
        tonnage_prevu: +$("#co-ton").value || 0, tarif_mode: $("#co-mode").value,
        prix_unitaire: +$("#co-prix").value || 0, requisition_id: $("#co-req").value || null } });
      closeModal(); toast("Fiche de course créée — à faire valider par le DFI.", "ok"); RENDER.courses();
    } catch (e) { toast(e.message, "ko"); }
  };
}

async function courseDetail(id, c) {
  if (!c) { try { c = (await api(`/transport/courses?societe_id=${currentSocieteId}`)).find((x) => x.id === id); } catch { return; } }
  const [sl, sc] = COURSE_ST[c.statut] || [c.statut, ""];
  const actions = [];
  if (c.statut === "demande") actions.push(`<button class="btn btn-sm btn-primary" id="ca-pec" ${c.deblocable ? "" : "disabled"} title="${c.deblocable ? "" : "En attente de confirmation du vendeur"}"><i class="ti ti-hand-grab"></i> Prendre en charge</button>`);
  if (!["demande", "facturee", "annulee"].includes(c.statut)) actions.push(`<button class="btn btn-sm" id="ca-req"><i class="ti ti-gas-station"></i> Lier une réquisition</button>`);
  if (c.statut === "brouillon" && has(transportCfg.role_validation || "DFI")) actions.push(`<button class="btn btn-sm btn-primary" id="ca-val"><i class="ti ti-check"></i> Valider (${esc(transportCfg.role_validation || "DFI")})</button>`);
  if (c.statut === "validee") actions.push(`<button class="btn btn-sm btn-primary" id="ca-dep"><i class="ti ti-player-play"></i> Départ camion</button>`);
  if (c.statut === "en_cours") actions.push(`<button class="btn btn-sm btn-primary" id="ca-arr"><i class="ti ti-map-pin-check"></i> Arrivé à destination</button>`);
  if (["en_cours", "arrivee", "receptionnee"].includes(c.statut)) actions.push(`<button class="btn btn-sm ${["arrivee", "receptionnee"].includes(c.statut) ? "btn-primary" : ""}" id="ca-ret"><i class="ti ti-flag-check"></i> Retour & clôture</button>`);
  if (c.reception_po && (c.reception_po.a_confirmer || []).length) actions.push(`<button class="btn btn-sm btn-primary" id="ca-conf"><i class="ti ti-checklist"></i> Confirmer la réception</button>`);
  if (["brouillon", "validee"].includes(c.statut)) actions.push(`<button class="btn btn-sm" id="ca-ann"><i class="ti ti-x"></i> Annuler</button>`);
  if (["en_cours", "arrivee"].includes(c.statut) && !(c.reception_po && c.reception_po.recu > 0)) actions.push(`<button class="btn btn-sm" id="ca-ann2" title="Interrompre la course (panne, incident…) — motif obligatoire"><i class="ti ti-alert-octagon"></i> Interrompre la course</button>`);
  actions.push(`<button class="btn btn-sm" id="ca-print"><i class="ti ti-printer"></i> Imprimer la fiche</button>`);
  modal({
    title: `Fiche de course ${c.numero}`,
    body: `<div style="margin-bottom:8px"><span class="pill ${sc}">${sl}</span>
        <b style="margin-left:8px">${esc(c.client || "")}</b>${c.intra_groupe ? ' <span class="tag">groupe</span>' : ""}
        ${c.contrat ? `<span class="tag">${esc(c.contrat)}</span>` : ""}</div>
      ${c.statut === "demande" ? `<div class="banner"><i class="ti ti-hourglass"></i>
        Demande issue de la commande <b>${esc(c.commande_origine || "")}</b> —
        ${c.deblocable ? "le vendeur a confirmé : vous pouvez la prendre en charge (camion, chauffeur, tarif)."
          : `en attente de confirmation du vendeur (commande client : ${esc(c.vendeur_statut || "envoyée")}).`}</div>` : ""}
      ${c.etapes_po ? bandeauEtapesPO(c.etapes_po) : ""}
      <table><tbody>
        <tr><td class="muted">Camion / chauffeur</td><td><b>${esc(c.camion || "à affecter")}</b>${c.camion_type === "sous_traite" ? " (sous-traité)" : ""} · ${esc(c.chauffeur || "—")}</td></tr>
        <tr><td class="muted">Trajet</td><td>${esc(c.origine)} → ${esc(c.destination)} · ${esc(c.marchandise)}</td></tr>
        <tr><td class="muted">Quantité</td><td>${fmtNum(c.tonnage_prevu)} ${esc(c.unite)} prévus${c.tonnage_livre != null ? ` · <b>${fmtNum(c.tonnage_livre)} ${esc(c.unite)} livrés</b>` : ""}${c.reception_po && c.reception_po.livre ? ` · chargé vendeur : ${fmtNum(c.reception_po.livre)}` : ""}</td></tr>
        <tr><td class="muted">Tarif</td><td>${fmtNum(c.prix_unitaire)} $${c.tarif_mode === "tonne" ? `/${esc(c.unite === "tonnes" ? "tonne" : c.unite)}` : " forfait"} → recette <b>${fmtNum(c.recette_usd)} $</b></td></tr>
        ${c.commande_origine && c.statut !== "demande" ? `<tr><td class="muted">Commande d'origine</td><td>${esc(c.commande_origine)}</td></tr>` : ""}
        ${c.reception_po && c.reception_po.livre > 0 ? `<tr><td class="muted">Réception acheteur</td><td>
          ${fmtNum(c.reception_po.recu)} reçu / ${fmtNum(c.reception_po.livre)} chargé
          ${c.reception_po.manquant > 0 ? ` · <span style="color:var(--r)"><b>${fmtNum(c.reception_po.manquant)} manquants</b> (${fmtNum(c.reception_po.valeur_manquants_usd)} $ à votre charge)</span>` : ""}
          ${c.reception_po.complete ? ' <i class="ti ti-check" style="color:var(--g)"></i>' : ' <span class="muted">(en attente)</span>'}</td></tr>` : ""}
        ${(c.requisitions || []).length ? `<tr><td class="muted">Réquisitions liées</td><td>
          ${c.requisitions.map((r) => `<span class="tag" title="${esc(r.statut)}">${esc(r.numero)}</span>`).join(" ")}
          <div class="muted" style="font-size:11.5px;margin-top:2px">Frais de route justifiés : ${fmtNum(c.frais_route_usd)} $</div></td></tr>` : ""}
        ${c.st_cout_usd ? `<tr><td class="muted">Sous-traitance</td><td>${fmtNum(c.st_cout_usd)} $ (${c.st_mode === "forfait" ? "forfait" : fmtNum(c.st_valeur) + " %"}) — facture ${esc(c.st_facture || "")}</td></tr>` : ""}
        ${c.marge_usd != null ? `<tr><td class="muted">Marge</td><td><b style="color:${c.marge_usd >= 0 ? "var(--g)" : "var(--r)"}">${fmtNum(c.marge_usd)} $</b></td></tr>` : ""}
        ${c.heure_depart ? `<tr><td class="muted">Départ / retour</td><td>${c.heure_depart.slice(11, 16)}${c.heure_retour ? " → " + c.heure_retour.slice(11, 16) : " (en cours)"}</td></tr>` : ""}
        ${c.incidents ? `<tr><td class="muted">Incidents</td><td>${esc(c.incidents)}</td></tr>` : ""}
        ${c.facture ? `<tr><td class="muted">Facturée</td><td>${esc(c.facture)}</td></tr>` : ""}
      </tbody></table>`,
    footer: `<button class="btn" onclick="closeModal()">Fermer</button>${actions.join("")}`,
  });
  const done = (msg) => { closeModal(); if (msg) toast(msg, "ok"); RENDER.courses(); };
  if ($("#ca-pec")) $("#ca-pec").onclick = () => priseEnChargeModal(c);
  if ($("#ca-req")) $("#ca-req").onclick = () => lierRequisitionModal(c);
  if ($("#ca-val")) $("#ca-val").onclick = async () => { try { await api(`/transport/courses/${c.id}/valider`, { method: "POST" }); done("Fiche validée."); } catch (e) { toast(e.message, "ko"); } };
  if ($("#ca-dep")) $("#ca-dep").onclick = () => {
    modal({ title: `Départ du camion — ${c.numero}`,
      body: `<div class="form-group"><label class="form-label">Compteur km au départ (facultatif)</label>
        <input id="dp-km" class="form-input right" type="number" step="any" placeholder="ex. 120450" /></div>
        <div class="banner"><i class="ti ti-info-circle"></i> Le relevé km alimente le suivi kilométrique du camion et les plans d'entretien « au km » du module Maintenance.</div>`,
      footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="dp-ok"><i class="ti ti-player-play"></i> Confirmer le départ</button>` });
    $("#dp-ok").onclick = async () => {
      try { await api(`/transport/courses/${c.id}/depart`, { method: "POST", body: { km_depart: $("#dp-km").value === "" ? null : +$("#dp-km").value } });
        closeModal(); done("Camion parti — bonne route."); } catch (e) { toast(e.message, "ko"); }
    };
  };
  if ($("#ca-arr")) $("#ca-arr").onclick = async () => { try { await api(`/transport/courses/${c.id}/arrivee`, { method: "POST" }); done("Camion arrivé — déchargement en cours (visible par l'acheteur et le vendeur)."); } catch (e) { toast(e.message, "ko"); } };
  if ($("#ca-conf")) $("#ca-conf").onclick = () => {
    const rp = c.reception_po;
    modal({
      title: "Confirmer la réception de l'acheteur",
      body: `<div class="banner"><i class="ti ti-checklist"></i> L'acheteur a constaté :
          <b>${fmtNum(rp.recu)}</b> reçus sur <b>${fmtNum(rp.livre)}</b> chargés
          ${rp.manquant > 0 ? ` · <b style="color:var(--r)">${fmtNum(rp.manquant)} manquants (${fmtNum(rp.valeur_manquants_usd)} $ à votre charge, au prix d'achat)</b>` : " · aucun manquant"}.
          En confirmant, vous validez ce constat — votre facturation sera alors débloquée.</div>
        ${rp.a_confirmer.map((x) => `<div class="pos-parked-item"><div><b>${esc(x.numero)}</b> · ${x.date}${x.note ? `<div class="muted" style="font-size:12px">${esc(x.note)}</div>` : ""}</div>
          <button class="btn btn-sm btn-primary" data-cfr="${x.id}"><i class="ti ti-check"></i> Confirmer</button></div>`).join("")}`,
      footer: `<button class="btn" onclick="closeModal()">Fermer</button>`,
    });
    document.querySelectorAll("[data-cfr]").forEach((b) => b.onclick = async () => {
      try { await api(`/intersociete/receptions/${b.dataset.cfr}/confirmer`, { method: "POST" });
        closeModal(); closeModal(); toast("Réception confirmée — vous pouvez facturer le transport.", "ok"); RENDER.courses(); }
      catch (e) { toast(e.message, "ko"); }
    });
  };
  if ($("#ca-ann")) $("#ca-ann").onclick = async () => { try { await api(`/transport/courses/${c.id}/annuler`, { method: "POST" }); done("Course annulée."); } catch (e) { toast(e.message, "ko"); } };
  if ($("#ca-ann2")) $("#ca-ann2").onclick = () => {
    modal({
      title: `Interrompre la course ${c.numero}`,
      body: `<div class="banner"><i class="ti ti-alert-octagon"></i> La course est déjà partie.
          Son interruption libère le camion${c.commande_origine ? " et <b>recrée automatiquement une demande de course</b> pour réorganiser le transport de la commande" : ""}.</div>
        <div class="form-group"><label class="form-label">Motif de l'interruption (obligatoire)</label>
          <input id="ann2-motif" class="form-input" placeholder="ex. panne moteur à mi-parcours, retour à vide" /></div>`,
      footer: `<button class="btn" onclick="closeModal()">Retour</button>
        <button class="btn btn-primary" id="ann2-ok"><i class="ti ti-check"></i> Interrompre</button>`,
    });
    $("#ann2-ok").onclick = async () => {
      const motif = ($("#ann2-motif").value || "").trim();
      if (!motif) { toast("Le motif est obligatoire pour une course déjà partie.", "ko"); return; }
      try {
        const r = await api(`/transport/courses/${c.id}/annuler`, { method: "POST", body: { motif } });
        toast(r.nouvelle_demande ? `Course interrompue — nouvelle demande ${r.nouvelle_demande} créée.` : "Course interrompue.", "ok");
        closeModal(); RENDER.courses();
      } catch (e) { toast(e.message, "ko"); }
    };
  };
  if ($("#ca-ret")) $("#ca-ret").onclick = () => retourCourseModal(c);
  if ($("#ca-print")) $("#ca-print").onclick = () => printFicheCourse(c);
}

async function priseEnChargeModal(c) {
  const [camions, chauffeurs, contrats] = await Promise.all([
    api(`/transport/camions?societe_id=${currentSocieteId}`).catch(() => []),
    api(`/transport/chauffeurs?societe_id=${currentSocieteId}`).catch(() => []),
    api(`/transport/contrats?societe_id=${currentSocieteId}`).catch(() => []),
  ]);
  const dispo = camions.filter((x) => x.actif && x.statut === "disponible");
  modal({
    title: `Prendre en charge — ${c.numero}`,
    body: `<div class="banner"><i class="ti ti-info-circle"></i> ${esc(c.marchandise)} · ${esc(c.origine)} → ${esc(c.destination)} —
        <b>${fmtNum(c.tonnage_prevu)} ${esc(c.unite)} prévus par le vendeur</b>${c.reception_po && c.reception_po.livre ? ` (déjà chargé : ${fmtNum(c.reception_po.livre)})` : ""}.
        En cas de livraison partielle, ajustez la quantité de CE voyage.</div>
      <div class="form-row">
        <div class="form-group"><label class="form-label">Camion</label><select id="pe-cam" class="form-select">${dispo.map((x) => `<option value="${x.id}">${esc(x.immatriculation)}${x.type === "sous_traite" ? " (sous-traité)" : ""} · ${fmtNum(x.capacite_tonnes)} t</option>`).join("") || '<option value="">(aucun disponible)</option>'}</select></div>
        <div class="form-group"><label class="form-label">Chauffeur</label><select id="pe-chf" class="form-select"><option value="">—</option>${chauffeurs.map((x) => `<option value="${x.id}">${esc(Catalogue.label(x))}</option>`).join("")}</select></div></div>
      <div class="form-row">
        <div class="form-group"><label class="form-label">Quantité de ce voyage</label><input id="pe-ton" class="form-input right" type="number" step="any" value="${c.tonnage_prevu || 30}" /></div>
        <div class="form-group"><label class="form-label">Unité d'emballage</label><input id="pe-unite" class="form-input" list="pe-unites" value="${esc(c.unite || "tonnes")}" />
          <datalist id="pe-unites"><option value="sacs"><option value="tonnes"><option value="pièces"><option value="fûts"><option value="palettes"><option value="cartons"></datalist></div>
        <div class="form-group"><label class="form-label">Tarification</label><select id="pe-mode" class="form-select"><option value="tonne">Prix à la tonne</option><option value="voyage">Forfait voyage</option></select></div>
        <div class="form-group"><label class="form-label">Prix USD</label><input id="pe-prix" class="form-input right" type="number" step="any" value="${c.prix_unitaire || 0}" /></div></div>
      <div class="form-group"><label class="form-label">Contrat (optionnel)</label><select id="pe-ctr" class="form-select"><option value="">— hors contrat —</option>${contrats.filter((x) => x.statut === "actif").map((x) => `<option value="${x.id}">${esc(x.libelle)}</option>`).join("")}</select></div>`,
    footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="pe-ok"><i class="ti ti-hand-grab"></i> Prendre en charge</button>`,
  });
  $("#pe-ok").onclick = async () => {
    try {
      await api(`/transport/courses/${c.id}/prendre-en-charge`, { method: "POST", body: {
        camion_id: $("#pe-cam").value, chauffeur_id: $("#pe-chf").value || null,
        tonnage_prevu: +$("#pe-ton").value || null, unite: $("#pe-unite").value || null,
        tarif_mode: $("#pe-mode").value,
        prix_unitaire: +$("#pe-prix").value || 0, contrat_id: $("#pe-ctr").value || null } });
      closeModal(); closeModal();
      toast(`${c.numero} prise en charge — à faire valider par le DFI.`, "ok");
      RENDER.courses();
    } catch (e) { toast(e.message, "ko"); }
  };
}

async function lierRequisitionModal(c) {
  const reqs = await api(`/requisitions?societe_id=${currentSocieteId}`).catch(() => []);
  const deja = new Set((c.requisitions || []).map((r) => r.numero));
  const dispo = reqs.filter((r) => !deja.has(r.numero));
  modal({
    title: `Lier une réquisition — ${c.numero}`,
    body: `<div class="banner"><i class="ti ti-gas-station"></i> Carburant initial, péages, mais aussi <b>dépenses en cours de route</b> (crevaison, mécanicien…) — rattachez chaque réquisition à la course pour un coût de revient complet.</div>
      ${(c.requisitions || []).length ? `<div class="muted" style="font-size:12px;margin-bottom:8px">Déjà liées : ${c.requisitions.map((r) => esc(r.numero)).join(", ")}</div>` : ""}
      <div class="form-group"><label class="form-label">Réquisition</label>
        <select id="lr-req" class="form-select">${dispo.map((r) => `<option value="${r.id}">${esc(r.numero)} — ${esc(r.objet || "")} (${esc(r.statut)})</option>`).join("") || '<option value="">(aucune réquisition disponible)</option>'}</select></div>`,
    footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="lr-ok"><i class="ti ti-link"></i> Rattacher</button>`,
  });
  $("#lr-ok").onclick = async () => {
    if (!$("#lr-req").value) { toast("Choisissez une réquisition.", "ko"); return; }
    try {
      await api(`/transport/courses/${c.id}/lier-requisition`, { method: "POST", body: { requisition_id: $("#lr-req").value } });
      closeModal(); closeModal();
      toast("Réquisition rattachée à la course.", "ok");
      RENDER.courses();
    } catch (e) { toast(e.message, "ko"); }
  };
}

function retourCourseModal(c) {
  const st = c.camion_type === "sous_traite";
  modal({
    title: `Retour camion — ${c.numero}`,
    body: `<div class="form-row">
        <div class="form-group"><label class="form-label">Quantité réellement livrée (${esc(c.unite)})</label><input id="rt-ton" class="form-input right" type="number" step="any" value="${c.reception_po && c.reception_po.recu ? c.reception_po.recu : c.tonnage_prevu}" />
        ${c.reception_po && c.reception_po.recu ? `<div class="muted" style="font-size:11.5px;margin-top:4px">Réception de l'acheteur : ${fmtNum(c.reception_po.recu)} reçus${c.reception_po.manquant ? ` · ${fmtNum(c.reception_po.manquant)} manquants` : ""}</div>` : ""}</div>
        <div class="form-group"><label class="form-label">Compteur km au retour${c.km_depart != null ? ` (départ : ${fmtNum(c.km_depart)})` : ""}</label><input id="rt-km" class="form-input right" type="number" step="any" placeholder="facultatif" /></div></div>
      <div class="form-group"><label class="form-label">Incidents (panne, retard, écart de livraison…)</label><input id="rt-inc" class="form-input" /></div>
      ${st ? `<div class="card" style="margin-top:8px"><div class="card-body">
        <div class="muted" style="font-size:12px;margin-bottom:8px"><i class="ti ti-user-dollar"></i> Camion sous-traité — la dette envers le propriétaire sera générée à la clôture.</div>
        <div class="form-row">
          <div class="form-group"><label class="form-label">Rémunération</label><select id="rt-mode" class="form-select">
            <option value="forfait">Forfait ($)</option><option value="pourcentage">% du prix client</option></select></div>
          <div class="form-group"><label class="form-label">Valeur</label><input id="rt-val" class="form-input right" type="number" step="any" /></div></div></div></div>` : ""}
      <div class="banner"><i class="ti ti-clock"></i> PROC-KL-03 : solde de l'avance à remettre en caisse sous 2 h — PROC-KL-04 : facturation sous 48 h.</div>`,
    footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="rt-ok"><i class="ti ti-flag-check"></i> Clôturer la course</button>`,
  });
  $("#rt-ok").onclick = async () => {
    try {
      const body = { tonnage_livre: +$("#rt-ton").value || 0, incidents: $("#rt-inc").value || null,
        km_retour: $("#rt-km").value === "" ? null : +$("#rt-km").value };
      if (st) { body.st_mode = $("#rt-mode").value; body.st_valeur = +$("#rt-val").value || null; }
      const r = await api(`/transport/courses/${c.id}/retour`, { method: "POST", body });
      closeModal(); closeModal();
      toast(`Course ${c.numero} livrée${r.st_cout_usd ? ` — dette sous-traitant ${fmtNum(r.st_cout_usd)} $ générée` : ""}.`, "ok");
      RENDER.courses();
    } catch (e) { toast(e.message, "ko"); }
  };
}

async function facturerCoursesModal() {
  const livrees = (await api(`/transport/courses?societe_id=${currentSocieteId}&statut=livree`).catch(() => []));
  if (!livrees.length) { toast("Aucune course livrée à facturer.", ""); return; }
  modal({
    title: "Facturer des courses livrées",
    body: `<div class="banner"><i class="ti ti-info-circle"></i> Sélectionnez des courses d'un <b>même client</b>. Client du groupe → la facture d'achat miroir est créée automatiquement chez lui.</div>
      <table><thead><tr><th></th><th>N°</th><th>Client</th><th>Trajet</th><th class="right">Recette $</th></tr></thead><tbody>
      ${livrees.map((c) => `<tr><td><input type="checkbox" class="fc-sel" data-id="${c.id}" data-cli="${c.client_tiers_id}" style="width:auto" /></td>
        <td class="num-cell">${esc(c.numero)}</td><td>${esc(c.client)}${c.intra_groupe ? ' <span class="tag">groupe</span>' : ""}</td>
        <td class="muted" style="font-size:12px">${esc(c.origine)} → ${esc(c.destination)}</td>
        <td class="right">${fmtNum(c.recette_usd)}</td></tr>`).join("")}</tbody></table>
      <div class="form-group" style="margin-top:10px"><label class="form-label">Échéance (optionnel)</label><input id="fc2-ech" class="form-input" type="date" /></div>`,
    footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="fc2-ok"><i class="ti ti-file-invoice"></i> Générer la facture</button>`,
  });
  $("#fc2-ok").onclick = async () => {
    const sel = [...document.querySelectorAll(".fc-sel:checked")];
    if (!sel.length) { toast("Cochez au moins une course.", "ko"); return; }
    try {
      const r = await api(`/transport/facturer?societe_id=${currentSocieteId}`, { method: "POST", body: {
        course_ids: sel.map((x) => x.dataset.id), echeance: $("#fc2-ech").value || null } });
      closeModal();
      toast(`Facture ${r.facture.numero} générée (${fmtNum(r.facture.total_ttc)} $)${r.facture.intra_groupe ? " + miroir intersociété" : ""}.`, "ok");
      RENDER.courses();
    } catch (e) { toast(e.message, "ko"); }
  };
}

async function rapportTransportModal() {
  let r; try { r = await api(`/transport/rapport?societe_id=${currentSocieteId}`); } catch (e) { toast(e.message, "ko"); return; }
  const t = r.total;
  modal({
    title: "Rentabilité transport",
    wide: true,
    body: `<div class="pos-kpis">
        <div><span>${t.courses}</span>courses</div>
        <div><span>${fmtNum(t.tonnage)} t</span>transportées</div>
        <div><span>${fmtNum(t.recettes)} $</span>recettes</div>
        <div><span>${fmtNum(t.frais)} $</span>frais de route</div>
        <div><span>${fmtNum(t.sous_traitance)} $</span>sous-traitance</div>
        <div><span>${fmtNum(t.maintenance)} $</span>maintenance</div>
        <div><span style="color:${t.marge >= 0 ? "var(--g)" : "var(--r)"}">${fmtNum(t.marge)} $</span>marge</div></div>
      ${r.par_camion.length ? `<div class="muted" style="font-size:12px;margin-top:14px">Par camion</div>
      <table><thead><tr><th>Camion</th><th class="right">Courses</th><th class="right">Tonnage</th><th class="right">Recettes</th>
        <th class="right">Frais</th><th class="right">Sous-trait.</th><th class="right">Maint.</th><th class="right">Marge $</th></tr></thead><tbody>
      ${r.par_camion.map((c) => `<tr><td><b>${esc(c.camion)}</b>${c.type === "sous_traite" ? ' <span class="tag">ST</span>' : ""}</td>
        <td class="right">${c.courses}</td><td class="right">${fmtNum(c.tonnage)}</td><td class="right">${fmtNum(c.recettes)}</td>
        <td class="right">${fmtNum(c.frais)}</td><td class="right">${fmtNum(c.sous_traitance)}</td><td class="right">${fmtNum(c.maintenance)}</td>
        <td class="right" style="font-weight:700;color:${c.marge >= 0 ? "var(--g)" : "var(--r)"}">${fmtNum(c.marge)}</td></tr>`).join("")}</tbody></table>` : ""}
      ${r.par_contrat.length ? `<div class="muted" style="font-size:12px;margin-top:14px">Par contrat</div>
      <table><tbody>${r.par_contrat.map((c) => `<tr><td>${esc(c.contrat)}</td><td class="right">${c.courses} courses</td>
        <td class="right">${fmtNum(c.recettes)} $</td><td class="right" style="font-weight:700">${fmtNum(c.marge)} $ de marge</td></tr>`).join("")}</tbody></table>` : ""}`,
    footer: `<button class="btn" onclick="closeModal()">Fermer</button>`,
  });
}

function printFicheCourse(c) {
  // Document opérationnel en deux volets — AUCUN prix ni marge (demande de Laurent) :
  // 1. Fiche de course (suivi logistique)  2. Ordre de mission du chauffeur
  const soc = (societes.find((s) => s.id === currentSocieteId) || { nom: "" });
  const row = (k, v) => `<tr><td class="k">${k}</td><td>${v}</td></tr>`;
  const w = Editions.fenetre(`Fiche de course · ${c.numero}`);
  w.document.write(`<html><head><meta charset="utf-8"><title>${esc(c.numero)}</title><style>
    @page{size:A4;margin:16mm}
    body{font-family:'Segoe UI',Arial,sans-serif;color:#1a1a2e;font-size:13px;margin:0;padding:34px}
    .hd{display:flex;justify-content:space-between;align-items:flex-start;border-bottom:3px solid #16324f;padding-bottom:12px;margin-bottom:16px}
    .hd .soc{font-size:19px;font-weight:800;color:#16324f}.hd .grp{font-size:11px;color:#777;letter-spacing:.06em}
    .doc{text-align:right}.doc .t{font-size:21px;font-weight:800;color:#16324f}.doc .n{font-size:13px;color:#555;margin-top:2px}
    table{width:100%;border-collapse:collapse;margin:8px 0}
    td{padding:7px 10px;border-bottom:1px solid #e3e6ec;font-size:12.5px}
    td.k{width:190px;font-size:10.5px;text-transform:uppercase;letter-spacing:.07em;color:#888;font-weight:700}
    .sigs{display:flex;justify-content:space-between;margin-top:38px;gap:26px}
    .sig{flex:1;text-align:center;font-size:11.5px;color:#555}.sig .l{border-top:1px solid #999;margin-top:50px;padding-top:6px}
    .ment{margin-top:16px;font-size:11.5px;color:#555;background:#f4f6fa;border-radius:8px;padding:10px 13px}
    .om{page-break-before:always;padding-top:10px}
    .consignes li{font-size:12px;color:#444;margin-bottom:5px}
    .ft{margin-top:30px;text-align:center;font-size:10.5px;color:#999}
  </style></head><body>

    <div class="hd"><div><div class="soc">${esc(soc.nom)}</div><div class="grp">GROUPE KILIMA HOLDINGS — R.D. CONGO</div></div>
      <div class="doc"><div class="t">FICHE DE COURSE</div><div class="n">${esc(c.numero)}</div></div></div>
    <table>
      ${row("Date", c.date)}
      ${row("Client / demandeur", esc(c.client || ""))}
      ${c.commande_origine ? row("Commande d'origine", esc(c.commande_origine)) : ""}
      ${c.reference_producteur ? row("Réf. producteur", esc(c.reference_producteur)) : ""}
      ${c.contrat ? row("Contrat", esc(c.contrat)) : ""}
      ${row("Camion", esc(c.camion || "à affecter") + (c.camion_type === "sous_traite" ? " (sous-traité)" : ""))}
      ${row("Chauffeur", esc(c.chauffeur || "—"))}
      ${row("Trajet", esc(c.origine) + " → " + esc(c.destination))}
      ${row("Marchandise", esc(c.marchandise))}
      ${row("Tonnage prévu", fmtNum(c.tonnage_prevu) + " t")}
      ${c.tonnage_livre != null ? row("Tonnage livré", fmtNum(c.tonnage_livre) + " t") : ""}
      ${(c.requisitions || []).length ? row("Réquisitions liées", c.requisitions.map((r) => esc(r.numero)).join(", ")) : ""}
      ${c.heure_depart ? row("Heure de départ", c.heure_depart.slice(0, 16).replace("T", " ")) : row("Heure de départ", "________________")}
      ${c.heure_retour ? row("Heure de retour", c.heure_retour.slice(0, 16).replace("T", " ")) : row("Heure de retour", "________________")}
      ${row("Incidents", c.incidents ? esc(c.incidents) : "—")}
    </table>
    <div class="ment">Aucun camion ne part sans fiche validée et sans avance carburant effectivement mise
      (contrôle physique du réservoir) — PROC-KL-01/02. Solde de route à remettre en caisse sous 2 h après le retour.</div>
    <div class="sigs">
      <div class="sig"><b>Assistant technique</b><div class="l">Nom, date & signature</div></div>
      <div class="sig"><b>Validateur (${esc(transportCfg.role_validation || "DFI")})</b><div class="l">Nom, date & signature</div></div>
      <div class="sig"><b>Dispatcher (retour)</b><div class="l">Nom, date & signature</div></div>
    </div>

    <div class="om">
      <div class="hd"><div><div class="soc">${esc(soc.nom)}</div><div class="grp">GROUPE KILIMA HOLDINGS — R.D. CONGO</div></div>
        <div class="doc"><div class="t">ORDRE DE MISSION</div><div class="n">Réf. ${esc(c.numero)}</div></div></div>
      <table>
        ${row("Chauffeur", esc(c.chauffeur || "________________"))}
        ${row("Camion", esc(c.camion || "________________"))}
        ${row("Date de départ", c.date)}
        ${row("Itinéraire", esc(c.origine) + " → " + esc(c.destination))}
        ${row("Marchandise transportée", esc(c.marchandise) + " — " + fmtNum(c.tonnage_prevu) + " t")}
        ${row("Destinataire", esc(c.client || ""))}
      </table>
      <div class="ment"><b>Consignes du chauffeur</b><ul class="consignes">
        <li>Vérifier le chargement et le carburant avant le départ ; signer la check-list de départ.</li>
        <li>Faire signer le bon de livraison par le destinataire à l'arrivée.</li>
        <li>Conserver TOUS les reçus (péages, dépenses de route) — aucun remboursement sans justificatif.</li>
        <li>Signaler immédiatement tout incident (panne, accident, retard) à l'assistant technique.</li>
        <li>Au retour : remettre bon de livraison signé, reçus et solde non dépensé dans les 2 heures.</li></ul></div>
      <div class="sigs">
        <div class="sig"><b>Le chauffeur</b><div class="l">Nom, date & signature</div></div>
        <div class="sig"><b>Pour la direction</b><div class="l">Nom, date & signature</div></div>
      </div>
    </div>
    <div class="ft">Document généré par l'ERP KILIMA HOLDINGS — ${new Date().toLocaleDateString("fr-FR")}</div>
  </body></html>`);
  w.document.close(); w.focus(); setTimeout(() => w.print(), 300);
}

// ═══ Opérations intersociétés ════════════════════════════════════════
let interTab = "positions";
RENDER.intersociete = async () => {
  const el = $("#view-intersociete");
  el.innerHTML = `<div class="muted">Chargement…</div>`;
  const seg = `<div class="seg">
    <button data-it="positions" class="${interTab === "positions" ? "on" : ""}">Positions</button>
    <button data-it="factures" class="${interTab === "factures" ? "on" : ""}">Factures intra-groupe</button>
    <button data-it="tracer" class="${interTab === "tracer" ? "on" : ""}">Traçabilité</button>
    <button data-it="liaisons" class="${interTab === "liaisons" ? "on" : ""}">Liaisons tiers ↔ sociétés</button></div>`;
  let body = "";
  if (interTab === "tracer") {
    body = `<div class="banner"><i class="ti ti-search"></i> Retracez tout le dossier d'une commande — quel que soit votre côté
        (acheteur, vendeur, transporteur) — par <b>n° producteur</b> ou n° de commande.</div>
      <div style="display:flex;gap:8px;margin-bottom:14px">
        <input id="tr-q" class="form-input" placeholder="ex. GCK-2026-08841 ou CMD-KAK-2026-000001" style="max-width:380px" />
        <button class="btn btn-primary" id="tr-go"><i class="ti ti-search"></i> Tracer</button></div>
      <div id="tr-res"></div>`;
  } else if (interTab === "positions") {
    const pos = await api(`/intersociete/positions`).catch(() => []);
    body = !pos.length ? '<div class="empty"><i class="ti ti-affiliate"></i>Aucune position intersociété en cours — tout est soldé.</div>'
      : `<div class="card"><div class="card-body"><table><thead><tr><th>Créancier (vend)</th><th>Débiteur (doit)</th>
          <th class="right">Montant $</th><th class="right">Vu du débiteur $</th><th class="right">Écart réconciliation</th></tr></thead><tbody>
        ${pos.map((p) => `<tr><td><b>${esc(p.creancier)}</b></td><td>${esc(p.debiteur)}</td>
          <td class="right" style="font-weight:700">${fmtNum(p.montant_usd)}</td>
          <td class="right">${fmtNum(p.miroir_usd)}</td>
          <td class="right ${Math.abs(p.ecart_usd) > 0.01 ? "danger" : ""}" style="font-weight:600">${Math.abs(p.ecart_usd) > 0.01 ? fmtNum(p.ecart_usd) : '<i class="ti ti-check" style="color:var(--g)"></i>'}</td></tr>`).join("")}
        </tbody></table></div></div>`;
  } else if (interTab === "factures") {
    const facs = await api(`/intersociete/factures`).catch(() => []);
    body = !facs.length ? '<div class="empty"><i class="ti ti-file-invoice"></i>Aucune facture intra-groupe. Liez d\'abord vos tiers aux sociétés (onglet Liaisons) puis facturez normalement — le miroir se créera tout seul.</div>'
      : `<div class="card"><div class="card-body"><table><thead><tr><th>N°</th><th>Date</th><th>Vendeur</th><th>Acheteur</th>
          <th>Miroir</th><th class="right">TTC $</th><th>Règlement</th><th></th></tr></thead><tbody>
        ${facs.map((f) => { const [rl, rc] = REGL_ST[f.statut_reglement] || ["", ""]; return `<tr>
          <td class="num-cell">${esc(f.numero)}</td><td>${f.date}</td>
          <td><b>${esc(f.vendeur)}</b></td><td>${esc(f.acheteur)}</td>
          <td class="muted" style="font-size:12px">${esc(f.miroir_numero || "—")}${f.miroir_statut === "en_attente" ? ' <span class="tag">à valider</span>' : ""}</td>
          <td class="right" style="font-weight:700">${fmtNum(f.total_ttc)}</td>
          <td><span class="pill ${rc}">${rl}</span>${f.statut_reglement !== "payee" ? `<div class="muted" style="font-size:11px">reste ${fmtNum(f.solde_du_usd)} $</div>` : ""}</td>
          <td class="right">${f.solde_du_usd > 0 ? `<button class="btn btn-sm btn-primary" data-ireg="${f.id}"><i class="ti ti-arrows-exchange"></i> Régler</button>` : ""}</td></tr>`; }).join("")}
        </tbody></table></div></div>`;
  } else {
    const d = await api(`/intersociete/liaisons?societe_id=${currentSocieteId}`).catch(() => ({ societes: [], tiers: [] }));
    const tousTiers = (await api(`/commercial/tiers?societe_id=${currentSocieteId}`).catch(() => []));
    if (!tousTiers.filter((t) => t.code !== "COMPTANT").length) {
      body = `<div class="empty"><i class="ti ti-affiliate"></i>
        Aucun tiers chez ${esc((societes.find((s) => s.id === currentSocieteId) || {}).nom || "cette société")}.<br/>
        <span class="muted" style="font-size:12.5px">Les liaisons se font société par société (sélecteur en haut à droite).
        Créez d'abord vos tiers dans Paramètres › Administration › Tiers — vous pourrez les lier directement là-bas.</span></div>`;
    } else
    body = `<div class="banner"><i class="ti ti-info-circle"></i> Liez chaque tiers « groupe » à la société qu'il représente : c'est ce lien qui déclenche les factures miroir et la réconciliation. (Aussi disponible dans Administration › Tiers.)</div>
      <div class="card"><div class="card-body">
      <table><thead><tr><th>Tiers (${esc((societes.find((s) => s.id === currentSocieteId) || {}).nom || "")})</th><th>Type</th><th>Société liée</th></tr></thead><tbody>
      ${tousTiers.filter((t) => t.code !== "COMPTANT").map((t) => {
        const lie = d.tiers.find((x) => x.id === t.id);
        return `<tr><td><b>${esc(Catalogue.label(t))}</b> <span class="muted">${esc(t.code)}</span></td><td>${esc(t.type)}</td>
          <td><select class="form-select il-sel" data-t="${t.id}" style="width:auto">
            <option value="">— non lié (tiers externe) —</option>
            ${d.societes.filter((s) => s.id !== currentSocieteId).map((s) => `<option value="${s.id}" ${lie && lie.societe_liee && lie.societe_liee.id === s.id ? "selected" : ""}>${esc(s.nom)}</option>`).join("")}
          </select></td></tr>`; }).join("")}
      </tbody></table></div></div>`;
  }
  el.innerHTML = `<div class="section-hdr" style="margin-bottom:12px">
      <div class="section-title"><i class="ti ti-affiliate"></i> Opérations intersociétés</div>
      <div style="margin-left:auto">${seg}</div></div>${body}`;
  el.querySelectorAll("[data-it]").forEach((b) => b.onclick = () => { interTab = b.dataset.it; RENDER.intersociete(); });
  if ($("#tr-go")) {
    const tracer = async () => {
      const q = $("#tr-q").value.trim();
      if (!q) { toast("Saisissez un n° producteur ou de commande.", "ko"); return; }
      $("#tr-res").innerHTML = '<div class="muted">Recherche…</div>';
      let ds;
      try { ds = await api(`/intersociete/tracer?societe_id=${currentSocieteId}&q=${encodeURIComponent(q)}`); }
      catch (e) { $("#tr-res").innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }
      $("#tr-res").innerHTML = !ds.length ? '<div class="empty"><i class="ti ti-search-off"></i>Aucun dossier trouvé.</div>'
        : ds.map((x) => {
          const t = x.reception ? x.reception.totaux : null;
          return `<div class="card" style="margin-bottom:12px"><div class="card-hdr"><div class="card-hdr-title">
            <span class="num-cell">${esc(x.commande.numero)}</span>
            ${x.reference_producteur ? `<span class="tag"><i class="ti ti-barcode"></i> ${esc(x.reference_producteur)}</span>` : ""}
            <span class="pill ${x.commande.statut === "soldee" ? "st-payee" : "st-confirme"}">${esc(x.commande.statut)}</span></div></div>
          <div class="card-body"><table><tbody>
            <tr><td class="muted" style="width:190px">Commande</td><td>${x.commande.date} — <b>${esc(x.commande.acheteur)}</b> → ${esc(x.commande.vendeur)} · ${fmtNum(x.commande.qte_commandee)} commandés · ${fmtNum(x.commande.total_ht)} $ HT${x.commande.destination ? ` · ${esc(x.commande.destination)}` : ""}</td></tr>
            ${x.prise_en_charge ? `<tr><td class="muted">Prise en charge vendeur</td><td>${esc(x.prise_en_charge.numero)} (${esc(x.prise_en_charge.statut)})${x.prise_en_charge.date ? " le " + x.prise_en_charge.date.slice(0, 10) : ""}</td></tr>` : ""}
            ${(x.chargements || []).length ? `<tr><td class="muted">Chargements</td><td>${x.chargements.map((b) => `${esc(b.numero)} le ${b.date} (${fmtNum(b.qte)})`).join(" · ")}</td></tr>` : ""}
            ${x.transport ? `<tr><td class="muted">Transport</td><td><b>${esc(x.transport.transporteur || "")}</b> — ${esc(x.transport.course)} <span class="pill ${(COURSE_ST[x.transport.statut] || ["", ""])[1]}">${esc((COURSE_ST[x.transport.statut] || [x.transport.statut])[0])}</span>${x.transport.camion ? ` · camion ${esc(x.transport.camion)}` : ""}${x.transport.depart ? ` · départ ${x.transport.depart.slice(0, 16).replace("T", " ")}` : ""}</td></tr>` : ""}
            ${t ? `<tr><td class="muted">Réception acheteur</td><td>${fmtNum(t.bon)} bon état · ${fmtNum(t.mauvais)} mauvais · <span style="color:var(--r)">${fmtNum(t.manquant)} manquants (${fmtNum(x.reception.valeur_manquants_usd)} $)</span> — ${x.reception.toutes_confirmees ? "confirmée transporteur ✓" : (x.reception.receptions.length ? "à confirmer" : "pas encore reçue")}</td></tr>` : ""}
            ${(x.factures_vendeur || []).length ? `<tr><td class="muted">Factures vendeur</td><td>${x.factures_vendeur.map((f) => `${esc(f.numero)} le ${f.date} (${fmtNum(f.ttc)} $, ${esc(f.statut)})`).join(" · ")}</td></tr>` : ""}
          </tbody></table></div></div>`;
        }).join("");
    };
    $("#tr-go").onclick = tracer;
    $("#tr-q").onkeydown = (e) => { if (e.key === "Enter") tracer(); };
  }
  el.querySelectorAll(".il-sel").forEach((s) => s.onchange = async (e) => {
    try {
      await api(`/intersociete/lier`, { method: "POST", body: { tiers_id: e.target.dataset.t, societe_liee_id: e.target.value || null } });
      toast(e.target.value ? "Tiers lié — les prochaines factures seront mirrorées." : "Liaison retirée.", "ok");
    } catch (er) { toast(er.message, "ko"); }
  });
  el.querySelectorAll("[data-ireg]").forEach((b) => b.onclick = async () => {
    const facs = await api(`/intersociete/factures`).catch(() => []);
    reglementInterModal(facs.find((f) => f.id === b.dataset.ireg));
  });
};

async function reglementInterModal(f) {
  if (!f) return;
  const [cV, cA] = await Promise.all([
    api(`/caisses?societe_id=${f.vendeur_societe_id}`).catch(() => []),
    f.acheteur_societe_id ? api(`/caisses?societe_id=${f.acheteur_societe_id}`).catch(() => []) : Promise.resolve([]),
  ]);
  const opts = (cs) => cs.map((c) => `<option value="${c.id}">${esc(c.libelle)}${c.session_ouverte ? "" : " (fermée)"}</option>`).join("");
  const cote = (id, titre, caisses) => `<div class="card" style="flex:1"><div class="card-body">
      <div style="font-weight:700;font-size:13px;margin-bottom:8px">${titre}</div>
      <div class="form-group"><label class="form-label">Mode</label><select id="${id}-mode" class="form-select">
        <option value="banque">Banque</option><option value="espece">Espèces (caisse)</option></select></div>
      <div class="form-group hidden" id="${id}-cw"><label class="form-label">Caisse</label><select id="${id}-caisse" class="form-select">${opts(caisses)}</select></div></div></div>`;
  modal({
    title: `Règlement intersociété — ${f.numero}`,
    wide: true,
    body: `<div class="banner"><i class="ti ti-arrows-exchange"></i> Une seule action, deux écritures : <b>sortie</b> de trésorerie chez ${esc(f.acheteur)} et <b>entrée</b> chez ${esc(f.vendeur)}.</div>
      <div class="total-bar" style="margin-top:0"><span class="lbl">Solde dû</span><span class="val">${fmtNum(f.solde_du_usd)} $</span></div>
      <div class="form-group" style="margin-top:10px"><label class="form-label">Montant à régler (USD)</label>
        <input id="ir-mnt" class="form-input right" type="number" step="any" value="${f.solde_du_usd}" style="width:160px" /></div>
      <div style="display:flex;gap:12px">
        ${cote("ir-a", `${esc(f.acheteur)} — paie (sortie)`, cA)}
        ${cote("ir-v", `${esc(f.vendeur)} — reçoit (entrée)`, cV)}</div>
      <div class="form-group" style="margin-top:10px"><label class="form-label">Référence (n° virement, bordereau…)</label><input id="ir-ref" class="form-input" /></div>`,
    footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="ir-ok"><i class="ti ti-arrows-exchange"></i> Régler les deux côtés</button>`,
  });
  ["ir-a", "ir-v"].forEach((id) => $(`#${id}-mode`).onchange = (e) => $(`#${id}-cw`).classList.toggle("hidden", e.target.value !== "espece"));
  $("#ir-ok").onclick = async () => {
    try {
      const r = await api(`/intersociete/factures/${f.id}/regler`, { method: "POST", body: {
        montant_usd: +$("#ir-mnt").value || null,
        acheteur_mode: $("#ir-a-mode").value, acheteur_caisse_id: $("#ir-a-mode").value === "espece" ? $("#ir-a-caisse").value : null,
        vendeur_mode: $("#ir-v-mode").value, vendeur_caisse_id: $("#ir-v-mode").value === "espece" ? $("#ir-v-caisse").value : null,
        reference: $("#ir-ref").value || null } });
      closeModal();
      toast(r.statut_reglement === "payee" ? `${f.numero} soldée des deux côtés ✓` : `Règlement partiel — reste ${fmtNum(r.solde_du_usd)} $.`, "ok");
      RENDER.intersociete();
    } catch (e) { toast(e.message, "ko"); }
  };
}

// ── Contrats de transport ────────────────────────────────────────────
RENDER["contrats-transport"] = async () => {
  const el = $("#view-contrats-transport");
  el.innerHTML = `<div class="muted">Chargement…</div>`;
  const cs = await api(`/transport/contrats?societe_id=${currentSocieteId}`).catch(() => []);
  el.innerHTML = `<div class="section-hdr" style="margin-bottom:12px">
      <div class="section-title"><i class="ti ti-writing-sign"></i> Contrats de transport</div>
      <button class="btn btn-sm btn-primary" id="ct-new" style="margin-left:auto"><i class="ti ti-plus"></i> Nouveau contrat</button></div>
    ${!cs.length ? '<div class="empty"><i class="ti ti-writing-sign"></i>Aucun contrat — créez le contrat-cadre de votre grand client.</div>'
      : cs.map((c) => `<div class="card" style="margin-bottom:12px"><div class="card-hdr">
          <div class="card-hdr-title"><span class="num-cell">${esc(c.numero)}</span> ${esc(c.libelle)}
            ${c.intra_groupe ? '<span class="tag">groupe</span>' : ""}
            <span class="pill ${c.statut === "actif" ? "st-payee" : "st-brouillon"}">${esc(c.statut)}</span></div>
          <div class="muted" style="font-size:12px">${esc(c.client)} · du ${c.date_debut}${c.date_fin ? " au " + c.date_fin : ""} · ${c.nb_courses} course(s)</div></div>
        <div class="card-body">${c.tarifs.length ? `<table><thead><tr><th>Trajet</th><th>Mode</th><th class="right">Prix USD</th></tr></thead><tbody>
          ${c.tarifs.map((t) => `<tr><td>${esc(t.trajet)}</td><td>${t.mode === "tonne" ? "à la tonne" : "forfait voyage"}</td><td class="right">${fmtNum(t.prix)}</td></tr>`).join("")}</tbody></table>` : '<div class="muted">Aucune grille tarifaire.</div>'}
          ${c.note ? `<div class="muted" style="font-size:12px;margin-top:8px">${esc(c.note)}</div>` : ""}</div></div>`).join("")}`;
  $("#ct-new").onclick = () => contratModal();
};

async function contratModal() {
  const clients = (await api(`/commercial/tiers?societe_id=${currentSocieteId}&type=client`).catch(() => []))
    .filter((c) => c.code !== "COMPTANT");
  const tarifRow = () => `<tr class="tr-row">
    <td><input class="form-input tr-traj" placeholder="Likasi → Kolwezi" /></td>
    <td><select class="form-select tr-mode"><option value="tonne">à la tonne</option><option value="voyage">forfait voyage</option></select></td>
    <td><input class="form-input tr-prix right" type="number" step="any" style="width:100px" /></td>
    <td><button class="btn btn-sm tr-del"><i class="ti ti-trash"></i></button></td></tr>`;
  modal({
    title: "Nouveau contrat de transport",
    wide: true,
    body: `<div class="form-row">
        <div class="form-group" style="flex:2"><label class="form-label">Libellé</label><input id="ct-lib" class="form-input" placeholder="ex. Contrat cadre 2026 — Société minière X" /></div>
        <div class="form-group"><label class="form-label">Client</label><select id="ct-cli" class="form-select">${clients.map((c) => `<option value="${c.id}">${esc(Catalogue.label(c))}</option>`).join("")}</select></div></div>
      <div class="form-row">
        <div class="form-group"><label class="form-label">Début</label><input id="ct-deb" class="form-input" type="date" value="${isoLocal(new Date())}" /></div>
        <div class="form-group"><label class="form-label">Fin (optionnel)</label><input id="ct-fin" class="form-input" type="date" /></div></div>
      <div class="muted" style="font-size:12px;margin-bottom:6px">Grille tarifaire par trajet</div>
      <table class="lignes-table"><thead><tr><th>Trajet</th><th>Mode</th><th class="right">Prix USD</th><th></th></tr></thead><tbody id="ct-tarifs">${tarifRow()}</tbody></table>
      <button class="btn btn-sm" id="ct-addt" style="margin-top:8px"><i class="ti ti-plus"></i> Ajouter un trajet</button>
      <div class="form-group" style="margin-top:10px"><label class="form-label">Note (conditions particulières, sous-traitance autorisée…)</label><input id="ct-note" class="form-input" /></div>`,
    footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="ct-ok"><i class="ti ti-check"></i> Créer le contrat</button>`,
  });
  const wire = () => document.querySelectorAll(".tr-del").forEach((b) => b.onclick = () => { b.closest("tr").remove(); });
  $("#ct-addt").onclick = () => { $("#ct-tarifs").insertAdjacentHTML("beforeend", tarifRow()); wire(); };
  wire();
  $("#ct-ok").onclick = async () => {
    const tarifs = [...document.querySelectorAll(".tr-row")].map((tr) => ({
      trajet: tr.querySelector(".tr-traj").value.trim(),
      mode: tr.querySelector(".tr-mode").value,
      prix: +tr.querySelector(".tr-prix").value || 0,
    })).filter((t) => t.trajet && t.prix > 0);
    try {
      await api(`/transport/contrats?societe_id=${currentSocieteId}`, { method: "POST", body: {
        libelle: $("#ct-lib").value, client_tiers_id: $("#ct-cli").value,
        date_debut: $("#ct-deb").value, date_fin: $("#ct-fin").value || null,
        note: $("#ct-note").value || null, tarifs } });
      closeModal(); toast("Contrat créé.", "ok"); RENDER["contrats-transport"]();
    } catch (e) { toast(e.message, "ko"); }
  };
}

// ── Réception physique d'un PO intersociété (bon / mauvais / manquant) ─
function receptionPOModal(d) {
  const rc = d.intersociete.reception;
  const lignes = rc.lignes.filter((l) => l.a_recevoir > 0);
  modal({
    title: `Réception — ${d.numero}`,
    wide: true,
    body: `<div class="banner"><i class="ti ti-package-import"></i> Constatez ce qui arrive réellement.
        Le <b>reçu</b> (bon + mauvais état) entre en stock ; les <b>manquants</b> sont mis à la charge du
        transporteur au prix d'achat. Le fournisseur facturera la quantité chargée.</div>
      <table><thead><tr><th>Article</th><th class="right">À recevoir</th>
        <th class="right">Bon état</th><th class="right">Mauvais état</th><th class="right">Manquant</th><th class="right">Contrôle</th></tr></thead><tbody>
      ${lignes.map((l) => `<tr data-lrec="${l.ligne_commande_id}" data-max="${l.a_recevoir}">
        <td>${esc(l.designation)}</td><td class="right"><b>${fmtNum(l.a_recevoir)}</b></td>
        <td class="right"><input class="form-input right rp-bon" type="number" step="any" min="0" value="${l.a_recevoir}" style="width:80px" /></td>
        <td class="right"><input class="form-input right rp-mv" type="number" step="any" min="0" value="0" style="width:80px" /></td>
        <td class="right"><input class="form-input right rp-mq" type="number" step="any" min="0" value="0" style="width:80px" /></td>
        <td class="right rp-ctl"><i class="ti ti-check" style="color:var(--g)"></i></td></tr>`).join("")}
      </tbody></table>
      <div class="form-group" style="margin-top:10px"><label class="form-label">Note (état du chargement, réserves…)</label><input id="rp-note" class="form-input" /></div>`,
    footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="rp-ok"><i class="ti ti-package-import"></i> Valider la réception</button>`,
  });
  const ctl = () => document.querySelectorAll("[data-lrec]").forEach((tr) => {
    const tot = (+tr.querySelector(".rp-bon").value || 0) + (+tr.querySelector(".rp-mv").value || 0) + (+tr.querySelector(".rp-mq").value || 0);
    const max = +tr.dataset.max;
    tr.querySelector(".rp-ctl").innerHTML = tot > max + 1e-6
      ? `<span style="color:var(--r);font-size:11px">> ${fmtNum(max)} !</span>`
      : (Math.abs(tot - max) < 1e-6 ? '<i class="ti ti-check" style="color:var(--g)"></i>'
         : `<span class="muted" style="font-size:11px">${fmtNum(tot)} / ${fmtNum(max)}</span>`);
  });
  document.querySelectorAll(".rp-bon,.rp-mv,.rp-mq").forEach((i) => i.oninput = ctl);
  ctl();
  $("#rp-ok").onclick = async () => {
    const lignesOut = [...document.querySelectorAll("[data-lrec]")].map((tr) => ({
      ligne_commande_id: tr.dataset.lrec,
      qte_bon: +tr.querySelector(".rp-bon").value || 0,
      qte_mauvais: +tr.querySelector(".rp-mv").value || 0,
      qte_manquante: +tr.querySelector(".rp-mq").value || 0,
    })).filter((l) => l.qte_bon + l.qte_mauvais + l.qte_manquante > 0);
    if (!lignesOut.length) { toast("Renseignez au moins une quantité.", "ko"); return; }
    try {
      const r = await api(`/intersociete/commandes/${d.id}/receptionner`, { method: "POST", body: {
        lignes: lignesOut, note: $("#rp-note").value || null } });
      closeModal(); closeModal();
      toast(`Réception ${r.numero} enregistrée${r.manquants_usd ? ` — manquants ${fmtNum(r.manquants_usd)} $ imputés au transporteur` : ""}.`, r.manquants_usd ? "warn" : "ok");
      RENDER.commandes();
    } catch (e) { toast(e.message, "ko"); }
  };
}

// ── Bon de réception intersociété imprimable ─────────────────────────
async function printBonReception(recId) {
  let r; try { r = await api(`/intersociete/receptions/${recId}`); } catch (e) { toast(e.message, "ko"); return; }
  _docA4({
    titre: "BON DE RÉCEPTION",
    numero: r.numero,
    client: r.fournisseur,
    meta: [["Date", r.date], ["Commande", r.commande || "—"],
           ...(r.reference_producteur ? [["Réf. producteur", r.reference_producteur]] : []),
           ...(r.transporteur ? [["Transporteur", r.transporteur]] : []),
           ...(r.destination ? [["Lieu", r.destination]] : []),
           ["Statut", r.statut === "confirmee" ? "Confirmé par le transporteur" : "À confirmer par le transporteur"]],
    colonnes: [{ t: "Désignation" }, { t: "Bon état", r: 1 }, { t: "Mauvais état", r: 1 }, { t: "Manquant", r: 1 }, { t: "P.U. ($)", r: 1 }],
    lignes: r.lignes.map((l) => [esc(l.designation), fmtNum(l.bon), fmtNum(l.mauvais), fmtNum(l.manquant), fmtNum(l.prix_unitaire)]),
    totaux: r.valeur_manquants_usd ? [{ l: "MANQUANTS (à charge du transporteur, prix d'achat)", v: fmtNum(r.valeur_manquants_usd) + " USD", grand: 1 }] : null,
    mentions: (r.note ? `<b>Réserves :</b> ${esc(r.note)}<br/>` : "") +
      "Le reçu (bon + mauvais état) entre en stock ; les manquants sont supportés par le transporteur au prix d'achat (règle du groupe).",
    signatures: ["Le réceptionnaire (acheteur)", "Le chauffeur / transporteur"],
  });
}

// ── Export CSV générique (BOM UTF-8 → s'ouvre proprement dans Excel) ─
function exporterCSV(nomFichier, entetes, lignes) {
  const csv = ModuleUX.toCSV(entetes, lignes);
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  a.download = nomFichier;
  a.click();
  URL.revokeObjectURL(a.href);
  toast(`Export ${nomFichier} téléchargé.`, "ok");
}

// ── Filtre de recherche générique sur les listes ─────────────────────
function filtreTable(el) {
  if (ModuleUX.managesLists(activeView)) return;
  el.querySelectorAll(".card-body table, .card > .card-body > table").forEach((t2) => {});
  const tables = el.querySelectorAll("table");
  if (!tables.length || el.querySelector(".filtre-liste")) return;
  const hdr = el.querySelector(".section-hdr");
  if (!hdr) return;
  const inp = document.createElement("input");
  inp.className = "form-input filtre-liste";
  inp.placeholder = "🔍 Filtrer (n°, client, statut, référence…)";
  inp.style.cssText = "width:250px;margin-left:10px";
  inp.oninput = () => {
    const q = inp.value.toLowerCase();
    el.querySelectorAll("tbody tr").forEach((tr) => {
      tr.style.display = !q || tr.textContent.toLowerCase().includes(q) ? "" : "none";
    });
  };
  hdr.appendChild(inp);
}

// ── Réglages transport (rôle validateur des fiches de course) ────────
let transportCfg = { role_validation: "DFI", roles: [] };
async function chargerTransportCfg() {
  try { transportCfg = await api(`/transport/config?societe_id=${currentSocieteId}`); } catch {}
}
function reglagesTransportModal() {
  modal({
    title: "Réglages transport",
    body: `<div class="form-group"><label class="form-label">Rôle validateur des fiches de course</label>
      <select id="rt2-role" class="form-select">${(transportCfg.roles || []).map((r) => `<option value="${r.code}" ${r.code === transportCfg.role_validation ? "selected" : ""}>${esc(r.code)} — ${esc(r.libelle)}</option>`).join("")}</select>
      <div class="muted" style="font-size:12px;margin-top:6px">PROC-KL-01 prévoit le DFI par défaut, mais vous pouvez déléguer (DG, assistant technique…). S'applique à la société courante.</div></div>`,
    footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="rt2-ok"><i class="ti ti-check"></i> Enregistrer</button>`,
  });
  $("#rt2-ok").onclick = async () => {
    try {
      await api(`/transport/config?societe_id=${currentSocieteId}`, { method: "POST", body: { role_validation: $("#rt2-role").value } });
      closeModal(); toast("Validateur des fiches de course mis à jour.", "ok");
      await chargerTransportCfg(); RENDER.courses();
    } catch (e) { toast(e.message, "ko"); }
  };
}

// ═══ Administration : sociétés, agents, tiers ════════════════════════
let adminTab = "societes";
RENDER.administration = async () => {
  const el = $("#view-administration");
  el.innerHTML = `<div class="muted">Chargement…</div>`;
  const seg = `<div class="seg">
    <button data-ad="societes" class="${adminTab === "societes" ? "on" : ""}">Sociétés</button>
    <button data-ad="agents" class="${adminTab === "agents" ? "on" : ""}">Agents</button>
    <button data-ad="roles" class="${adminTab === "roles" ? "on" : ""}">Rôles</button>
    <button data-ad="tiers" class="${adminTab === "tiers" ? "on" : ""}">Tiers</button></div>`;
  let body = "";
  if (adminTab === "societes") {
    const socs = (await api(`/config/societes`).catch(() => [])).filter((s) => s.id);
    window._adSocsFull = socs;
    body = `<div class="card"><div class="card-hdr"><div class="card-hdr-title"><i class="ti ti-building"></i> Sociétés du groupe</div>
        <button class="btn btn-sm btn-primary" id="ad-soc-new"><i class="ti ti-plus"></i> Nouvelle société</button></div>
      <div class="card-body"><table><thead><tr><th>Code</th><th>Nom</th><th>Ville</th><th>RCCM</th><th>Statut</th><th></th></tr></thead><tbody>
        ${socs.map((s) => `<tr ${s.actif ? "" : 'style="opacity:.55"'}>
          <td class="num-cell">${esc(s.code || "")}</td><td><b>${esc(s.nom)}</b></td>
          <td>${esc(s.ville || "—")}</td><td>${esc(s.rccm || "—")}</td>
          <td><span class="pill ${s.actif ? "st-payee" : "st-annule"}">${s.actif ? "Active" : "Archivée"}</span></td>
          <td class="right" style="white-space:nowrap">
            <button class="btn btn-sm" data-sedit="${s.id}" title="Modifier"><i class="ti ti-pencil"></i></button>
            <button class="btn btn-sm" data-sarch="${s.id}" data-actif="${s.actif}" title="${s.actif ? "Archiver (données conservées)" : "Réactiver"}"><i class="ti ${s.actif ? "ti-archive" : "ti-archive-off"}"></i></button>
            <button class="btn btn-sm" data-sdel="${s.id}" title="Supprimer (uniquement si sans activité)"><i class="ti ti-trash"></i></button>
          </td></tr>`).join("")}
      </tbody></table>
      <div class="banner" style="margin-top:10px"><i class="ti ti-info-circle"></i> <b>Archiver</b> masque la société partout mais conserve toutes ses données. <b>Supprimer</b> n'est possible que si la société n'a aucune activité (aucune écriture, facture, course…).</div></div></div>`;
  } else if (adminTab === "agents") {
    const [users, roles, socs] = await Promise.all([
      api(`/config/utilisateurs`).catch(() => []),
      api(`/config/roles`).catch(() => []),
      api(`/config/societes`).catch(() => []),
    ]);
    window._adRoles = roles; window._adSocs = socs;
    body = `<div class="card"><div class="card-hdr"><div class="card-hdr-title"><i class="ti ti-users"></i> Agents</div>
        <button class="btn btn-sm btn-primary" id="ad-usr-new"><i class="ti ti-user-plus"></i> Nouvel agent</button></div>
      <div class="card-body"><table><thead><tr><th>Nom</th><th>Email</th><th>Affectations (rôle@société)</th><th>Statut</th><th></th></tr></thead><tbody>
        ${users.map((u) => `<tr ${u.actif ? "" : 'style="opacity:.55"'}>
          <td><b>${esc(u.nom)}</b>${u.prenom ? " " + esc(u.prenom) : ""}</td><td>${esc(u.email)}</td>
          <td>${(u.affectations || []).map((a) => `<span class="tag">${esc(a)}</span>`).join(" ") || "—"}</td>
          <td><span class="pill ${u.actif ? "st-payee" : "st-annule"}">${u.actif ? "Actif" : "Désactivé"}</span></td>
          <td class="right" style="white-space:nowrap">
            <button class="btn btn-sm" data-uedit="${u.id}" title="Modifier l'identité"><i class="ti ti-pencil"></i></button>
            <button class="btn btn-sm" data-aff="${u.id}" title="Affectations"><i class="ti ti-building-plus"></i></button>
            <button class="btn btn-sm" data-mdp="${u.id}" title="Réinitialiser le mot de passe"><i class="ti ti-key"></i></button>
            <button class="btn btn-sm" data-tgl="${u.id}" data-actif="${u.actif}" title="${u.actif ? "Désactiver" : "Réactiver"}"><i class="ti ${u.actif ? "ti-user-off" : "ti-user-check"}"></i></button>
          </td></tr>`).join("")}
      </tbody></table></div></div>`;
    window._adUsers = users;
  } else if (adminTab === "roles") {
    const rolesL = await api(`/config/roles`).catch(() => []);
    window._adRolesFull = rolesL;
    body = `<div class="card"><div class="card-hdr"><div class="card-hdr-title"><i class="ti ti-id-badge-2"></i> Rôles</div>
        <button class="btn btn-sm btn-primary" id="ad-role-new"><i class="ti ti-plus"></i> Nouveau rôle</button></div>
      <div class="card-body"><table><thead><tr><th>Code</th><th>Libellé</th><th>Hérite des droits de</th><th class="right">Agents</th><th></th></tr></thead><tbody>
        ${rolesL.map((r) => `<tr>
          <td class="num-cell">${esc(r.code)}${r.systeme ? ' <span class="tag">système</span>' : ""}</td>
          <td>${esc(r.libelle)}</td>
          <td>${r.herite_de ? `<span class="tag">${esc(r.herite_de)}</span>` : '<span class="muted">—</span>'}</td>
          <td class="right">${r.nb_affectations}</td>
          <td class="right" style="white-space:nowrap">${r.systeme ? "" : `
            <button class="btn btn-sm" data-redit="${r.id}"><i class="ti ti-pencil"></i></button>
            <button class="btn btn-sm" data-rdel="${r.id}" title="Supprimer (si aucun agent)"><i class="ti ti-trash"></i></button>`}
          </td></tr>`).join("")}
      </tbody></table>
      <div class="banner" style="margin-top:10px"><i class="ti ti-info-circle"></i> Un rôle personnalisé (magasinier, logisticien…) <b>hérite des écrans</b> de son rôle de base — ex. LOGISTICIEN héritant de COMPTABLE accède aux mêmes modules. Sans héritage, le rôle est purement organisationnel. Les rôles système sont verrouillés.</div></div></div>`;
  } else {
    const [tiersL, liaisons] = await Promise.all([
      api(`/commercial/tiers?societe_id=${currentSocieteId}`).catch(() => []),
      api(`/intersociete/liaisons?societe_id=${currentSocieteId}`).catch(() => ({ societes: [], tiers: [] })),
    ]);
    const autresSocs = (liaisons.societes || []).filter((s) => s.id !== currentSocieteId);
    const socNom = esc((societes.find((s) => s.id === currentSocieteId) || {}).nom || "");
    body = `<div class="card"><div class="card-hdr"><div class="card-hdr-title"><i class="ti ti-address-book"></i> Tiers — ${socNom}</div>
        <button class="btn btn-sm btn-primary" id="ad-trs-new"><i class="ti ti-plus"></i> Nouveau tiers</button></div>
      <div class="card-body">
      ${!tiersL.length ? `<div class="empty"><i class="ti ti-address-book"></i>Aucun tiers chez ${socNom}.<br/>
          <span class="muted" style="font-size:12.5px">Les tiers appartiennent à la société sélectionnée en haut à droite — changez de société ou créez-en un ici.</span></div>`
        : `<table><thead><tr><th>Code</th><th>Nom</th><th>Type</th><th class="right">Crédit max $</th>
          <th>Société liée (groupe)</th><th></th></tr></thead><tbody>
        ${tiersL.filter((t) => t.code !== "COMPTANT").map((t) => {
          const lie = (liaisons.tiers || []).find((x) => x.id === t.id);
          return `<tr><td class="num-cell">${esc(t.code)}</td><td><b>${esc(Catalogue.label(t))}</b></td>
          <td>${esc(t.type)}</td><td class="right">${t.limite_credit_usd != null ? fmtNum(t.limite_credit_usd) : "—"}</td>
          <td><select class="form-select il-sel" data-t="${t.id}" style="width:auto;min-width:170px" title="Ce tiers représente-t-il une société du groupe ? Ce lien déclenche les factures miroir.">
            <option value="">— tiers externe —</option>
            ${autresSocs.map((s) => `<option value="${s.id}" ${lie && lie.societe_liee && lie.societe_liee.id === s.id ? "selected" : ""}>${esc(s.nom)}</option>`).join("")}
          </select></td>
          <td class="right"><button class="btn btn-sm" data-edt="${t.id}"><i class="ti ti-pencil"></i></button></td></tr>`; }).join("")}
      </tbody></table>`}
      <div class="banner" style="margin-top:10px"><i class="ti ti-affiliate"></i> <b>Société liée</b> : si ce tiers EST une société du groupe (ex. le fournisseur « DAKAM » chez KAKO), choisissez-la — c'est ce lien qui déclenche les commandes et factures miroir. Le récapitulatif se trouve aussi dans Groupe › Opérations intersociétés.</div></div></div>`;
  }
  el.innerHTML = `<div class="section-hdr" style="margin-bottom:12px">
      <div class="section-title"><i class="ti ti-shield-cog"></i> Administration</div>
      <div style="margin-left:auto">${seg}</div></div>${body}`;
  el.querySelectorAll("[data-ad]").forEach((b) => b.onclick = () => { adminTab = b.dataset.ad; RENDER.administration(); });
  if ($("#ad-soc-new")) $("#ad-soc-new").onclick = () => adminSocieteModal();
  if ($("#ad-usr-new")) $("#ad-usr-new").onclick = () => adminAgentModal();
  if ($("#ad-trs-new")) $("#ad-trs-new").onclick = () => adminTiersModal(null);
  if ($("#ad-role-new")) $("#ad-role-new").onclick = () => adminRoleModal();
  // ── Sociétés : modifier / archiver / supprimer ──
  el.querySelectorAll("[data-sedit]").forEach((b) => b.onclick = () =>
    adminSocieteEditModal((window._adSocsFull || []).find((s) => s.id === b.dataset.sedit)));
  el.querySelectorAll("[data-sarch]").forEach((b) => b.onclick = async () => {
    const active = b.dataset.actif === "true";
    if (active && !confirm("Archiver cette société ? Elle disparaîtra des écrans mais toutes ses données seront conservées.")) return;
    try { await api(`/config/societes/${b.dataset.sarch}`, { method: "PATCH", body: { actif: !active } });
      societes = await api("/societes");
      const sel = $("#societe-select");
      sel.innerHTML = societes.map((x) => `<option value="${x.id}">${esc(Catalogue.label(x))}</option>`).join("");
      if (!societes.find((x) => x.id === currentSocieteId)) currentSocieteId = societes[0] && societes[0].id;
      sel.value = currentSocieteId;
      toast(active ? "Société archivée (données conservées)." : "Société réactivée.", "ok");
      RENDER.administration(); } catch (e) { toast(e.message, "ko"); }
  });
  el.querySelectorAll("[data-sdel]").forEach((b) => b.onclick = async () => {
    if (!confirm("Supprimer DÉFINITIVEMENT cette société ? (refusé si elle a de l'activité)")) return;
    try { await api(`/config/societes/${b.dataset.sdel}`, { method: "DELETE" });
      societes = await api("/societes");
      const sel = $("#societe-select");
      sel.innerHTML = societes.map((x) => `<option value="${x.id}">${esc(Catalogue.label(x))}</option>`).join("");
      if (!societes.find((x) => x.id === currentSocieteId)) currentSocieteId = societes[0] && societes[0].id;
      sel.value = currentSocieteId;
      toast("Société supprimée.", "ok"); RENDER.administration(); } catch (e) { toast(e.message, "ko"); }
  });
  // ── Agents : modifier l'identité ──
  el.querySelectorAll("[data-uedit]").forEach((b) => b.onclick = () =>
    adminAgentEditModal((window._adUsers || []).find((u) => u.id === b.dataset.uedit)));
  // ── Rôles ──
  el.querySelectorAll("[data-redit]").forEach((b) => b.onclick = () =>
    adminRoleModal((window._adRolesFull || []).find((r) => r.id === b.dataset.redit)));
  el.querySelectorAll("[data-rdel]").forEach((b) => b.onclick = async () => {
    if (!confirm("Supprimer ce rôle ?")) return;
    try { await api(`/config/roles/${b.dataset.rdel}`, { method: "DELETE" });
      toast("Rôle supprimé.", "ok"); RENDER.administration(); } catch (e) { toast(e.message, "ko"); }
  });
  el.querySelectorAll("[data-edt]").forEach((b) => b.onclick = async () => {
    const ts = await api(`/commercial/tiers?societe_id=${currentSocieteId}`).catch(() => []);
    adminTiersModal(ts.find((t) => t.id === b.dataset.edt));
  });
  // Liaison intersociété directement depuis l'onglet Tiers
  el.querySelectorAll(".il-sel").forEach((s) => s.onchange = async (e) => {
    try {
      await api(`/intersociete/lier`, { method: "POST", body: { tiers_id: e.target.dataset.t, societe_liee_id: e.target.value || null } });
      toast(e.target.value ? "Tiers lié — les commandes et factures vers ce tiers seront mirrorées." : "Liaison retirée (tiers externe).", "ok");
    } catch (er) { toast(er.message, "ko"); }
  });
  el.querySelectorAll("[data-tgl]").forEach((b) => b.onclick = async () => {
    try { await api(`/config/utilisateurs/${b.dataset.tgl}`, { method: "PATCH", body: { actif: b.dataset.actif !== "true" } });
      toast("Statut mis à jour.", "ok"); RENDER.administration(); } catch (e) { toast(e.message, "ko"); }
  });
  el.querySelectorAll("[data-mdp]").forEach((b) => b.onclick = () => {
    modal({ title: "Réinitialiser le mot de passe",
      body: `<div class="form-group"><label class="form-label">Nouveau mot de passe (min. 6 caractères)</label><input id="ad-np" class="form-input" /></div>`,
      footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="ad-np-ok"><i class="ti ti-key"></i> Réinitialiser</button>` });
    $("#ad-np-ok").onclick = async () => {
      try { await api(`/config/utilisateurs/${b.dataset.mdp}`, { method: "PATCH", body: { password: $("#ad-np").value } });
        closeModal(); toast("Mot de passe réinitialisé — communiquez-le à l'agent.", "ok"); } catch (e) { toast(e.message, "ko"); }
    };
  });
  el.querySelectorAll("[data-aff]").forEach((b) => b.onclick = () => adminAffectationsModal(b.dataset.aff));
}

function adminSocieteEditModal(s) {
  if (!s) return;
  modal({
    title: `Modifier — ${s.nom}`,
    body: `<div class="form-group"><label class="form-label">Nom</label><input id="se-nom" class="form-input" value="${esc(s.nom)}" /></div>
      <div class="form-row">
        <div class="form-group"><label class="form-label">Ville</label><input id="se-ville" class="form-input" value="${esc(s.ville || "")}" /></div>
        <div class="form-group"><label class="form-label">RCCM</label><input id="se-rccm" class="form-input" value="${esc(s.rccm || "")}" /></div>
        <div class="form-group"><label class="form-label">ID Nat.</label><input id="se-idnat" class="form-input" value="${esc(s.id_nat || "")}" /></div></div>
      <div class="muted" style="font-size:12px">Le code (${esc(s.code)}) est figé — il numérote déjà vos pièces (FV-${esc(s.code)}-…).</div>`,
    footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="se-ok"><i class="ti ti-check"></i> Enregistrer</button>`,
  });
  $("#se-ok").onclick = async () => {
    try {
      await api(`/config/societes/${s.id}`, { method: "PATCH", body: {
        nom: $("#se-nom").value, ville: $("#se-ville").value,
        rccm: $("#se-rccm").value, id_nat: $("#se-idnat").value } });
      societes = await api("/societes");
      const sel = $("#societe-select");
      sel.innerHTML = societes.map((x) => `<option value="${x.id}">${esc(Catalogue.label(x))}</option>`).join("");
      sel.value = currentSocieteId;
      closeModal(); toast("Société modifiée.", "ok"); RENDER.administration();
    } catch (e) { toast(e.message, "ko"); }
  };
}

function adminAgentEditModal(u) {
  if (!u) return;
  modal({
    title: `Modifier — ${u.nom}`,
    body: `<div class="form-row">
        <div class="form-group"><label class="form-label">Nom</label><input id="ue-nom" class="form-input" value="${esc(u.nom)}" /></div>
        <div class="form-group"><label class="form-label">Prénom</label><input id="ue-prenom" class="form-input" value="${esc(u.prenom || "")}" /></div></div>
      <div class="form-group"><label class="form-label">Email (identifiant de connexion)</label><input id="ue-email" class="form-input" type="email" value="${esc(u.email)}" /></div>`,
    footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="ue-ok"><i class="ti ti-check"></i> Enregistrer</button>`,
  });
  $("#ue-ok").onclick = async () => {
    try {
      await api(`/config/utilisateurs/${u.id}`, { method: "PATCH", body: {
        nom: $("#ue-nom").value, prenom: $("#ue-prenom").value, email: $("#ue-email").value } });
      closeModal(); toast("Agent modifié.", "ok"); RENDER.administration();
    } catch (e) { toast(e.message, "ko"); }
  };
}

function adminRoleModal(existant) {
  const bases = (window._adRolesFull || []).filter((r) => !existant || r.code !== existant.code);
  modal({
    title: existant ? `Modifier le rôle ${existant.code}` : "Nouveau rôle",
    body: `${existant ? "" : `<div class="form-group"><label class="form-label">Code (ex. LOGISTICIEN, MAGASINIER)</label>
        <input id="ar-code" class="form-input" style="text-transform:uppercase" /></div>`}
      <div class="form-group"><label class="form-label">Libellé</label><input id="ar-lib" class="form-input" value="${existant ? esc(existant.libelle) : ""}" placeholder="ex. Logisticien / Dispatcher" /></div>
      <div class="form-group"><label class="form-label">Hérite des droits d'accès de</label>
        <select id="ar-herite" class="form-select"><option value="">— aucun (rôle organisationnel) —</option>
          ${bases.map((r) => `<option value="${r.code}" ${existant && existant.herite_de === r.code ? "selected" : ""}>${esc(r.code)} — ${esc(r.libelle)}</option>`).join("")}</select>
        <div class="muted" style="font-size:12px;margin-top:4px">L'agent verra les mêmes écrans que le rôle de base ; son titre reste le sien.</div></div>`,
    footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="ar-ok"><i class="ti ti-check"></i> ${existant ? "Enregistrer" : "Créer le rôle"}</button>`,
  });
  $("#ar-ok").onclick = async () => {
    try {
      if (existant) {
        await api(`/config/roles/${existant.id}`, { method: "PATCH", body: {
          libelle: $("#ar-lib").value, herite_de: $("#ar-herite").value || "" } });
      } else {
        await api(`/config/roles`, { method: "POST", body: {
          code: $("#ar-code").value, libelle: $("#ar-lib").value,
          herite_de: $("#ar-herite").value || null } });
      }
      closeModal(); toast("Rôle enregistré.", "ok"); RENDER.administration();
    } catch (e) { toast(e.message, "ko"); }
  };
}

function adminSocieteModal() {
  modal({
    title: "Nouvelle société du groupe",
    body: `<div class="form-row">
        <div class="form-group"><label class="form-label">Code (2-6 lettres)</label><input id="as-code" class="form-input" placeholder="DAK" style="text-transform:uppercase" /></div>
        <div class="form-group" style="flex:2"><label class="form-label">Nom</label><input id="as-nom" class="form-input" placeholder="DAKAM Sarl" /></div></div>
      <div class="form-group"><label class="form-label">Ville</label><input id="as-ville" class="form-input" placeholder="Likasi" /></div>`,
    footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="as-ok"><i class="ti ti-building-plus"></i> Créer la société</button>`,
  });
  $("#as-ok").onclick = async () => {
    try {
      const s = await api(`/config/societes`, { method: "POST", body: {
        code: $("#as-code").value, nom: $("#as-nom").value, ville: $("#as-ville").value || null } });
      societes = await api("/societes");
      const sel = $("#societe-select");
      sel.innerHTML = societes.map((x) => `<option value="${x.id}">${esc(Catalogue.label(x))}</option>`).join("");
      sel.value = currentSocieteId;
      closeModal(); toast(`Société ${s.nom} créée — plan comptable et caisse principale prêts.`, "ok");
      RENDER.administration();
    } catch (e) { toast(e.message, "ko"); }
  };
}

function adminAgentModal() {
  const roles = window._adRoles || [], socs = window._adSocs || [];
  const affRow = () => `<tr class="af-row">
    <td><select class="form-select af-soc">${socs.map((s) => `<option value="${s.id}">${esc(s.nom)}</option>`).join("")}</select></td>
    <td><select class="form-select af-role">${roles.map((r) => `<option value="${r.code}">${esc(r.code)} — ${esc(r.libelle)}</option>`).join("")}</select></td>
    <td><button class="btn btn-sm af-del"><i class="ti ti-trash"></i></button></td></tr>`;
  modal({
    title: "Nouvel agent",
    wide: true,
    body: `<div class="form-row">
        <div class="form-group"><label class="form-label">Nom</label><input id="au-nom" class="form-input" /></div>
        <div class="form-group"><label class="form-label">Prénom</label><input id="au-prenom" class="form-input" /></div></div>
      <div class="form-row">
        <div class="form-group"><label class="form-label">Email (identifiant)</label><input id="au-email" class="form-input" type="email" placeholder="prenom.nom@kilima.cd" /></div>
        <div class="form-group"><label class="form-label">Mot de passe initial</label><input id="au-mdp" class="form-input" placeholder="min. 6 caractères" /></div></div>
      <div class="muted" style="font-size:12px;margin:6px 0">Affectations (une ligne par société × rôle)</div>
      <table class="lignes-table"><thead><tr><th>Société</th><th>Rôle</th><th></th></tr></thead><tbody id="au-affs">${affRow()}</tbody></table>
      <button class="btn btn-sm" id="au-add" style="margin-top:8px"><i class="ti ti-plus"></i> Ajouter une affectation</button>`,
    footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="au-ok"><i class="ti ti-user-plus"></i> Créer l'agent</button>`,
  });
  const wire = () => document.querySelectorAll(".af-del").forEach((b) => b.onclick = () => b.closest("tr").remove());
  $("#au-add").onclick = () => { $("#au-affs").insertAdjacentHTML("beforeend", affRow()); wire(); };
  wire();
  $("#au-ok").onclick = async () => {
    const affectations = [...document.querySelectorAll(".af-row")].map((tr) => ({
      societe_id: tr.querySelector(".af-soc").value, role_code: tr.querySelector(".af-role").value }));
    try {
      const u = await api(`/config/utilisateurs`, { method: "POST", body: {
        nom: $("#au-nom").value, prenom: $("#au-prenom").value || null,
        email: $("#au-email").value, password: $("#au-mdp").value, affectations } });
      closeModal(); toast(`Agent ${u.nom} créé (${u.affectations} affectation(s)).`, "ok");
      RENDER.administration();
    } catch (e) { toast(e.message, "ko"); }
  };
}

async function adminAffectationsModal(userId) {
  const [users, roles, socs, inter] = await Promise.all([
    api(`/config/utilisateurs`), api(`/config/roles`), api(`/config/societes`), Promise.resolve(null)]);
  const u = users.find((x) => x.id === userId);
  modal({
    title: `Affectations — ${esc(u.nom)}`,
    body: `<div style="margin-bottom:10px">${(u.affectations || []).map((a) => `<span class="tag">${esc(a)}</span>`).join(" ") || '<span class="muted">Aucune affectation.</span>'}</div>
      <div class="form-row">
        <div class="form-group"><label class="form-label">Société</label><select id="aa-soc" class="form-select">${socs.map((s) => `<option value="${s.id}">${esc(s.nom)}</option>`).join("")}</select></div>
        <div class="form-group"><label class="form-label">Rôle</label><select id="aa-role" class="form-select">${roles.map((r) => `<option value="${r.code}">${esc(r.code)}</option>`).join("")}</select></div></div>`,
    footer: `<button class="btn" onclick="closeModal()">Fermer</button>
      <button class="btn" id="aa-del"><i class="ti ti-minus"></i> Retirer</button>
      <button class="btn btn-primary" id="aa-add"><i class="ti ti-plus"></i> Ajouter</button>`,
  });
  const done = async (msg) => { closeModal(); toast(msg, "ok"); RENDER.administration(); };
  $("#aa-add").onclick = async () => {
    try { await api(`/config/affectations`, { method: "POST", body: {
      utilisateur_id: userId, societe_id: $("#aa-soc").value, role_code: $("#aa-role").value } });
      done("Affectation ajoutée."); } catch (e) { toast(e.message, "ko"); }
  };
  $("#aa-del").onclick = async () => {
    try { await api(`/config/affectations`, { method: "DELETE", body: {
      utilisateur_id: userId, societe_id: $("#aa-soc").value, role_code: $("#aa-role").value } });
      done("Affectation retirée."); } catch (e) { toast(e.message, "ko"); }
  };
}

function adminTiersModal(existant) {
  let duplicateConfirmation=null;
  modal({
    title: existant ? `Modifier — ${existant.nom}` : "Nouveau tiers",
    body: `<div class="form-row">
        ${existant ? "" : `<div class="form-group"><label class="form-label">Code</label><input id="at-code" class="form-input" /></div>`}
        <div class="form-group" style="flex:2"><label class="form-label">Nom</label><input id="at-nom" class="form-input" value="${existant ? esc(existant.nom) : ""}" /></div>
        <div class="form-group"><label class="form-label">Type</label><select id="at-type" class="form-select">
          <option value="client" ${existant && existant.type === "client" ? "selected" : ""}>Client</option>
          <option value="fournisseur" ${existant && existant.type === "fournisseur" ? "selected" : ""}>Fournisseur</option>
          ${existant && !["client", "fournisseur"].includes(existant.type) ? `<option value="${esc(existant.type)}" selected>${esc(existant.type)}</option>` : ""}</select></div></div>
      <div class="form-group"><label class="form-label">Plafond de crédit USD (clients — vide = pas de crédit encadré)</label>
        <input id="at-lim" class="form-input right" type="number" step="any" value="${existant && existant.limite_credit_usd != null ? existant.limite_credit_usd : ""}" style="width:160px" /></div>`,
    footer: `<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" id="at-ok"><i class="ti ti-check"></i> ${existant ? "Enregistrer" : "Créer"}</button>`,
  });
  $("#at-ok").onclick = async () => {
    const fingerprint=JSON.stringify([$("#at-code")?.value,$("#at-nom").value,$("#at-type").value]);
    if (!existant && !$("#at-code").value.trim()) { toast("Le code du tiers est obligatoire (ex. DAKAM, MUKENDI).", "ko"); return; }
    if (!$("#at-nom").value.trim()) { toast("Le nom du tiers est obligatoire.", "ko"); return; }
    try {
      if (existant) {
        await api(`/commercial/tiers/${existant.id}`, { method: "PATCH", body: {
          confirmer_homonyme:duplicateConfirmation===fingerprint, nom: $("#at-nom").value, type: $("#at-type").value,
          limite_credit_usd: $("#at-lim").value === "" ? null : +$("#at-lim").value } });
      } else {
        await api(`/commercial/tiers?societe_id=${currentSocieteId}`, { method: "POST", body: {
          confirmer_homonyme:duplicateConfirmation===fingerprint, type: $("#at-type").value, code: $("#at-code").value, nom: $("#at-nom").value,
          limite_credit_usd: $("#at-lim").value === "" ? null : +$("#at-lim").value } });
      }
      closeModal(); toast("Tiers enregistré.", "ok"); RENDER.administration();
    } catch (e) { if(Catalogue.confirmConflict(e,()=>{duplicateConfirmation=fingerprint;$("#at-ok").click();}))return; toast(e.message, "ko"); }
  };
}

// ═══ Démarrage ═══
Clotures.init();
RH.init();
RHPaie.init();
RHMensuel.init();
RHFinances.init();
Pilotage.init();
Navigation.organiser();
initWorkspace();
ModuleUX.init();
Catalogue.init();
window.go = go; window.closeModal = closeModal;
$("#btn-login").onclick = login;
$("#password").addEventListener("keydown", (e) => { if (e.key === "Enter") login(); });
$("#btn-logout").onclick = logout;
$("#societe-select").onchange = (e) => {
  if (pendingWrites.size || $("#modal-root").childElementCount) {
    e.target.value = currentSocieteId;
    toast("Terminez l’opération ou fermez la fenêtre avant de changer de société.", "ko"); return;
  }
  if(!Clotures.confirmLeave()){e.target.value=currentSocieteId;return;}
  currentSocieteId = e.target.value;
  localStorage.setItem("kh_societe_" + me.id, currentSocieteId);
  $("#nav-search").value = "";
  $("#nav-empty").classList.add("hidden");
  renderSidebar(); refreshBadge(); refreshComptaBadge(); go("accueil");
  Pilotage.badge();
};
document.querySelectorAll(".nav-item").forEach((n) => n.onclick = () => go(n.dataset.view));
if (token) boot().catch(() => logout());
