"""Génération des déclencheurs d'audit SQLite/PostgreSQL.

Les migrations figent leur propre plan de colonnes. Les requêtes groupées,
les écritures SQL et les suppressions sont ainsi couvertes sans signaux ORM.
"""
import hashlib
import json

EXCLUDED={'audit_log','sequence_compteur'}
SENSITIVE=('password','secret','token','signature','contenu','remuneration','resultat','parametres','decisions','echeancier')
HR_PUBLIC={'id','societe_id','revision','statut','agent_id','contrat_id','periode_id','bulletin_id','dette_id','type_contrat','nature','date','mois','debut','fin','created_at','updated_at','created_by','updated_by'}
# Relations UUID historiques qui ne sont pas des ForeignKey Django.
PARENTS={
 'blocage_beneficiaire':('avance_id','avance'), 'bon_reception':('ordre_depense_id','ordre_depense'),
 'justification':('avance_id','avance'), 'justification_ligne':('justification_id','justification'),
 'mouvement_caisse':('caisse_id','caisse'), 'session_caisse':('caisse_id','caisse'),
 'requisition_ligne':('requisition_id','requisition'), 'requisition_commentaire':('requisition_id','requisition'),
 'ligne_facture':('facture_id','facture'), 'frais_facture':('facture_id','facture'), 'paiement_facture':('facture_id','facture'),
 'ligne_commande':('commande_id','commande'), 'ligne_reception':('reception_id','reception'), 'frais_reception':('reception_id','reception'),
 'ligne_devis':('devis_id','devis'), 'ligne_livraison':('livraison_id','livraison'),
 'stock_depot':('depot_id','depot'), 'ligne_transfert_depot':('transfert_id','transfert_depot'),
 'ligne_fiche_technique':('fiche_id','fiche_technique'), 'ligne_consommation_cuisine':('consommation_id','consommation_cuisine'),
 'ligne_inventaire_depot':('inventaire_id','inventaire_depot'), 'ligne_sejour':('sejour_id','sejour'),
 'tarif_article':('liste_prix_id','liste_prix'), 'tarif_contrat':('contrat_id','contrat_transport'),
 'course_requisition':('course_id','course'), 'ligne_reception_inter':('reception_id','reception_inter'),
 'arret_prestation_engin':('prestation_id','prestation_engin'), 'palier_approbateur':('palier_id','palier_validation'),
}


def build_plan(registry):
    plan=[]
    for model in registry.get_models():
        if model._meta.app_label in ('contenttypes',) or model._meta.db_table in EXCLUDED:continue
        fields=[]
        for f in model._meta.local_fields:
            fields.append({'name':f.column,'type':f.get_internal_type(),
                'private':any(k in f.column.lower() for k in SENSITIVE) or f.get_internal_type() in ('BinaryField','JSONField')
                or (model._meta.app_label=='rh' and f.column not in HR_PUBLIC)
                or (model._meta.db_table=='parametre' and f.column=='valeur')})
        plan.append({'table':model._meta.db_table,'module':model._meta.app_label,'fields':fields,'pk':model._meta.pk.column})
    return sorted(plan,key=lambda t:t['table'])


def literal(value):return "'"+str(value).replace("'","''")+"'"
def quote(value):return '"'+value.replace('"','""')+'"'


def scope_sql(spec,ref,plan,seen=()):
    table=spec['table'];names={f['name'] for f in spec['fields']}
    if 'societe_id' in names:return f'{ref}."societe_id"'
    if table=='societe':return f'{ref}."id"'
    if table in seen:return 'NULL'
    if table in ('piece_jointe','validation'):
        cases=[]
        for target in plan:
            if target['table'] in (*seen,table) or target['table'] in ('piece_jointe','validation'):continue
            inner=scope_sql(target,'document',plan,(*seen,table))
            if inner=='NULL':continue
            cases.append(f'WHEN {literal(target["table"])} THEN (SELECT {inner} FROM {quote(target["table"])} document WHERE document.{quote(target["pk"])}={ref}."document_id")')
        return f'CASE {ref}."document_type" '+ ' '.join(cases)+' ELSE NULL END'
    if table in PARENTS:
        key,parent=PARENTS[table];target=next((t for t in plan if t['table']==parent),None)
        if key in names and target:
            alias='parent_'+str(len(seen));inner=scope_sql(target,alias,plan,(*seen,table))
            return f'(SELECT {inner} FROM {quote(parent)} {alias} WHERE {alias}."id"={ref}.{quote(key)})'
    return 'NULL'


def names(spec):
    key=hashlib.sha256(spec['table'].encode()).hexdigest()[:12]
    return {verb:f'kh_audit_{key}_{verb.lower()}' for verb in ('INSERT','UPDATE','DELETE')}


def statements(spec,plan,vendor):
    sqlite=vendor=='sqlite'; table=spec['table'];fields=spec['fields'];out=[]
    js='json_object' if sqlite else 'jsonb_build_object'
    def snapshot(ref):
        parts=[]
        for f in fields:
            v=f'{ref}.{quote(f["name"])}'
            if f['private']:v=f'CASE WHEN {v} IS NULL THEN NULL ELSE \'[masqué]\' END'
            elif f['type'] in ('CharField','TextField','EmailField'):v=f'substr(CAST({v} AS TEXT),1,2000)'
            parts.extend([literal(f['name']),v])
        if sqlite:
            rows=' UNION ALL '.join(f'SELECT {parts[i]} AS champ, {parts[i+1]} AS valeur' for i in range(0,len(parts),2))
            return f'(SELECT json_group_object(champ,valeur) FROM ({rows}) valeurs_audit)'
        # PostgreSQL limite aussi les arguments d'une fonction.
        chunks=[js+'('+','.join(parts[i:i+40])+')' for i in range(0,len(parts),40)]
        result=chunks[0]
        for chunk in chunks[1:]:result=f'json_patch({result},{chunk})' if sqlite else f'({result} || {chunk})'
        return result
    def changed():
        comparisons=[(f['name'],f'OLD.{quote(f["name"])} IS NOT NEW.{quote(f["name"])}' if sqlite else f'OLD.{quote(f["name"])} IS DISTINCT FROM NEW.{quote(f["name"])}') for f in fields]
        return comparisons
    for verb,name in names(spec).items():
        ref='OLD' if verb=='DELETE' else 'NEW';old=snapshot('OLD') if verb!='INSERT' else 'NULL';new=snapshot('NEW') if verb!='DELETE' else 'NULL'
        predicate=' OR '.join(c for _,c in changed())
        if verb=='UPDATE':
            selects=' UNION ALL '.join(f'SELECT {literal(n)} AS champ WHERE {condition}' for n,condition in changed())
            diffs=f'(SELECT {"json_group_array(champ)" if sqlite else "jsonb_agg(champ)"} FROM ({selects}) changements)'
        else:diffs=("json("+literal(json.dumps([f['name'] for f in fields]))+")") if sqlite else (literal(json.dumps([f['name'] for f in fields]))+'::jsonb')
        def context(key):
            if sqlite:return 'kilima_audit('+literal(key)+')'
            v=f"(NULLIF(current_setting('kilima.audit_context',true),'')::jsonb ->> {literal(key)})"
            return v+'::uuid' if key in ('utilisateur_id','requete_id') else v
        timestamp=context('horodatage') if sqlite else "(clock_timestamp() AT TIME ZONE 'UTC')"
        record=f'CAST({ref}.{quote(spec["pk"])} AS TEXT)'
        columns=['utilisateur_id','action','table_cible','enregistrement_id','ancienne_valeur','nouvelle_valeur','adresse_ip','horodatage','societe_id','module','categorie','champs_modifies','requete_id','methode','chemin','origine']
        vals=[context('utilisateur_id'),literal(verb),literal(table),record,old,new,context('adresse_ip'),timestamp,scope_sql(spec,ref,plan),literal(spec['module']),"'donnees'",diffs,context('requete_id'),f"COALESCE({context('methode')},'')",f"COALESCE({context('chemin')},'')",f"COALESCE({context('origine')},'systeme')"]
        insert=f'INSERT INTO audit_log ({",".join(quote(c) for c in columns)}) VALUES ({",".join(vals)});'
        if sqlite:
            out.append(f'CREATE TRIGGER {quote(name)} {"BEFORE" if verb=="DELETE" else "AFTER"} {verb} ON {quote(table)} '+(f'WHEN {predicate} ' if verb=='UPDATE' else '')+f'BEGIN {insert} END')
        else:
            out.append(f'CREATE FUNCTION {quote(name)}() RETURNS trigger LANGUAGE plpgsql AS $audit$ BEGIN '+(f'IF {predicate} THEN ' if verb=='UPDATE' else '')+insert+(' END IF;' if verb=='UPDATE' else '')+f' RETURN {ref}; END; $audit$')
            out.append(f'CREATE TRIGGER {quote(name)} {"BEFORE" if verb=="DELETE" else "AFTER"} {verb} ON {quote(table)} FOR EACH ROW EXECUTE FUNCTION {quote(name)}()')
    return out


def install(schema_editor,plan):
    vendor=schema_editor.connection.vendor
    if vendor not in ('sqlite','postgresql'):raise RuntimeError('Audit : moteur de base non pris en charge.')
    for spec in plan:
        for sql in statements(spec,plan,vendor):schema_editor.execute(sql)
    if vendor=='sqlite':
        schema_editor.execute("CREATE TRIGGER kh_audit_no_replace BEFORE INSERT ON audit_log WHEN EXISTS (SELECT 1 FROM audit_log WHERE id=NEW.id) BEGIN SELECT RAISE(ABORT,'Journal audit en lecture seule'); END")
        for verb in ('UPDATE','DELETE'):
            schema_editor.execute(f"CREATE TRIGGER kh_audit_no_{verb.lower()} BEFORE {verb} ON audit_log BEGIN SELECT RAISE(ABORT,'Journal audit en lecture seule'); END")
    else:
        schema_editor.execute("CREATE FUNCTION kh_audit_immutable() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'Journal audit en lecture seule'; END; $$")
        schema_editor.execute('CREATE TRIGGER kh_audit_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON audit_log FOR EACH STATEMENT EXECUTE FUNCTION kh_audit_immutable()')


def uninstall(schema_editor,plan):
    sqlite=schema_editor.connection.vendor=='sqlite'
    for spec in plan:
        for name in names(spec).values():
            schema_editor.execute(f'DROP TRIGGER IF EXISTS {quote(name)}'+('' if sqlite else ' ON '+quote(spec['table'])))
            if not sqlite:schema_editor.execute(f'DROP FUNCTION IF EXISTS {quote(name)}()')
    if sqlite:
        schema_editor.execute('DROP TRIGGER IF EXISTS kh_audit_no_replace')
        for verb in ('update','delete'):schema_editor.execute('DROP TRIGGER IF EXISTS kh_audit_no_'+verb)
    else:
        schema_editor.execute('DROP TRIGGER IF EXISTS kh_audit_immutable ON audit_log')
        schema_editor.execute('DROP FUNCTION IF EXISTS kh_audit_immutable()')
