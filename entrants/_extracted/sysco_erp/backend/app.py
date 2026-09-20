"""
SYSCO ERP v2.0 — Backend Flask
Comptabilité OHADA · Multi-tenant · Multi-utilisateurs
"""
import sqlite3, json, io, hashlib, secrets, re
from datetime import datetime, date
from pathlib import Path
from flask import Flask, request, jsonify, send_from_directory, g

BASE    = Path(__file__).parent
DB_PATH = BASE / 'sysco.db'
FRONT   = BASE.parent / 'frontend'

app = Flask(__name__, static_folder=str(FRONT))
app.config['SECRET_KEY'] = 'sysco-erp-2025-ohada'

# ═══════════════════════════════════════════════════════════════════
# BASE DE DONNÉES
# ═══════════════════════════════════════════════════════════════════
def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(str(DB_PATH))
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys=ON")
        g.db.execute("PRAGMA journal_mode=WAL")
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    db = g.pop('db', None)
    if db: db.close()

def q(sql, p=(), one=False):
    cur = get_db().execute(sql, p)
    if one:
        r = cur.fetchone()
        return dict(r) if r else None
    return [dict(r) for r in cur.fetchall()]

def ex(sql, p=()):
    db = get_db()
    cur = db.execute(sql, p)
    db.commit()
    return cur.lastrowid

def init_db():
    schema = (BASE / 'schema.sql').read_text()
    db = sqlite3.connect(str(DB_PATH))
    db.executescript(schema)
    db.close()

# ═══════════════════════════════════════════════════════════════════
# CORS + ROUTING SPA
# ═══════════════════════════════════════════════════════════════════
@app.after_request
def cors(r):
    r.headers.update({
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Headers': 'Content-Type,Authorization',
        'Access-Control-Allow-Methods': 'GET,POST,PUT,DELETE,OPTIONS'
    })
    return r

@app.route('/api/ping')
def ping():
    return jsonify({'status': 'ok', 'version': '2.0', 'db': str(DB_PATH)})

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def spa(path):
    f = FRONT / path
    if path and f.exists():
        return send_from_directory(str(FRONT), path)
    idx = FRONT / 'index.html'
    if idx.exists():
        return idx.read_text(), 200, {'Content-Type': 'text/html; charset=utf-8'}
    return jsonify({'sysco': 'ERP API v2.0 running'})

# ═══════════════════════════════════════════════════════════════════
# TENANTS
# ═══════════════════════════════════════════════════════════════════
@app.route('/api/tenants')
def list_tenants():
    return jsonify(q("SELECT * FROM tenants WHERE actif=1 ORDER BY nom"))

@app.route('/api/tenants', methods=['POST'])
def create_tenant():
    d = request.json or {}
    if not d.get('code') or not d.get('nom'):
        return jsonify({'error': 'code et nom requis'}), 400
    tid = ex("INSERT INTO tenants(code,nom,rccm,id_nat,nif,adresse,ville,pays,devise,referentiel) VALUES(?,?,?,?,?,?,?,?,?,?)",
             (d['code'].upper(), d['nom'], d.get('rccm'), d.get('id_nat'), d.get('nif'),
              d.get('adresse'), d.get('ville','Lubumbashi'), d.get('pays','RDC'),
              d.get('devise','USD'), d.get('referentiel','SYSCOHADA')))
    _init_tenant(tid, d.get('annee', date.today().year))
    return jsonify(q("SELECT * FROM tenants WHERE id=?", (tid,), one=True)), 201

@app.route('/api/tenants/<int:tid>', methods=['PUT'])
def update_tenant(tid):
    d = request.json or {}
    ex("UPDATE tenants SET nom=?,rccm=?,id_nat=?,nif=?,adresse=?,ville=?,pays=?,devise=? WHERE id=?",
       (d.get('nom'), d.get('rccm'), d.get('id_nat'), d.get('nif'),
        d.get('adresse'), d.get('ville'), d.get('pays'), d.get('devise'), tid))
    return jsonify(q("SELECT * FROM tenants WHERE id=?", (tid,), one=True))

def _init_tenant(tid, annee):
    """Initialiser journaux et exercice pour un nouveau tenant"""
    ex("INSERT OR IGNORE INTO exercices(tenant_id,annee,date_debut,date_fin) VALUES(?,?,?,?)",
       (tid, annee, f"{annee}-01-01", f"{annee}-12-31"))
    journaux = [
        ('AN',  'A-Nouveaux',         'a_nouveaux'),
        ('BQ1', 'Banque RAWBANK',     'banque'),
        ('BQ2', 'Banque EQUITY BCDC', 'banque'),
        ('CA',  'Caisse Espèces',     'caisse'),
        ('VT',  'Journal Ventes',     'vente'),
        ('AC',  'Journal Achats',     'achat'),
        ('OD',  'Opérations Diverses','od'),
    ]
    for code, lib, typ in journaux:
        ex("INSERT OR IGNORE INTO journaux(tenant_id,code,libelle,type) VALUES(?,?,?,?)",
           (tid, code, lib, typ))

# ═══════════════════════════════════════════════════════════════════
# EXERCICES
# ═══════════════════════════════════════════════════════════════════
@app.route('/api/<int:tid>/exercices')
def list_exercices(tid):
    return jsonify(q("SELECT * FROM exercices WHERE tenant_id=? ORDER BY annee DESC", (tid,)))

@app.route('/api/<int:tid>/exercices', methods=['POST'])
def create_exercice(tid):
    d = request.json or {}
    annee = int(d.get('annee', date.today().year))
    eid = ex("INSERT OR IGNORE INTO exercices(tenant_id,annee,date_debut,date_fin) VALUES(?,?,?,?)",
             (tid, annee, d.get('date_debut', f"{annee}-01-01"), d.get('date_fin', f"{annee}-12-31")))
    return jsonify(q("SELECT * FROM exercices WHERE id=?", (eid,), one=True)), 201

@app.route('/api/<int:tid>/exercices/<int:eid>', methods=['PUT'])
def update_exercice(tid, eid):
    d = request.json or {}
    ex("UPDATE exercices SET statut=? WHERE id=? AND tenant_id=?",
       (d.get('statut','ouvert'), eid, tid))
    return jsonify(q("SELECT * FROM exercices WHERE id=?", (eid,), one=True))

def _get_exercice_actif(tid):
    r = q("SELECT id,annee FROM exercices WHERE tenant_id=? AND statut='ouvert' ORDER BY annee DESC LIMIT 1",
          (tid,), one=True)
    return (r['id'], r['annee']) if r else (None, None)

# ═══════════════════════════════════════════════════════════════════
# JOURNAUX
# ═══════════════════════════════════════════════════════════════════
@app.route('/api/<int:tid>/journaux')
def list_journaux(tid):
    return jsonify(q("SELECT * FROM journaux WHERE tenant_id=? ORDER BY code", (tid,)))

@app.route('/api/<int:tid>/journaux', methods=['POST'])
def create_journal(tid):
    d = request.json or {}
    jid = ex("INSERT INTO journaux(tenant_id,code,libelle,type,compte_default) VALUES(?,?,?,?,?)",
             (tid, d['code'].upper(), d['libelle'], d.get('type','od'), d.get('compte_default')))
    return jsonify(q("SELECT * FROM journaux WHERE id=?", (jid,), one=True)), 201

@app.route('/api/<int:tid>/journaux/<int:jid>', methods=['PUT'])
def update_journal(tid, jid):
    d = request.json or {}
    ex("UPDATE journaux SET libelle=?,type=?,compte_default=?,actif=? WHERE id=? AND tenant_id=?",
       (d.get('libelle'), d.get('type'), d.get('compte_default'), d.get('actif',1), jid, tid))
    return jsonify(q("SELECT * FROM journaux WHERE id=?", (jid,), one=True))

# ═══════════════════════════════════════════════════════════════════
# PLAN DE COMPTE
# ═══════════════════════════════════════════════════════════════════
@app.route('/api/<int:tid>/comptes')
def list_comptes(tid):
    search = request.args.get('q', '')
    classe = request.args.get('classe', '')
    sens   = request.args.get('sens', '')
    actif  = request.args.get('actif', '1')
    sql    = "SELECT * FROM comptes WHERE tenant_id=?"
    params = [tid]
    if actif != 'all': sql += " AND actif=?"; params.append(int(actif))
    if search: sql += " AND (numero LIKE ? OR intitule LIKE ?)"; params += [f'%{search}%']*2
    if classe: sql += " AND numero LIKE ?"; params.append(f'{classe}%')
    if sens:   sql += " AND sens_ohada=?"; params.append(sens)
    return jsonify(q(sql + " ORDER BY numero", params))

@app.route('/api/<int:tid>/comptes', methods=['POST'])
def create_compte(tid):
    d = request.json or {}
    if not d.get('numero') or not d.get('intitule'):
        return jsonify({'error': 'numero et intitule requis'}), 400
    cid = ex("INSERT INTO comptes(tenant_id,numero,intitule,classe,categorie,sens_ohada,rubrique) VALUES(?,?,?,?,?,?,?)",
             (tid, d['numero'], d['intitule'], d.get('classe'), d.get('categorie'),
              d.get('sens_ohada',''), d.get('rubrique','')))
    return jsonify(q("SELECT * FROM comptes WHERE id=?", (cid,), one=True)), 201

@app.route('/api/<int:tid>/comptes/<string:numero>', methods=['PUT'])
def update_compte(tid, numero):
    d = request.json or {}
    fields, vals = [], []
    for f in ['intitule','categorie','sens_ohada','rubrique','classe','actif']:
        if f in d: fields.append(f'{f}=?'); vals.append(d[f])
    if not fields: return jsonify({'error': 'rien à modifier'}), 400
    vals += [tid, numero]
    ex(f"UPDATE comptes SET {','.join(fields)} WHERE tenant_id=? AND numero=?", vals)
    return jsonify(q("SELECT * FROM comptes WHERE tenant_id=? AND numero=?", (tid, numero), one=True))

@app.route('/api/<int:tid>/comptes/<string:numero>', methods=['DELETE'])
def delete_compte(tid, numero):
    n = q("SELECT COUNT(*) as n FROM lignes_ecriture WHERE tenant_id=? AND compte_numero=?",
          (tid, numero), one=True)['n']
    if n > 0:
        ex("UPDATE comptes SET actif=0 WHERE tenant_id=? AND numero=?", (tid, numero))
        return jsonify({'message': f'Compte désactivé (utilisé dans {n} lignes)'}), 200
    ex("DELETE FROM comptes WHERE tenant_id=? AND numero=?", (tid, numero))
    return jsonify({'message': 'Compte supprimé'}), 200

# ═══════════════════════════════════════════════════════════════════
# ÉCRITURES
# ═══════════════════════════════════════════════════════════════════
def _next_numero(tid, exid, annee):
    n = q("SELECT COUNT(*) as n FROM ecritures WHERE tenant_id=? AND exercice_id=?",
          (tid, exid), one=True)['n']
    return f"ECR-{annee}-{n+1:04d}"

def _validate_ohada(lignes):
    errors = []
    td = sum(l['montant'] for l in lignes if l['sens']=='D')
    tc = sum(l['montant'] for l in lignes if l['sens']=='C')
    if abs(td - tc) > 0.01:
        errors.append(f"Déséquilibre D/C : Débit={td:.2f} ≠ Crédit={tc:.2f} (écart {abs(td-tc):.2f})")
    if not any(l['sens']=='D' for l in lignes):
        errors.append("Aucune ligne au débit — principe de partie double non respecté")
    if not any(l['sens']=='C' for l in lignes):
        errors.append("Aucune ligne au crédit — principe de partie double non respecté")
    cd = {l['compte_numero'][:6] for l in lignes if l['sens']=='D'}
    cc = {l['compte_numero'][:6] for l in lignes if l['sens']=='C'}
    doublons = cd & cc
    if doublons:
        errors.append(f"Même compte au débit et au crédit : {', '.join(sorted(doublons))}")
    return errors, td, tc

@app.route('/api/<int:tid>/ecritures')
def list_ecritures(tid):
    exid    = request.args.get('exercice_id')
    jid     = request.args.get('journal_id')
    mois    = request.args.get('mois')
    qs      = request.args.get('q', '')
    statut  = request.args.get('statut', '')
    compte  = request.args.get('compte', '')
    limit   = min(int(request.args.get('limit', 100)), 500)
    offset  = int(request.args.get('offset', 0))

    if not exid:
        ex_r = _get_exercice_actif(tid)
        exid = ex_r[0]

    sql = """
        SELECT e.*, j.libelle as journal_libelle, j.code as journal_code,
               COUNT(l.id) as nb_lignes,
               COALESCE(SUM(CASE WHEN l.sens='D' THEN l.montant ELSE 0 END),0) as total_debit,
               COALESCE(SUM(CASE WHEN l.sens='C' THEN l.montant ELSE 0 END),0) as total_credit
        FROM ecritures e
        LEFT JOIN journaux j ON e.journal_id = j.id
        LEFT JOIN lignes_ecriture l ON e.id = l.ecriture_id
        WHERE e.tenant_id=?"""
    params = [tid]
    if exid:   sql += " AND e.exercice_id=?";                         params.append(exid)
    if jid:    sql += " AND e.journal_id=?";                          params.append(jid)
    if mois:   sql += " AND strftime('%Y-%m',e.date_ecriture)=?";     params.append(mois)
    if statut: sql += " AND e.statut=?";                              params.append(statut)
    if qs:     sql += " AND (e.libelle LIKE ? OR e.numero_piece LIKE ? OR e.numero LIKE ?)"; params += [f'%{qs}%']*3
    if compte: sql += " AND e.id IN (SELECT ecriture_id FROM lignes_ecriture WHERE compte_numero LIKE ?)"; params.append(f'{compte}%')
    sql += " GROUP BY e.id ORDER BY e.date_ecriture DESC, e.id DESC LIMIT ? OFFSET ?"
    params += [limit, offset]

    rows  = q(sql, params)
    total = q("SELECT COUNT(*) as n FROM ecritures WHERE tenant_id=?" + (" AND exercice_id=?" if exid else ""),
              [tid] + ([exid] if exid else []), one=True)['n']
    return jsonify({'rows': rows, 'total': total, 'limit': limit, 'offset': offset})

@app.route('/api/<int:tid>/ecritures', methods=['POST'])
def create_ecriture(tid):
    d      = request.json or {}
    lignes = d.get('lignes', [])

    errors, td, tc = _validate_ohada(lignes)
    if errors and not d.get('force'):
        return jsonify({'errors': errors, 'total_debit': td, 'total_credit': tc}), 422

    exid, annee = _get_exercice_actif(tid)
    if d.get('exercice_id'): exid = d['exercice_id']
    if not exid: return jsonify({'error': 'Aucun exercice ouvert'}), 400

    ex_info = q("SELECT annee FROM exercices WHERE id=?", (exid,), one=True)
    annee   = ex_info['annee'] if ex_info else date.today().year
    numero  = _next_numero(tid, exid, annee)

    eid = ex("""INSERT INTO ecritures
        (tenant_id,exercice_id,journal_id,numero,date_ecriture,numero_piece,
         libelle,type_operation,statut,user_id)
        VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (tid, exid, d.get('journal_id'), numero, d.get('date_ecriture', str(date.today())),
         d.get('numero_piece'), d['libelle'], d.get('type_operation'),
         d.get('statut','valide'), d.get('user_id')))

    for i, l in enumerate(lignes):
        ex("""INSERT INTO lignes_ecriture
            (ecriture_id,tenant_id,sens,compte_numero,montant,libelle_ligne,ordre)
            VALUES(?,?,?,?,?,?,?)""",
           (eid, tid, l['sens'], l['compte_numero'][:6],
            float(l['montant']), l.get('libelle_ligne',''), i))

    return jsonify({'id': eid, 'numero': numero,
                    'total_debit': td, 'total_credit': tc,
                    'message': f'Écriture {numero} enregistrée'}), 201

@app.route('/api/<int:tid>/ecritures/<int:eid>')
def get_ecriture(tid, eid):
    ecr = q("SELECT e.*,j.libelle as journal_libelle,j.code as journal_code FROM ecritures e LEFT JOIN journaux j ON e.journal_id=j.id WHERE e.id=? AND e.tenant_id=?",
            (eid,tid), one=True)
    if not ecr: return jsonify({'error': 'Non trouvé'}), 404
    ecr['lignes'] = q("""SELECT l.*,c.intitule FROM lignes_ecriture l
        LEFT JOIN comptes c ON l.tenant_id=c.tenant_id AND l.compte_numero=c.numero
        WHERE l.ecriture_id=? ORDER BY l.ordre""", (eid,))
    return jsonify(ecr)

@app.route('/api/<int:tid>/ecritures/<int:eid>', methods=['PUT'])
def update_ecriture(tid, eid):
    d = request.json or {}
    # Seul le statut et le libellé peuvent être modifiés après validation
    ex("UPDATE ecritures SET statut=?,libelle=? WHERE id=? AND tenant_id=?",
       (d.get('statut'), d.get('libelle'), eid, tid))
    return jsonify(q("SELECT * FROM ecritures WHERE id=?", (eid,), one=True))

@app.route('/api/<int:tid>/ecritures/<int:eid>/lignes')
def get_lignes(tid, eid):
    rows = q("""SELECT l.*,c.intitule,c.sens_ohada FROM lignes_ecriture l
        LEFT JOIN comptes c ON l.tenant_id=c.tenant_id AND l.compte_numero=c.numero
        WHERE l.ecriture_id=? AND l.tenant_id=? ORDER BY l.ordre""", (eid, tid))
    return jsonify(rows)

# ═══════════════════════════════════════════════════════════════════
# SOLDES D'OUVERTURE
# ═══════════════════════════════════════════════════════════════════
@app.route('/api/<int:tid>/soldes-ouverture')
def get_si(tid):
    exid = request.args.get('exercice_id')
    return jsonify(q("""SELECT so.*, c.intitule, c.sens_ohada
        FROM soldes_ouverture so
        LEFT JOIN comptes c ON so.tenant_id=c.tenant_id AND so.compte_numero=c.numero
        WHERE so.tenant_id=? AND so.exercice_id=? ORDER BY so.compte_numero""",
        (tid, exid)))

@app.route('/api/<int:tid>/soldes-ouverture', methods=['POST'])
def upsert_si(tid):
    d = request.json or {}
    exid = d.get('exercice_id')
    nb = 0
    for row in d.get('soldes', []):
        ex("""INSERT INTO soldes_ouverture(tenant_id,exercice_id,compte_numero,si_debit,si_credit,source)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(tenant_id,exercice_id,compte_numero)
            DO UPDATE SET si_debit=excluded.si_debit, si_credit=excluded.si_credit, source=excluded.source""",
           (tid, exid, row['compte_numero'],
            float(row.get('si_debit',0)), float(row.get('si_credit',0)),
            row.get('source','manuel')))
        nb += 1
    return jsonify({'message': f'{nb} soldes mis à jour', 'nb': nb})

# ═══════════════════════════════════════════════════════════════════
# BALANCE GÉNÉRALE
# ═══════════════════════════════════════════════════════════════════
def _compute_balance(tid, exid, classe='', search='', only_moved=False):
    sql = """
        SELECT c.numero, c.intitule, c.sens_ohada, c.categorie, c.rubrique,
            COALESCE(so.si_debit,0)  AS si_debit,
            COALESCE(so.si_credit,0) AS si_credit,
            COALESCE(SUM(CASE WHEN l.sens='D' THEN l.montant ELSE 0 END),0) AS mouv_debit,
            COALESCE(SUM(CASE WHEN l.sens='C' THEN l.montant ELSE 0 END),0) AS mouv_credit,
            COALESCE(so.si_debit,0)  + COALESCE(SUM(CASE WHEN l.sens='D' THEN l.montant ELSE 0 END),0) AS total_debit,
            COALESCE(so.si_credit,0) + COALESCE(SUM(CASE WHEN l.sens='C' THEN l.montant ELSE 0 END),0) AS total_credit,
            MAX(0,
                COALESCE(so.si_debit,0)  + COALESCE(SUM(CASE WHEN l.sens='D' THEN l.montant ELSE 0 END),0)
               -COALESCE(so.si_credit,0) - COALESCE(SUM(CASE WHEN l.sens='C' THEN l.montant ELSE 0 END),0)
            ) AS sf_debit,
            MAX(0,
                COALESCE(so.si_credit,0) + COALESCE(SUM(CASE WHEN l.sens='C' THEN l.montant ELSE 0 END),0)
               -COALESCE(so.si_debit,0)  - COALESCE(SUM(CASE WHEN l.sens='D' THEN l.montant ELSE 0 END),0)
            ) AS sf_credit
        FROM comptes c
        LEFT JOIN soldes_ouverture so
            ON so.tenant_id=c.tenant_id AND so.exercice_id=? AND so.compte_numero=c.numero
        LEFT JOIN lignes_ecriture l
            ON l.tenant_id=c.tenant_id AND l.compte_numero=c.numero
        LEFT JOIN ecritures e
            ON l.ecriture_id=e.id AND e.exercice_id=? AND e.statut != 'brouillon'
        WHERE c.tenant_id=? AND c.actif=1"""
    params = [exid, exid, tid]
    if classe: sql += " AND c.numero LIKE ?"; params.append(f'{classe}%')
    if search: sql += " AND (c.numero LIKE ? OR c.intitule LIKE ?)"; params += [f'%{search}%']*2
    sql += " GROUP BY c.numero ORDER BY c.numero"
    rows = q(sql, params)
    if only_moved:
        rows = [r for r in rows if r['total_debit']>0 or r['total_credit']>0]

    # Audit OHADA en ligne
    for row in rows:
        issues = []
        s = row['sens_ohada'] or ''
        n = row['numero']
        if s == 'ACTIF' and row['sf_credit'] > 0.01:
            issues.append({'code':'ACT_CRED','severite':'critique','msg':'Actif à solde créditeur'})
        if s == 'PASSIF' and row['sf_debit'] > 0.01:
            issues.append({'code':'PAS_DEB','severite':'warning','msg':'Passif à solde débiteur'})
        if n.startswith('51') and row['sf_credit'] > 0.01:
            issues.append({'code':'CAISSE_CRED','severite':'critique','msg':'Caisse créditrice — impossible'})
        if n.startswith('6') and row['sf_credit'] > 0.01:
            issues.append({'code':'CHARG_CRED','severite':'warning','msg':'Charge à solde créditeur'})
        if n.startswith('7') and row['sf_debit'] > 0.01:
            issues.append({'code':'PROD_DEB','severite':'warning','msg':'Produit à solde débiteur'})
        if n.startswith('496') and row['sf_debit'] > 0.01:
            issues.append({'code':'CC_ASS_DEB','severite':'warning','msg':'CC associé débiteur — convention requise'})
        if (n.startswith('28') or n.startswith('29')) and row['sf_debit'] > 0.01:
            issues.append({'code':'AMORT_DEB','severite':'critique','msg':'Amortissement à solde débiteur'})
        row['audit']           = issues
        row['audit_severite']  = ('critique' if any(a['severite']=='critique' for a in issues)
                                  else 'warning' if issues else 'ok')
    return rows

@app.route('/api/<int:tid>/balance')
def get_balance(tid):
    exid      = request.args.get('exercice_id')
    classe    = request.args.get('classe', '')
    search    = request.args.get('q', '')
    only_moved= request.args.get('only_moved','false') == 'true'
    anom_only = request.args.get('anomalies_only','false') == 'true'

    if not exid:
        ex_id, _ = _get_exercice_actif(tid)
        exid = ex_id
    if not exid: return jsonify({'rows':[], 'total_debit':0, 'total_credit':0, 'equilibre':True})

    rows = _compute_balance(tid, exid, classe, search, only_moved)
    if anom_only: rows = [r for r in rows if r['audit']]

    td = sum(r['total_debit']  for r in rows)
    tc = sum(r['total_credit'] for r in rows)
    return jsonify({
        'rows':       rows,
        'total_debit':  td,
        'total_credit': tc,
        'equilibre':    abs(td - tc) < 0.01,
        'nb_anomalies': sum(1 for r in rows if r['audit']),
        'critiques':    sum(1 for r in rows if r['audit_severite']=='critique'),
        'nb_comptes':   len(rows)
    })

# ═══════════════════════════════════════════════════════════════════
# KPI & STATISTIQUES
# ═══════════════════════════════════════════════════════════════════
def _sf(tid, exid, pfx, col='sf_d'):
    c = 'sf_d' if col=='sf_d' else 'sf_c'
    r = q(f"""SELECT COALESCE(SUM({c}),0) as v FROM (
        SELECT MAX(0,
            COALESCE(so.si_debit,0)+COALESCE(SUM(CASE WHEN l.sens='D' THEN l.montant ELSE 0 END),0)
           -COALESCE(so.si_credit,0)-COALESCE(SUM(CASE WHEN l.sens='C' THEN l.montant ELSE 0 END),0)) as sf_d,
        MAX(0,
            COALESCE(so.si_credit,0)+COALESCE(SUM(CASE WHEN l.sens='C' THEN l.montant ELSE 0 END),0)
           -COALESCE(so.si_debit,0)-COALESCE(SUM(CASE WHEN l.sens='D' THEN l.montant ELSE 0 END),0)) as sf_c
        FROM comptes c
        LEFT JOIN soldes_ouverture so ON so.tenant_id=c.tenant_id AND so.exercice_id=? AND so.compte_numero=c.numero
        LEFT JOIN lignes_ecriture l  ON l.tenant_id=c.tenant_id AND l.compte_numero=c.numero
        LEFT JOIN ecritures e        ON l.ecriture_id=e.id AND e.exercice_id=?
        WHERE c.tenant_id=? AND c.numero LIKE ? GROUP BY c.numero)""",
        (exid, exid, tid, f'{pfx}%'), one=True)
    return r['v'] if r else 0

def _si(tid, exid, pfx, col='si_debit'):
    r = q(f"""SELECT COALESCE(SUM({col}),0) as v
        FROM soldes_ouverture so JOIN comptes c ON so.tenant_id=c.tenant_id AND so.compte_numero=c.numero
        WHERE so.tenant_id=? AND so.exercice_id=? AND c.numero LIKE ?""",
        (tid, exid, f'{pfx}%'), one=True)
    return r['v'] if r else 0

@app.route('/api/<int:tid>/kpi')
def get_kpi(tid):
    exid = request.args.get('exercice_id')
    if not exid: exid, _ = _get_exercice_actif(tid)
    if not exid: return jsonify({})

    ca       = _sf(tid,exid,'7','sf_c')
    charges  = _sf(tid,exid,'6','sf_d')
    res      = ca - charges
    tres_d   = _sf(tid,exid,'5','sf_d')
    tres_c   = _sf(tid,exid,'5','sf_c')
    tres     = tres_d - tres_c
    creances = _sf(tid,exid,'411','sf_d')
    dettes   = _sf(tid,exid,'401','sf_c')
    cap      = _sf(tid,exid,'1','sf_c') - _sf(tid,exid,'1','sf_d')
    actif    = (_sf(tid,exid,'2','sf_d') - _sf(tid,exid,'2','sf_c') +
                _sf(tid,exid,'3','sf_d') - _sf(tid,exid,'3','sf_c') +
                _sf(tid,exid,'4','sf_d') - _sf(tid,exid,'4','sf_c') + tres)
    passif   = cap + _sf(tid,exid,'1','sf_c') - _sf(tid,exid,'1','sf_d') + dettes

    monthly = q("""
        SELECT strftime('%Y-%m',e.date_ecriture) as mois,
               COUNT(e.id) as nb_ecritures,
               COALESCE(SUM(CASE WHEN l.sens='D' THEN l.montant ELSE 0 END),0) as volume
        FROM ecritures e LEFT JOIN lignes_ecriture l ON e.id=l.ecriture_id
        WHERE e.tenant_id=? AND e.exercice_id=? AND e.statut != 'brouillon'
        GROUP BY mois ORDER BY mois""", (tid, exid))

    bal = _compute_balance(tid, exid, only_moved=True)
    nb_anom = sum(1 for r in bal if r['audit'])
    nb_crit = sum(1 for r in bal if r['audit_severite']=='critique')

    return jsonify({
        'ca': ca, 'charges': charges, 'resultat': res,
        'marge': round(res/ca*100, 2) if ca else 0,
        'tresorerie': tres, 'creances': creances, 'dettes': dettes,
        'capitaux_propres': cap,
        'autonomie': round(cap/(cap+dettes)*100, 2) if (cap+dettes)>0 else 0,
        'actif_total': max(actif, 0),
        'monthly': monthly,
        'nb_anomalies': nb_anom,
        'nb_critiques': nb_crit,
        'equilibre': abs(_sf(tid,exid,'','sf_d') - _sf(tid,exid,'','sf_c')) < 1
    })

# ═══════════════════════════════════════════════════════════════════
# TABLEAU DE FLUX DE TRÉSORERIE (TFT OHADA — méthode indirecte)
# ═══════════════════════════════════════════════════════════════════
@app.route('/api/<int:tid>/tft')
def get_tft(tid):
    exid = request.args.get('exercice_id')
    if not exid: exid, _ = _get_exercice_actif(tid)
    if not exid: return jsonify({})

    sf  = lambda pfx, c='sf_d': _sf(tid, exid, pfx, c)
    si  = lambda pfx, c='si_debit': _si(tid, exid, pfx, c)

    res       = sf('7','sf_c') - sf('6','sf_d')
    dot_amort = sf('68','sf_d')
    reprises  = sf('78','sf_c')
    var_stocks   = sf('3','sf_d') - si('3','si_debit')
    var_creances = sf('41','sf_d') - si('41','si_debit')
    var_fourn    = sf('40','sf_c') - si('40','si_credit')
    var_fisc     = sf('44','sf_c') - si('44','si_credit')
    var_autre    = (sf('42','sf_c') - si('42','si_credit') +
                    sf('43','sf_c') - si('43','si_credit'))
    flux_A = res + dot_amort - reprises - var_stocks - var_creances + var_fourn + var_fisc + var_autre

    immo_sfD = sf('2','sf_d'); immo_siD = si('2','si_debit')
    acquis   = -(immo_sfD - immo_siD)
    cessions = sf('82','sf_c')
    var_fin  = -(sf('26','sf_d')+sf('27','sf_d') - si('26','si_debit') - si('27','si_debit'))
    flux_B   = acquis + cessions + var_fin

    cap_var   = sf('10','sf_c') - si('10','si_credit')
    emp_sf    = sf('16','sf_c') + sf('17','sf_c')
    emp_si    = si('16','si_credit') + si('17','si_credit')
    nouv_emp  = max(0, emp_sf - emp_si)
    rembours  = -max(0, emp_si - emp_sf)
    divid     = -(max(0, si('13','si_debit') - sf('13','sf_d')))
    flux_C    = cap_var + nouv_emp + rembours + divid

    tres_ouv = (si('51','si_debit') - si('51','si_credit') +
                si('52','si_debit') - si('52','si_credit'))
    tres_clo = sf('51','sf_d')-sf('51','sf_c') + sf('52','sf_d')-sf('52','sf_c')
    var_nette = flux_A + flux_B + flux_C

    return jsonify({
        'exploitation': {
            'resultat_net': res,
            'dotations': dot_amort,
            'reprises': reprises,
            'var_stocks': -var_stocks,
            'var_creances': -var_creances,
            'var_dettes_fournisseurs': var_fourn,
            'var_dettes_fiscales': var_fisc,
            'var_autres_bfr': var_autre,
            'flux_net': flux_A
        },
        'investissement': {
            'acquisitions': acquis,
            'cessions': cessions,
            'var_immob_financieres': var_fin,
            'flux_net': flux_B
        },
        'financement': {
            'augmentation_capital': cap_var,
            'nouveaux_emprunts': nouv_emp,
            'remboursements': rembours,
            'dividendes': divid,
            'flux_net': flux_C
        },
        'tresorerie': {
            'ouverture': tres_ouv,
            'cloture': tres_clo,
            'variation': var_nette,
            'controle_ok': abs(tres_clo - tres_ouv - var_nette) < 1
        }
    })

# ═══════════════════════════════════════════════════════════════════
# GRAND LIVRE AUXILIAIRE
# ═══════════════════════════════════════════════════════════════════
@app.route('/api/<int:tid>/grand-livre')
def grand_livre(tid):
    exid    = request.args.get('exercice_id')
    compte  = request.args.get('compte', '')
    tiers   = request.args.get('tiers', '')
    limit   = min(int(request.args.get('limit', 300)), 1000)
    offset  = int(request.args.get('offset', 0))

    if not exid: exid, _ = _get_exercice_actif(tid)

    sql = """SELECT e.date_ecriture, e.numero as ecr_num, e.numero_piece,
        e.libelle as ecr_lib, l.sens, l.montant, l.libelle_ligne,
        c.intitule, c.numero as compte_num, j.code as journal_code
        FROM lignes_ecriture l
        JOIN ecritures e ON l.ecriture_id=e.id
        JOIN comptes c ON l.tenant_id=c.tenant_id AND l.compte_numero=c.numero
        LEFT JOIN journaux j ON e.journal_id=j.id
        WHERE l.tenant_id=? AND e.exercice_id=? AND e.statut != 'brouillon'"""
    params = [tid, exid]
    if tiers:
        sql += " AND l.compte_numero=?"; params.append(tiers)
    elif compte:
        sql += " AND l.compte_numero LIKE ?"; params.append(f'{compte}%')
    sql += " ORDER BY e.date_ecriture, e.id, l.ordre LIMIT ? OFFSET ?"
    params += [limit, offset]
    rows = q(sql, params)

    # Solde cumulatif
    si_row = None
    if tiers:
        si_row = q("SELECT COALESCE(si_debit,0) as d, COALESCE(si_credit,0) as c FROM soldes_ouverture WHERE tenant_id=? AND exercice_id=? AND compte_numero=?",
                   (tid, exid, tiers), one=True)
    solde = (si_row['d'] - si_row['c']) if si_row else 0
    for r in rows:
        solde += r['montant'] if r['sens']=='D' else -r['montant']
        r['solde_cumul'] = solde

    return jsonify({'rows': rows, 'total': len(rows), 'solde_final': solde})

# ═══════════════════════════════════════════════════════════════════
# CLIENTS & FOURNISSEURS (synthèse)
# ═══════════════════════════════════════════════════════════════════
@app.route('/api/<int:tid>/tiers')
def get_tiers(tid):
    exid    = request.args.get('exercice_id')
    prefixe = request.args.get('prefixe', '411')  # 411=clients, 40=fournisseurs
    if not exid: exid, _ = _get_exercice_actif(tid)
    rows = q("""SELECT c.numero, c.intitule,
        COALESCE(so.si_debit,0) as si_debit, COALESCE(so.si_credit,0) as si_credit,
        COALESCE(SUM(CASE WHEN l.sens='D' THEN l.montant ELSE 0 END),0) as mouv_debit,
        COALESCE(SUM(CASE WHEN l.sens='C' THEN l.montant ELSE 0 END),0) as mouv_credit,
        MAX(0,COALESCE(so.si_debit,0)+COALESCE(SUM(CASE WHEN l.sens='D' THEN l.montant ELSE 0 END),0)
            -COALESCE(so.si_credit,0)-COALESCE(SUM(CASE WHEN l.sens='C' THEN l.montant ELSE 0 END),0)) as sf_debit,
        MAX(0,COALESCE(so.si_credit,0)+COALESCE(SUM(CASE WHEN l.sens='C' THEN l.montant ELSE 0 END),0)
            -COALESCE(so.si_debit,0)-COALESCE(SUM(CASE WHEN l.sens='D' THEN l.montant ELSE 0 END),0)) as sf_credit
        FROM comptes c
        LEFT JOIN soldes_ouverture so ON so.tenant_id=c.tenant_id AND so.exercice_id=? AND so.compte_numero=c.numero
        LEFT JOIN lignes_ecriture l  ON l.tenant_id=c.tenant_id AND l.compte_numero=c.numero
        LEFT JOIN ecritures e        ON l.ecriture_id=e.id AND e.exercice_id=?
        WHERE c.tenant_id=? AND c.numero LIKE ? AND c.actif=1
        GROUP BY c.numero
        HAVING (mouv_debit+mouv_credit+si_debit+si_credit)>0
        ORDER BY (sf_debit+sf_credit) DESC""",
        (exid, exid, tid, f'{prefixe}%'))
    return jsonify(rows)

# ═══════════════════════════════════════════════════════════════════
# RAPPROCHEMENT & CONTRÔLE
# ═══════════════════════════════════════════════════════════════════
@app.route('/api/<int:tid>/rapprochement')
def rapprochement(tid):
    exid = request.args.get('exercice_id')
    if not exid: exid, _ = _get_exercice_actif(tid)

    # Écritures déséquilibrées
    deseq = q("""SELECT e.numero, e.date_ecriture, e.libelle,
        ABS(SUM(CASE WHEN l.sens='D' THEN l.montant ELSE -l.montant END)) as ecart
        FROM ecritures e JOIN lignes_ecriture l ON e.id=l.ecriture_id
        WHERE e.tenant_id=? AND e.exercice_id=?
        GROUP BY e.id HAVING ecart > 0.01 ORDER BY ecart DESC""", (tid, exid))

    # Comptes sans mouvement
    sans_mvt = q("""SELECT c.numero, c.intitule FROM comptes c
        WHERE c.tenant_id=? AND c.actif=1
        AND c.numero NOT IN (SELECT DISTINCT compte_numero FROM lignes_ecriture WHERE tenant_id=?)
        AND c.numero NOT IN (SELECT compte_numero FROM soldes_ouverture WHERE tenant_id=? AND exercice_id=?)
        ORDER BY c.numero LIMIT 10""", (tid,tid,tid,exid))

    # Totaux
    tot = q("""SELECT
        COALESCE(SUM(CASE WHEN l.sens='D' THEN l.montant ELSE 0 END),0) as td,
        COALESCE(SUM(CASE WHEN l.sens='C' THEN l.montant ELSE 0 END),0) as tc
        FROM lignes_ecriture l JOIN ecritures e ON l.ecriture_id=e.id
        WHERE e.tenant_id=? AND e.exercice_id=?""", (tid, exid), one=True)

    # Stats
    nb_ecr = q("SELECT COUNT(*) as n FROM ecritures WHERE tenant_id=? AND exercice_id=?", (tid,exid), one=True)['n']
    nb_lig = q("SELECT COUNT(*) as n FROM lignes_ecriture WHERE tenant_id=?", (tid,), one=True)['n']

    return jsonify({
        'ecritures_desequilibrees': deseq,
        'nb_desequilibre': len(deseq),
        'comptes_sans_mouvement': sans_mvt,
        'total_debit':  tot['td'] if tot else 0,
        'total_credit': tot['tc'] if tot else 0,
        'equilibre': abs((tot['td'] if tot else 0) - (tot['tc'] if tot else 0)) < 0.01,
        'nb_ecritures': nb_ecr,
        'nb_lignes': nb_lig
    })

# ═══════════════════════════════════════════════════════════════════
# RECHERCHE GLOBALE
# ═══════════════════════════════════════════════════════════════════
@app.route('/api/<int:tid>/search')
def search(tid):
    term = request.args.get('q', '').strip()
    if len(term) < 2: return jsonify({'comptes': [], 'ecritures': []})
    comptes = q("SELECT numero,intitule,sens_ohada FROM comptes WHERE tenant_id=? AND (numero LIKE ? OR intitule LIKE ?) LIMIT 8",
                (tid, f'%{term}%', f'%{term}%'))
    ecritures = q("SELECT numero,date_ecriture,libelle,numero_piece FROM ecritures WHERE tenant_id=? AND (libelle LIKE ? OR numero_piece LIKE ? OR numero LIKE ?) ORDER BY date_ecriture DESC LIMIT 8",
                  (tid, f'%{term}%', f'%{term}%', f'%{term}%'))
    return jsonify({'comptes': comptes, 'ecritures': ecritures})

# ═══════════════════════════════════════════════════════════════════
# IMPORT EXCEL
# ═══════════════════════════════════════════════════════════════════
@app.route('/api/<int:tid>/import-excel', methods=['POST'])
def import_excel(tid):
    import openpyxl
    if 'file' not in request.files:
        return jsonify({'error': 'Fichier manquant'}), 400

    f    = request.files['file']
    mode = request.form.get('mode', 'ecritures')
    exid = request.form.get('exercice_id')

    try:
        wb = openpyxl.load_workbook(io.BytesIO(f.read()), data_only=True, keep_vba=False)
    except Exception as e:
        return jsonify({'error': f'Fichier invalide: {e}'}), 400

    result = {'comptes': 0, 'si': 0, 'ecritures': 0, 'errors': []}

    # Import Plan de compte
    if mode in ('comptes','all') and 'Plan de compte' in wb.sheetnames:
        ws = wb['Plan de compte']
        for r in range(4, ws.max_row+1):
            num = ws.cell(r,1).value
            if not num or not str(num).strip()[:6].isdigit(): continue
            num = str(num).strip()[:6]
            intit = str(ws.cell(r,2).value or '').strip().lstrip(num).strip()
            cat  = str(ws.cell(r,4).value or '')
            sens = str(ws.cell(r,6).value or '')
            rubr = str(ws.cell(r,7).value or '')
            try:
                ex("INSERT OR REPLACE INTO comptes(tenant_id,numero,intitule,categorie,sens_ohada,rubrique) VALUES(?,?,?,?,?,?)",
                   (tid,num,intit,cat,sens,rubr))
                result['comptes'] += 1
            except Exception as e:
                result['errors'].append(f"Compte {num}: {e}")

    # Import Soldes d'ouverture
    if mode in ('si','all') and exid and 'Balance N-1' in wb.sheetnames:
        ws = wb['Balance N-1']
        for r in range(5, ws.max_row+1):
            num = ws.cell(r,1).value
            if not num: continue
            try:
                num = str(int(float(str(num))))
                d_v = float(ws.cell(r,4).value or 0)
                c_v = float(ws.cell(r,5).value or 0)
                if d_v > 0 or c_v > 0:
                    ex("""INSERT INTO soldes_ouverture(tenant_id,exercice_id,compte_numero,si_debit,si_credit,source)
                        VALUES(?,?,?,?,?,'import_excel')
                        ON CONFLICT(tenant_id,exercice_id,compte_numero)
                        DO UPDATE SET si_debit=excluded.si_debit,si_credit=excluded.si_credit""",
                       (tid, exid, num, d_v, c_v))
                    result['si'] += 1
            except: pass

    # Import Écritures
    if mode in ('ecritures','all') and exid and 'Données_Générales' in wb.sheetnames:
        ws  = wb['Données_Générales']
        ex_info = q("SELECT annee FROM exercices WHERE id=?", (exid,), one=True)
        yr  = ex_info['annee'] if ex_info else date.today().year
        base_n = q("SELECT COUNT(*) as n FROM ecritures WHERE tenant_id=? AND exercice_id=?", (tid,exid), one=True)['n']

        for r in range(3, ws.max_row+1):
            date_e  = ws.cell(r,3).value
            type_op = ws.cell(r,4).value
            piece   = ws.cell(r,5).value
            libelle = ws.cell(r,7).value
            lignes  = []
            for ci,mi in [(8,9),(10,11),(12,13)]:
                c,m = ws.cell(r,ci).value, ws.cell(r,mi).value
                if c and m and isinstance(m,(int,float)) and m>0:
                    lignes.append({'sens':'D','compte_numero':str(c)[:6],'montant':float(m)})
            for ci,mi in [(14,15),(16,17),(18,19)]:
                c,m = ws.cell(r,ci).value, ws.cell(r,mi).value
                if c and m and isinstance(m,(int,float)) and m>0:
                    lignes.append({'sens':'C','compte_numero':str(c)[:6],'montant':float(m)})
            if not lignes: continue
            try:
                base_n += 1
                num = f"ECR-{yr}-{base_n:04d}"
                eid = ex("INSERT INTO ecritures(tenant_id,exercice_id,numero,date_ecriture,libelle,type_operation,numero_piece,statut) VALUES(?,?,?,?,?,?,?,?)",
                         (tid,exid,num,str(date_e)[:10] if date_e else str(date.today()),
                          str(libelle or '')[:200],str(type_op or ''),str(piece or ''),'valide'))
                for i,l in enumerate(lignes):
                    ex("INSERT INTO lignes_ecriture(ecriture_id,tenant_id,sens,compte_numero,montant,ordre) VALUES(?,?,?,?,?,?)",
                       (eid,tid,l['sens'],l['compte_numero'],l['montant'],i))
                result['ecritures'] += 1
            except Exception as e:
                result['errors'].append(f"L{r}: {e}")

    return jsonify(result)

# ═══════════════════════════════════════════════════════════════════
# SEED DONNÉES PLANET RESOURCES
# ═══════════════════════════════════════════════════════════════════
def seed():
    data_path = Path('/home/claude/data_export.json')
    if not data_path.exists(): return

    db2 = sqlite3.connect(str(DB_PATH))
    if db2.execute("SELECT id FROM tenants WHERE code='PR'").fetchone():
        db2.close(); return

    data = json.loads(data_path.read_text())
    s    = data['societe']
    db2.execute("INSERT INTO tenants(code,nom,rccm,nif,devise,referentiel) VALUES(?,?,?,?,?,?)",
                ('PR',s['nom'],s['rccm'],s['nif'],s['devise'],s['referentiel']))
    tid = db2.execute("SELECT last_insert_rowid()").fetchone()[0]

    db2.execute("INSERT INTO exercices(tenant_id,annee,date_debut,date_fin) VALUES(?,2025,'2025-01-01','2025-12-31')", (tid,))
    exid = db2.execute("SELECT last_insert_rowid()").fetchone()[0]

    for code,lib,typ in [('AN','A-Nouveaux','a_nouveaux'),('BQ1','Banque RAWBANK','banque'),
                          ('BQ2','Banque EQUITY BCDC','banque'),('CA','Caisse Espèces','caisse'),
                          ('VT','Journal Ventes','vente'),('AC','Journal Achats','achat'),
                          ('OD','Opérations Diverses','od')]:
        db2.execute("INSERT OR IGNORE INTO journaux(tenant_id,code,libelle,type) VALUES(?,?,?,?)",(tid,code,lib,typ))

    for c in data['comptes']:
        num = c['numero']
        intit = c['intitule'].replace(num,'').strip() if c['intitule'].startswith(num) else c['intitule']
        db2.execute("INSERT OR IGNORE INTO comptes(tenant_id,numero,intitule,categorie,sens_ohada,rubrique) VALUES(?,?,?,?,?,?)",
                    (tid,num,intit,c['categorie'],c['sens_ohada'],c['rubrique']))

    for row in data['si']:
        if row['si_debit']>0 or row['si_credit']>0:
            db2.execute("INSERT OR REPLACE INTO soldes_ouverture(tenant_id,exercice_id,compte_numero,si_debit,si_credit,source) VALUES(?,?,?,?,?,'import_excel')",
                        (tid,exid,row['numero'],row['si_debit'],row['si_credit']))

    for i,e in enumerate(data['ecritures']):
        num = f"ECR-2025-{i+1:04d}"
        eid = db2.execute("INSERT INTO ecritures(tenant_id,exercice_id,numero,date_ecriture,libelle,type_operation,numero_piece,statut) VALUES(?,?,?,?,?,?,?,?)",
                          (tid,exid,num,e['date'] or '2025-01-01',e['libelle'],e['type'],e['piece'],'valide')).lastrowid
        for j,l in enumerate(e['lignes']):
            db2.execute("INSERT INTO lignes_ecriture(ecriture_id,tenant_id,sens,compte_numero,montant,ordre) VALUES(?,?,?,?,?,?)",
                        (eid,tid,l['sens'],l['compte'][:6],l['montant'],j))

    db2.commit()
    nb_ecr = db2.execute("SELECT COUNT(*) FROM ecritures WHERE tenant_id=?",(tid,)).fetchone()[0]
    print(f"  Planet Resources: {len(data['comptes'])} comptes · {nb_ecr} écritures")
    db2.close()

# ═══════════════════════════════════════════════════════════════════
# DÉMARRAGE
# ═══════════════════════════════════════════════════════════════════
if __name__ == '__main__':
    print("\n" + "="*52)
    print("  SYSCO ERP v2.0 — Comptabilité OHADA")
    print("="*52)
    print(f"  Base : {DB_PATH}")
    print(f"  URL  : http://localhost:5000")
    print("="*52)
    init_db()
    print("  Base de données : initialisée")
    seed()
    print("  Données         : chargées")
    print("  Serveur         : démarrage...\n")
    app.run(debug=False, host='0.0.0.0', port=5000, use_reloader=False)
