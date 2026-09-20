"use strict";

function setMobileMenu(open) {
  document.body.classList.toggle("menu-open", open);
  document.querySelector("#sidebar-backdrop")?.classList.toggle("hidden", !open);
  document.querySelector("#btn-menu")?.setAttribute("aria-expanded", String(open));
  const sidebar = document.querySelector("#sidebar");
  if (sidebar) sidebar.inert = !open && window.matchMedia("(max-width:760px)").matches;
}

function visibleModules() {
  return NAV.filter((g) => !g.roles || hasGlobal(...g.roles)).map((g) => ({
    ...g, items: g.items.filter((it) => !it.roles || hasGlobal(...it.roles)),
  })).filter((g) => g.items.length);
}

async function renderWorkspace() {
  const el = $("#view-accueil"), sid = currentSocieteId;
  const soc = societes.find((s) => s.id === sid);
  const groups = visibleModules();
  const allowed = new Set(groups.flatMap((g) => g.items.map((it) => it.v)));
  const link = (view, label, cls = "workspace-link") => allowed.has(view)
    ? `<button class="${cls}" data-go="${view}">${esc(label)}<span aria-hidden="true">↗</span></button>` : "";
  const recent = savedJSON("kh_recent_" + me.id, []).filter((v) => allowed.has(v) && TITLES[v]);
  const dateLabel = new Intl.DateTimeFormat("fr-CD", { weekday: "long", day: "numeric", month: "long", year: "numeric" }).format(new Date());
  const flows = [
    { n: "01", title: "De la demande au paiement", sub: "Demander, autoriser, décaisser et justifier.", steps: [["requisitions", "Réquisitions"], ["ordres", "Ordres de dépense"], ["avances", "Avances"]] },
    { n: "02", title: "Du devis à l’encaissement", sub: "Suivre vos ventes et les règlements clients.", steps: [["devis", "Devis & commandes"], ["ventes", "Factures de vente"], ["caisse", "Caisse"]] },
    { n: "03", title: "Des achats aux stocks", sub: "Commander, réceptionner et suivre les quantités.", steps: [["commandes", "Commandes"], ["receptions", "Réceptions"], ["stock", "Stock"]] },
  ].filter((f) => f.steps.some(([v]) => allowed.has(v)));
  el.innerHTML = `<section class="workspace-hero">
    <div><div class="workspace-eyebrow">VOTRE ESPACE DE TRAVAIL <span>·</span> ${esc(dateLabel)}</div>
    <h2>Bonjour, ${esc(me.prenom || me.nom)}.</h2>
    <p>Gardez le fil de vos opérations chez <strong>${esc(soc?.nom || "Kilima Holdings")}</strong>.</p></div>
    ${link("nouvelle-req", "Nouvelle réquisition", "btn btn-primary workspace-create")}
    </section>
    <div class="workspace-section-heading"><h3>Vos priorités</h3><span>Société active · données enregistrées</span></div>
    <div id="workspace-metrics" class="workspace-metrics" aria-live="polite"><div class="workspace-metric muted">Chargement des indicateurs…</div></div>
    ${recent.length ? `<section class="workspace-recent"><span>Accès récents</span>${recent.map((v) => link(v, TITLES[v][0], "recent-link")).join("")}</section>` : ""}
    <div class="workspace-section-heading"><h3>Suivez vos circuits de gestion</h3><span>Les étapes liées, au même endroit</span></div>
    <section class="workspace-flows">${flows.map((f) => `<article class="workspace-flow"><span class="flow-number">${f.n}</span><h4>${f.title}</h4><p>${f.sub}</p><div>${f.steps.map(([v, l]) => link(v, l)).join("")}</div></article>`).join("")}</section>
    <div class="workspace-section-heading"><h3>Tous vos modules</h3><span>${groups.length} espaces accessibles à votre compte</span></div>
    <section class="workspace-modules">${groups.filter((g) => g.g !== "Pilotage").map((g) => `<article class="workspace-module"><div class="module-icon"><i class="ti ${g.items[0].i}" aria-hidden="true"></i></div><div><h4>${esc(g.g)}</h4><div class="module-links">${g.items.map((it) => link(it.v, it.l)).join("")}</div></div></article>`).join("")}</section>`;
  const bindLinks = (target) => target.querySelectorAll("[data-go]").forEach((b) => b.onclick = () => go(b.dataset.go));
  bindLinks(el);
  async function metrics() {
    const root = el.querySelector("#workspace-metrics");
    try {
      const d = await api(`/dashboard?societe_id=${sid}`);
      if (sid !== currentSocieteId || !root.isConnected || !token) return;
      const cards = [
        ["Réquisitions soumises", d.requisitions_soumises, "En attente de validation", "requisitions", "amber"],
        ["Ordres à valider", d.ordres_a_valider, "Autorisations de sortie de fonds", "ordres", "blue"],
        ["Avances en cours", d.avances_en_cours, fmtUSD(d.avances_montant_usd), "avances", "green"],
        ["Avances en retard", d.avances_en_retard, "À examiner et à justifier", "avances", d.avances_en_retard ? "red" : "green"],
      ];
      root.innerHTML = cards.map(([label, value, hint, view, color]) => `<button class="workspace-metric ${color}" data-go="${view}"><span class="metric-label">${label}<span aria-hidden="true">↗</span></span><strong>${esc(value ?? "—")}</strong><span class="metric-hint">${esc(hint)}</span></button>`).join("");
      bindLinks(root);
    } catch (e) {
      if (!root.isConnected || sid !== currentSocieteId) return;
      root.innerHTML = `<div class="workspace-metric metric-unavailable"><span>Indicateurs indisponibles. ${esc(e.message)}</span><button class="btn btn-sm" id="retry-metrics">Réessayer</button></div>`;
      root.querySelector("#retry-metrics").onclick = metrics;
    }
  }
  await metrics();
}

function initWorkspace() {
  RENDER.accueil = renderWorkspace;
  setMobileMenu(false);
  window.matchMedia("(max-width:760px)").addEventListener("change", () => setMobileMenu(false));
  $("#btn-menu").onclick = () => setMobileMenu(!document.body.classList.contains("menu-open"));
  $("#sidebar-backdrop").onclick = () => { setMobileMenu(false); $("#btn-menu").focus(); };
  const search = $("#nav-search");
  search.addEventListener("input",()=>Navigation.rechercher(search.value));
  function connectionState() {
    const offline = !navigator.onLine, banner = $("#connection-banner");
    banner.classList.toggle("hidden", !offline);
    banner.textContent = offline ? "Connexion interrompue. Les opérations nécessitent une connexion au serveur. Conservez vos saisies et vérifiez la connexion avant de valider." : "";
  }
  window.addEventListener("online", connectionState);
  window.addEventListener("offline", connectionState);
  connectionState();
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k" && token) {
      e.preventDefault(); setMobileMenu(true); search.focus(); search.select();
    }
    const overlay = $("#modal-root").lastElementChild;
    if (e.key === "Escape") {
      if (overlay) closeModal(); else setMobileMenu(false);
    }
    if (e.key === "Tab" && overlay) {
      const focusable = [...overlay.querySelectorAll('button, input, select, textarea, a[href], [tabindex="0"]')].filter((x) => !x.disabled && x.getClientRects().length);
      const first = focusable[0], last = focusable.at(-1);
      if (!first) { e.preventDefault(); return; }
      if (e.shiftKey && (document.activeElement === first || !focusable.includes(document.activeElement))) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && (document.activeElement === last || !focusable.includes(document.activeElement))) { e.preventDefault(); first.focus(); }
    }
  });
}
